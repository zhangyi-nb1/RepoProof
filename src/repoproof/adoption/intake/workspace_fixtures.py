"""Human-confirmable fixture blueprints for workspace-bundle Product tasks.

An LLM may propose scenario metadata, but only a frozen task-owned builder
creates bytes.  Confirmations bind the exact builder and generated file tree;
candidate regeneration never silently drops an already confirmed fixture.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from repoproof.domain.models import validate_workspace_relative_path
from repoproof.execution.core_execution import atomic_write_json
from repoproof.execution.offline_sandbox import (
    OfflineSandboxUnavailable,
    offline_sandbox_argv,
    sanitised_subprocess_env,
)
from repoproof.execution.workspace_bundle import (
    InputPathIdentityV1,
    WorkspaceBundleError,
    snapshot_admitted_path,
)

_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")
_RUNNER = r'''import importlib.util
import json
import sys
from pathlib import Path

source, blueprint_json, output_path = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("repoproof_task_fixture_builder", source)
if spec is None or spec.loader is None:
    raise RuntimeError("fixture builder cannot be loaded")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
build = getattr(module, "build", None)
if not callable(build):
    raise TypeError("fixture builder must export build(blueprint, output_path)")
blueprint = json.loads(blueprint_json)
build(blueprint, Path(output_path))
'''


class FixtureBlueprintV1(BaseModel):
    """Natural scenario metadata; never an LLM-supplied binary payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blueprint_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    scenario: str = Field(min_length=1, max_length=1200)
    input_kind: Literal["file", "directory"]
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("blueprint_id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        if value[0] not in "abcdefghijklmnopqrstuvwxyz0123456789" or any(
            char not in _ID_CHARS for char in value
        ):
            raise ValueError("blueprint_id must be a lowercase safe slug")
        return value

    @field_validator("parameters")
    @classmethod
    def _json_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > 32_000:
            raise ValueError("fixture blueprint parameters are too large")
        return value


class InputFixtureCandidateV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    blueprint: FixtureBlueprintV1
    builder_id: str = Field(min_length=1, max_length=128)
    builder_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fixture_path: str
    fixture_identity: InputPathIdentityV1
    confirmed: bool = False

    @model_validator(mode="after")
    def _kind_matches_blueprint(self) -> InputFixtureCandidateV1:
        if self.fixture_identity.kind != self.blueprint.input_kind:
            raise ValueError("fixture builder output kind mismatches blueprint")
        return self


class InputFixtureBundleV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    generation_id: str = Field(min_length=1, max_length=128)
    candidates: tuple[InputFixtureCandidateV1, ...] = Field(
        min_length=1, max_length=12
    )

    @model_validator(mode="after")
    def _candidate_ids_are_unique(self) -> InputFixtureBundleV1:
        ids = [item.blueprint.blueprint_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("fixture blueprint ids must be unique")
        input_identities = [
            (item.fixture_identity.kind, item.fixture_identity.sha256)
            for item in self.candidates
        ]
        if len(input_identities) != len(set(input_identities)):
            raise ValueError("fixture inputs must be unique")
        return self


class FixtureBuilderError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


_PATH_VALUE_FIELDS = frozenset(
    {"file", "files", "filename", "filenames", "path", "paths", "relative_path"}
)


def _portable_path_map(seed_values: tuple[object, ...]) -> bool:
    dictionaries = [value for value in seed_values if isinstance(value, dict)]
    if not dictionaries:
        return False
    keys = [str(key) for value in dictionaries for key in value]
    if not keys or not any("/" in key or "." in Path(key).name for key in keys):
        return False
    try:
        for key in keys:
            validate_workspace_relative_path(key)
    except ValueError:
        return False
    return True


def _validate_parameter_paths(
    value: object,
    *,
    seed_values: tuple[object, ...],
    field_name: str = "",
) -> None:
    if isinstance(value, dict):
        if _portable_path_map(seed_values):
            for key in value:
                try:
                    validate_workspace_relative_path(str(key))
                except ValueError as exc:
                    raise FixtureBuilderError(
                        "FIXTURE_BLUEPRINT_NONPORTABLE_PATH"
                    ) from exc
        seed_dicts = [item for item in seed_values if isinstance(item, dict)]
        for key, child in value.items():
            child_seeds = tuple(item[key] for item in seed_dicts if key in item)
            _validate_parameter_paths(
                child,
                seed_values=child_seeds,
                field_name=str(key).lower(),
            )
        return
    if isinstance(value, list):
        seed_items = tuple(
            child
            for item in seed_values
            if isinstance(item, list)
            for child in item
        )
        for child in value:
            _validate_parameter_paths(
                child,
                seed_values=seed_items,
                field_name=field_name,
            )
        return
    if isinstance(value, str) and field_name in _PATH_VALUE_FIELDS:
        seed_strings = tuple(item for item in seed_values if isinstance(item, str))
        if not seed_strings:
            return
        try:
            for seed in seed_strings:
                validate_workspace_relative_path(seed)
            validate_workspace_relative_path(value)
        except ValueError as exc:
            raise FixtureBuilderError(
                "FIXTURE_BLUEPRINT_NONPORTABLE_PATH"
            ) from exc


def validate_fixture_blueprint_portable_paths(
    blueprint: FixtureBlueprintV1,
    *,
    seeds: tuple[FixtureBlueprintV1, ...],
) -> None:
    """Reject model parameters that would create non-portable fixture paths.

    Path-bearing parameter positions are inferred from the frozen seed shape;
    arbitrary Unicode scenario text and file contents remain valid.  This keeps
    task-specific builders expressive without letting a model-proposed filename
    reach the filesystem before the common workspace policy is applied.
    """

    _validate_parameter_paths(
        blueprint.parameters,
        seed_values=tuple(seed.parameters for seed in seeds),
    )


def assert_distinct_fixture_inputs(
    candidates: list[InputFixtureCandidateV1]
    | tuple[InputFixtureCandidateV1, ...],
) -> None:
    """Reject multiple scenarios that bind to the same exact input bytes.

    Blueprint labels are suggestions, not coverage evidence.  Two distinct
    labels backed by the same admitted input cannot count as two representative
    fixtures, regardless of whether their expected artifacts are also equal.
    """

    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        identity = (
            candidate.fixture_identity.kind,
            candidate.fixture_identity.sha256,
        )
        if identity in seen:
            raise FixtureBuilderError("FIXTURE_INPUT_DUPLICATE")
        seen.add(identity)


def _read_builder_source(path: Path) -> bytes:
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FixtureBuilderError("FIXTURE_BUILDER_UNREADABLE") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise FixtureBuilderError("FIXTURE_BUILDER_UNSAFE")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise FixtureBuilderError("FIXTURE_BUILDER_CHANGED_DURING_READ")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def build_fixture_candidate(
    *,
    blueprint: FixtureBlueprintV1,
    builder_id: str,
    builder_source: Path,
    fixture_root: Path,
    python_exe: str,
    isolation_required: bool = True,
    timeout_s: int = 60,
) -> InputFixtureCandidateV1:
    """Execute a frozen builder and publish one exact, inspectable fixture."""

    if not python_exe:
        raise FixtureBuilderError("FIXTURE_BUILDER_PYTHON_MISSING")
    source_bytes = _read_builder_source(Path(builder_source))
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    fixture_root = Path(fixture_root)
    fixture_root.mkdir(parents=True, exist_ok=True)
    if fixture_root.is_symlink():
        raise FixtureBuilderError("FIXTURE_ROOT_UNSAFE")
    destination = fixture_root / blueprint.blueprint_id
    if destination.exists() or destination.is_symlink():
        raise FixtureBuilderError("FIXTURE_DESTINATION_EXISTS")

    with tempfile.TemporaryDirectory(prefix="rp-fixture-builder-") as temp:
        root = Path(temp)
        source_snapshot = root / "fixture_builder.py"
        source_snapshot.write_bytes(source_bytes)
        source_snapshot.chmod(0o400)
        runner = root / "runner.py"
        runner.write_text(_RUNNER, encoding="utf-8")
        runner.chmod(0o400)
        generated = root / "generated"
        argv = [
            python_exe,
            str(runner),
            str(source_snapshot),
            json.dumps(blueprint.model_dump(mode="json"), ensure_ascii=False),
            str(generated),
        ]
        if isolation_required:
            try:
                argv = offline_sandbox_argv(argv, root)
            except OfflineSandboxUnavailable as exc:
                raise FixtureBuilderError("FIXTURE_BUILDER_ISOLATION_UNAVAILABLE") from exc
        try:
            process = subprocess.run(  # noqa: S603 - frozen argv, no shell
                argv,
                cwd=root,
                env=sanitised_subprocess_env(root, [str(root)]),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FixtureBuilderError("FIXTURE_BUILDER_EXECUTION_FAILED") from exc
        if process.returncode != 0:
            raise FixtureBuilderError(
                "FIXTURE_BUILDER_FAILED", type(process).__name__
            )
        try:
            identity = snapshot_admitted_path(generated, destination)
        except WorkspaceBundleError as exc:
            raise FixtureBuilderError(exc.code, exc.detail) from exc

    return InputFixtureCandidateV1(
        blueprint=blueprint,
        builder_id=builder_id,
        builder_source_sha256=source_sha,
        fixture_path=str(destination.resolve()),
        fixture_identity=identity,
    )


def confirm_fixture_candidate(
    candidate: InputFixtureCandidateV1,
) -> InputFixtureCandidateV1:
    """Human gate: bind confirmation to the already generated exact bytes."""

    return candidate.model_copy(update={"confirmed": True})


def merge_regenerated_fixture_bundle(
    previous: InputFixtureBundleV1 | None,
    generated: InputFixtureBundleV1,
) -> InputFixtureBundleV1:
    """Keep confirmed exact fixtures while replacing unconfirmed suggestions."""

    if previous is None:
        return generated
    current = {item.blueprint.blueprint_id: item for item in generated.candidates}
    retained: list[InputFixtureCandidateV1] = []
    for old in previous.candidates:
        if not old.confirmed:
            continue
        replacement = current.get(old.blueprint.blueprint_id)
        if replacement is not None and (
            replacement.builder_source_sha256 == old.builder_source_sha256
            and replacement.fixture_identity == old.fixture_identity
        ):
            current[old.blueprint.blueprint_id] = replacement.model_copy(
                update={"confirmed": True}
            )
        else:
            retained.append(old)
            # A regenerated suggestion may reuse the same human-facing id with
            # different bytes.  The confirmed exact fixture wins; keeping both
            # would either erase the confirmation or create an invalid duplicate.
            current.pop(old.blueprint.blueprint_id, None)
    seen_inputs = {
        (item.fixture_identity.kind, item.fixture_identity.sha256)
        for item in retained
    }
    for item in generated.candidates:
        candidate = current.get(item.blueprint.blueprint_id)
        if candidate is None:
            continue
        identity = (
            candidate.fixture_identity.kind,
            candidate.fixture_identity.sha256,
        )
        if identity in seen_inputs:
            continue
        retained.append(candidate)
        seen_inputs.add(identity)
    return InputFixtureBundleV1(
        generation_id=generated.generation_id,
        candidates=tuple(retained),
    )


def write_fixture_bundle(path: Path, bundle: InputFixtureBundleV1) -> Path:
    """Atomically update editable pre-freeze fixture navigation state."""

    atomic_write_json(Path(path), bundle.model_dump(mode="json"))
    return Path(path)


def remove_unconfirmed_fixture(candidate: InputFixtureCandidateV1) -> None:
    """Cleanup helper for discarded pre-freeze bytes; confirmed bytes are immutable."""

    if candidate.confirmed:
        raise FixtureBuilderError("CONFIRMED_FIXTURE_IS_IMMUTABLE")
    path = Path(candidate.fixture_path)
    if path.is_symlink():
        raise FixtureBuilderError("FIXTURE_PATH_UNSAFE")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.is_file():
        path.unlink()
