"""Generic execution and evidence binding for task-authored semantic verifiers.

The Harness must not learn repository-specific semantics just to make a
qualification case pass.  A frozen task may instead provide an independent
oracle module exposing ``verify(input_path, artifact_path)``.  This module
executes that verifier in the same offline/write-contained boundary used for
reference work, proves that the declared pinned upstream was called at runtime,
and emits a self-contained evidence record bound to the exact verifier, input,
artifact, upstream commit, output contract, and confirmed intent.

RepoProof deliberately does not interpret the verifier's domain vocabulary.
Only the protocol, identities, runtime evidence, and stable result codes are
Harness responsibilities.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from repoproof.execution.import_hook import (
    ENV_LEDGER,
    ENV_MODULE,
    ENV_SECRET,
    verify_import_receipts,
    write_hook_dir,
)
from repoproof.execution.offline_sandbox import (
    OfflineSandboxUnavailable,
    offline_sandbox_argv,
    sanitised_subprocess_env,
)

SEMANTIC_VERIFIER_PROTOCOL = "repoproof-semantic-verifier-v1"
_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,255}")
_MODULE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_REASON_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SHA256_RE = r"^[0-9a-f]{64}$"
_COMMIT_RE = r"^[0-9a-f]{40}$"
_OUTPUT_CAP = 20_000
_MECHANISM_REASON_CODES = frozenset({
    "ARTIFACT_BINDING_CONTROL_FAILED",
    "COMMITMENT_COVERAGE_MISMATCH",
    "INPUT_BINDING_CONTROL_FAILED",
    "UPSTREAM_RESULT_BINDING_CONTROL_FAILED",
    "UPSTREAM_CALL_NOT_OBSERVED",
    "VERIFIER_PROTOCOL_ERROR",
})


class SemanticVerifierError(RuntimeError):
    """The Harness could not safely execute or persist verifier evidence."""


class SemanticVerifierEvidenceV1(BaseModel):
    """Immutable facts from one semantic-verifier execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # This class name is retained as the public import surface.  Evidence v3 is
    # the first evidence shape strong enough for ToolSpec v3 operational use:
    # it binds execution to immutable snapshots and includes three generic
    # sensitivity controls (input, artifact, and upstream result).  No released
    # ToolSpec v1/v2 package consumes this
    # evidence type.
    schema_version: Literal[3] = 3
    protocol: Literal["repoproof-semantic-verifier-v1"] = (
        "repoproof-semantic-verifier-v1"
    )
    verifier_id: str
    verifier_source_sha256: str = Field(pattern=_SHA256_RE)
    input_sha256: str = Field(pattern=_SHA256_RE)
    artifact_sha256: str = Field(pattern=_SHA256_RE)
    output_contract_sha256: str = Field(pattern=_SHA256_RE)
    intent_confirmation_sha256: str = Field(pattern=_SHA256_RE)
    upstream_commit: str = Field(pattern=_COMMIT_RE)
    import_module: str
    upstream_imports: int = Field(ge=0)
    upstream_calls: int = Field(ge=0)
    input_negative_control_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_RE,
    )
    input_negative_control_result: Literal[
        "NOT_RUN", "REJECTED", "ACCEPTED", "UNTRUSTED"
    ] = "NOT_RUN"
    input_negative_control_upstream_imports: int = Field(default=0, ge=0)
    input_negative_control_upstream_calls: int = Field(default=0, ge=0)
    artifact_negative_control_sha256: str | None = Field(
        default=None,
        pattern=_SHA256_RE,
    )
    artifact_negative_control_result: Literal[
        "NOT_RUN", "REJECTED", "ACCEPTED", "UNTRUSTED"
    ] = "NOT_RUN"
    artifact_negative_control_upstream_imports: int = Field(default=0, ge=0)
    artifact_negative_control_upstream_calls: int = Field(default=0, ge=0)
    upstream_result_counterfactual_result: Literal[
        "NOT_RUN", "REJECTED", "ACCEPTED", "UNTRUSTED"
    ] = "NOT_RUN"
    upstream_result_counterfactual_upstream_imports: int = Field(default=0, ge=0)
    upstream_result_counterfactual_upstream_calls: int = Field(default=0, ge=0)
    required_commitment_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    checked_commitment_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    passed: bool
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=32)

    @field_validator("verifier_id")
    @classmethod
    def _safe_verifier_id(cls, value: str) -> str:
        value = value.strip()
        if _ID_RE.fullmatch(value) is None:
            raise ValueError("verifier_id must be a safe lowercase identifier")
        return value

    @field_validator("import_module")
    @classmethod
    def _safe_import_module(cls, value: str) -> str:
        value = value.strip()
        if _MODULE_RE.fullmatch(value) is None:
            raise ValueError("import_module must be a dotted Python identifier")
        return value

    @field_validator("reason_codes")
    @classmethod
    def _safe_reason_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_REASON_RE.fullmatch(item) is None for item in value):
            raise ValueError("reason_codes must be stable uppercase identifiers")
        if len(value) != len(set(value)):
            raise ValueError("reason_codes must be unique")
        return value

    @field_validator("required_commitment_ids", "checked_commitment_ids")
    @classmethod
    def _safe_commitment_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_ID_RE.fullmatch(item) is None for item in value):
            raise ValueError("commitment ids must be safe stable identifiers")
        if len(value) != len(set(value)):
            raise ValueError("commitment ids must be unique")
        return value

    @model_validator(mode="after")
    def _passed_requires_binding_controls(self) -> SemanticVerifierEvidenceV1:
        """A v3 semantic PASS is impossible without all sensitivity controls.

        The artifact control is intentionally not required to call upstream.
        A verifier is free to inspect and reject a substituted artifact before
        it evaluates the input.  Requiring a receipt in that run would make
        the trust decision depend on verifier statement order rather than on
        the three facts the controls establish together:

        * the actual pair is accepted after a real upstream call;
        * a different artifact is not accepted; and
        * replacing the upstream result prevents acceptance after a call.
        """

        if self.passed and (
            self.input_negative_control_result != "REJECTED"
            or self.input_negative_control_sha256 is None
            or self.artifact_negative_control_result != "REJECTED"
            or self.artifact_negative_control_sha256 is None
            or self.upstream_result_counterfactual_result != "REJECTED"
            or self.upstream_result_counterfactual_upstream_calls < 1
        ):
            raise ValueError(
                "semantic verifier PASS requires input, artifact, and upstream-result controls"
            )
        return self


class SemanticCandidateScreenV1(BaseModel):
    """Advisory pre-confirmation result for one input/artifact pair.

    This is deliberately not operational evidence: it has no frozen contract
    or human-confirmation identity and is never written to the release ledger.
    It exists only to stop Studio from calling a reference-produced string
    "confirmable" when the independent task verifier rejects the pair.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    mechanism_ok: bool
    passed: bool
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    checked_commitment_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    upstream_imports: int = Field(ge=0)
    upstream_calls: int = Field(ge=0)

    @field_validator("reason_codes")
    @classmethod
    def _valid_screen_reason_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_REASON_RE.fullmatch(item) is None for item in value):
            raise ValueError("candidate screen reason_codes must be stable identifiers")
        if len(value) != len(set(value)):
            raise ValueError("candidate screen reason_codes must be unique")
        return value

    @field_validator("checked_commitment_ids")
    @classmethod
    def _valid_screen_commitment_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_ID_RE.fullmatch(item) is None for item in value):
            raise ValueError("candidate screen commitment ids are invalid")
        if len(value) != len(set(value)):
            raise ValueError("candidate screen commitment ids must be unique")
        return value

    @model_validator(mode="after")
    def _pass_requires_a_sound_mechanism(self) -> SemanticCandidateScreenV1:
        if self.passed and (not self.mechanism_ok or self.reason_codes):
            raise ValueError("candidate screen PASS requires a sound mechanism")
        return self


_RUNNER = r'''import importlib.util
import json
import sys
from pathlib import Path

source, input_path, artifact_path, control = sys.argv[1:5]
try:
    if control == "upstream-result-counterfactual":
        from repoproof_counterfactual_hook import install
        install()
    spec = importlib.util.spec_from_file_location("repoproof_task_semantic_verifier", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("verifier module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    verify = getattr(module, "verify", None)
    if not callable(verify):
        raise TypeError("verifier must export verify(input_path, artifact_path)")
    result = verify(Path(input_path), Path(artifact_path))
    if not isinstance(result, dict) or set(result) != {
        "ok", "reason_codes", "checked_commitment_ids"
    } or not isinstance(result.get("ok"), bool):
        raise TypeError("verifier result must be an object with boolean ok")
    reasons = result.get("reason_codes") or []
    if not isinstance(reasons, list) or not all(isinstance(item, str) for item in reasons):
        raise TypeError("reason_codes must be a string list")
    checked = result.get("checked_commitment_ids") or []
    if not isinstance(checked, list) or not all(isinstance(item, str) for item in checked):
        raise TypeError("checked_commitment_ids must be a string list")
    print(json.dumps({
        "ok": result["ok"],
        "reason_codes": reasons,
        "checked_commitment_ids": checked,
    }))
except BaseException as exc:
    print(json.dumps({"fatal_type": type(exc).__name__}))
'''


# Loaded *after* the signed receipt hook and inserted immediately behind it.
# The receipt hook therefore wraps these counterfactual proxies and records the
# attempted upstream call before the proxy returns a hostile sentinel.  A
# verifier that merely calls upstream and ignores its return value will still
# report PASS and is rejected.  A verifier that consumes the returned value
# must report FAIL or terminate under this run.  This is deliberately about
# data dependence, not any repository/API/format vocabulary.
_COUNTERFACTUAL_HOOK = r'''import importlib.abc
import importlib.util
import os
import sys


class _ControlledResult:
    __slots__ = ()

    def _used(self, *args, **kwargs):
        raise RuntimeError("controlled upstream result was consumed")

    __bool__ = _used
    __bytes__ = _used
    __call__ = _used
    __contains__ = _used
    __enter__ = _used
    __exit__ = _used
    __float__ = _used
    __getitem__ = _used
    __index__ = _used
    __int__ = _used
    __iter__ = _used
    __len__ = _used
    __next__ = _used
    __setitem__ = _used

    def __getattr__(self, name):
        self._used()

    def __eq__(self, other):
        return False

    def __ne__(self, other):
        return True

    def __repr__(self):
        return "<controlled-upstream-result>"

    def __str__(self):
        return "controlled-upstream-result"


_RESULT = _ControlledResult()


def install():
    module = os.environ.get("REPOPROOF_HOOK_MODULE", "")
    if not module:
        raise RuntimeError("counterfactual target module is absent")
    wrapped_class_ids = set()

    def _replace_callables(mod, modname):
        for name in list(vars(mod)):
            if name.startswith("_"):
                continue
            obj = getattr(mod, name, None)
            if getattr(obj, "__module__", None) != modname:
                continue
            if not callable(obj) or isinstance(obj, type(sys)):
                continue
            if isinstance(obj, type):
                try:
                    if issubclass(obj, BaseException):
                        continue
                except TypeError:
                    continue
                if id(obj) in wrapped_class_ids:
                    continue

                def _make_new():
                    def _new(cls, *args, **kwargs):
                        return _RESULT
                    return staticmethod(_new)

                try:
                    setattr(obj, "__new__", _make_new())
                except (AttributeError, TypeError):
                    continue
                wrapped_class_ids.add(id(obj))
                continue

            def _make_proxy(fn, owner):
                def _proxy(*args, **kwargs):
                    return _RESULT
                try:
                    _proxy.__name__ = getattr(fn, "__name__", "controlled")
                    _proxy.__doc__ = getattr(fn, "__doc__", None)
                    _proxy.__module__ = owner
                except (AttributeError, TypeError):
                    pass
                return _proxy

            try:
                setattr(mod, name, _make_proxy(obj, modname))
            except (AttributeError, TypeError):
                continue

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != module and not fullname.startswith(module + "."):
                return None
            index = sys.meta_path.index(self)
            sys.meta_path.pop(index)
            try:
                spec = importlib.util.find_spec(fullname)
            finally:
                sys.meta_path.insert(index, self)
            if spec is None or spec.loader is None:
                return None
            inner = spec.loader

            class _Loader(importlib.abc.Loader):
                def __getattr__(self, name):
                    return getattr(inner, name)

                def create_module(self, spec):
                    return inner.create_module(spec) if hasattr(inner, "create_module") else None

                def exec_module(self, loaded):
                    inner.exec_module(loaded)
                    _replace_callables(loaded, getattr(loaded, "__name__", fullname))

            spec.loader = _Loader()
            return spec

    # write_hook_dir() installs the signed-receipt finder at index zero.  Being
    # directly behind it makes the receipt wrapper the outermost call wrapper.
    sys.meta_path.insert(1 if sys.meta_path else 0, _Finder())
'''


@dataclass(frozen=True)
class _VerifierRun:
    protocol_ok: bool
    verifier_ok: bool
    reason_codes: tuple[str, ...]
    checked_commitment_ids: tuple[str, ...]
    upstream_imports: int
    upstream_calls: int
    receipts_ok: bool


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_regular_file_snapshot(path: Path, *, label: str) -> bytes:
    """Read one race-detected, no-follow file snapshot.

    Hashing a path and later executing the same *path* creates a classic
    hash-then-replace gap.  We instead read through one no-follow descriptor,
    reject mutation observed during the read, and only ever execute a private
    copy of these returned bytes.
    """

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SemanticVerifierError(
            f"{label} must be a readable regular non-symlink file"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise SemanticVerifierError(
                f"{label} must be a regular non-symlink file"
            )
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
        stable_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) == (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        payload = b"".join(chunks)
        if not stable_identity or len(payload) != after.st_size:
            raise SemanticVerifierError(f"{label} changed while being snapshotted")
        return payload
    finally:
        os.close(descriptor)


def _write_private_snapshot(path: Path, payload: bytes) -> Path:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o400)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    return path


def _negative_artifact(payload: bytes) -> bytes:
    """Return a deterministic, domain-blind artifact counterexample."""

    return (
        b"REPOPROOF-ARTIFACT-NEGATIVE-CONTROL-v1\x00"
        + hashlib.sha256(payload).digest()
    )


def _negative_input(payload: bytes) -> bytes:
    """Return a deterministic domain-blind input counterexample.

    The control is not interpreted as a valid domain sample.  It asks only a
    necessary question: can the verifier still approve the original artifact
    when the exact input bytes are replaced?  Approval proves the verifier can
    ignore the audited input and therefore cannot support an operational PASS.
    """

    return (
        b"REPOPROOF-INPUT-NEGATIVE-CONTROL-v1\x00"
        + hashlib.sha256(payload).digest()
    )


def semantic_mechanism_failure(reason_codes: list[str] | tuple[str, ...]) -> bool:
    """Classify verifier-mechanism failures from the protocol's single registry."""

    return any(reason in _MECHANISM_REASON_CODES for reason in reason_codes)


def semantic_verifier_evidence_sha256(
    evidence: SemanticVerifierEvidenceV1 | dict,
) -> str:
    parsed = (
        evidence
        if isinstance(evidence, SemanticVerifierEvidenceV1)
        else SemanticVerifierEvidenceV1.model_validate(evidence)
    )
    payload = json.dumps(
        parsed.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _execute_snapshot(
    *,
    stage_root: Path,
    verifier_source: Path,
    input_path: Path,
    artifact_path: Path,
    python_exe: str,
    upstream_paths: list[str],
    import_module: str,
    control: Literal["normal", "upstream-result-counterfactual"],
    isolation_required: bool,
    timeout_s: int,
) -> _VerifierRun:
    """Execute one immutable snapshot set with a fresh receipt identity."""

    stage_root.mkdir(mode=0o700)
    hook_dir = write_hook_dir(stage_root / "hook")
    ledger = stage_root / "upstream_receipts.jsonl"
    secret = secrets.token_hex(32)
    runner = _write_private_snapshot(
        stage_root / "runner.py",
        _RUNNER.encode("utf-8"),
    )
    _write_private_snapshot(
        stage_root / "repoproof_counterfactual_hook.py",
        _COUNTERFACTUAL_HOOK.encode("utf-8"),
    )
    env = sanitised_subprocess_env(
        stage_root,
        [str(hook_dir), str(stage_root), *upstream_paths],
    )
    env.update({
        ENV_MODULE: import_module,
        ENV_LEDGER: str(ledger),
        ENV_SECRET: secret,
    })
    argv = [
        python_exe,
        str(runner),
        str(verifier_source),
        str(input_path),
        str(artifact_path),
        control,
    ]
    if isolation_required:
        try:
            argv = offline_sandbox_argv(argv, stage_root)
        except OfflineSandboxUnavailable as exc:
            raise SemanticVerifierError(
                "semantic verifier isolation is unavailable"
            ) from exc
    try:
        process = subprocess.run(  # noqa: S603 - reviewed argv, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=stage_root,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SemanticVerifierError(
            f"semantic verifier execution failed: {type(exc).__name__}"
        ) from exc

    raw = process.stdout or ""
    protocol_ok = len(raw.encode("utf-8", errors="replace")) <= _OUTPUT_CAP
    result: dict = {}
    if protocol_ok:
        try:
            parsed = json.loads(raw.strip().splitlines()[-1])
            result = parsed if isinstance(parsed, dict) else {}
        except (ValueError, IndexError, TypeError):
            protocol_ok = False
    if result.get("fatal_type"):
        protocol_ok = False
    raw_reasons = result.get("reason_codes") if protocol_ok else []
    reasons = (
        tuple(item for item in raw_reasons if isinstance(item, str))
        if isinstance(raw_reasons, list)
        else ()
    )
    raw_checked = result.get("checked_commitment_ids") if protocol_ok else []
    checked = (
        tuple(item for item in raw_checked if isinstance(item, str))
        if isinstance(raw_checked, list)
        else ()
    )
    if (
        process.returncode != 0
        or any(_REASON_RE.fullmatch(item) is None for item in reasons)
        or len(reasons) > 32
        or len(reasons) != len(set(reasons))
        or any(item in _MECHANISM_REASON_CODES for item in reasons)
        or any(_ID_RE.fullmatch(item) is None for item in checked)
        or len(checked) > 64
        or len(checked) != len(set(checked))
    ):
        protocol_ok = False
        reasons = ()
        checked = ()

    receipts = verify_import_receipts(
        ledger,
        secret,
        module=import_module,
        min_calls=1,
    )
    return _VerifierRun(
        protocol_ok=protocol_ok,
        verifier_ok=bool(protocol_ok and result.get("ok") is True),
        reason_codes=reasons,
        checked_commitment_ids=checked,
        upstream_imports=int(receipts["imports"]),
        upstream_calls=int(receipts["calls"]),
        receipts_ok=bool(receipts["ok"]),
    )


def screen_semantic_candidate(
    *,
    verifier_source: Path,
    input_path: Path,
    artifact_path: Path,
    python_exe: str,
    upstream_dir: Path,
    import_module: str,
    required_commitment_ids: list[str] | tuple[str, ...],
    execute_installed_upstream: bool = False,
    isolation_required: bool = True,
    timeout_s: int = 120,
) -> SemanticCandidateScreenV1:
    """Run the independent verifier before a proposed golden reaches the UI.

    Only the normal verifier execution is needed at this stage.  The stronger
    input/artifact/upstream counterfactual controls remain mandatory in
    :func:`run_semantic_verifier` after freeze.  A normal rejection means the
    proposed pair is outside the admitted success domain.  Conversely, a
    claimed PASS with incomplete commitment coverage or no observed upstream
    call is a verifier-mechanism defect and stops candidate generation.
    """

    required_ids = tuple(required_commitment_ids)
    if not required_ids or any(_ID_RE.fullmatch(item) is None for item in required_ids):
        raise SemanticVerifierError("candidate screen requires valid commitment ids")
    if len(required_ids) != len(set(required_ids)):
        raise SemanticVerifierError("candidate screen commitment ids must be unique")
    if not python_exe:
        raise SemanticVerifierError("python_exe is required")
    upstream_dir = Path(upstream_dir)
    if upstream_dir.is_symlink() or not upstream_dir.is_dir():
        raise SemanticVerifierError(
            "upstream_dir must be a regular non-symlink directory"
        )

    source_bytes = _read_regular_file_snapshot(
        Path(verifier_source),
        label="verifier",
    )
    input_bytes = _read_regular_file_snapshot(Path(input_path), label="input")
    artifact_bytes = _read_regular_file_snapshot(
        Path(artifact_path),
        label="artifact",
    )
    with tempfile.TemporaryDirectory(prefix="rp-semantic-candidate-") as temp:
        root = Path(temp)
        snapshots = root / "snapshots"
        snapshots.mkdir(mode=0o700)
        source_snapshot = _write_private_snapshot(
            snapshots / "semantic_verifier.py",
            source_bytes,
        )
        input_snapshot = _write_private_snapshot(
            snapshots / "input",
            input_bytes,
        )
        artifact_snapshot = _write_private_snapshot(
            snapshots / "artifact",
            artifact_bytes,
        )
        upstream_paths = (
            []
            if execute_installed_upstream
            else (
                [str(upstream_dir / "src"), str(upstream_dir)]
                if (upstream_dir / "src").is_dir()
                else [str(upstream_dir)]
            )
        )
        actual = _execute_snapshot(
            stage_root=root / "actual",
            verifier_source=source_snapshot,
            input_path=input_snapshot,
            artifact_path=artifact_snapshot,
            python_exe=python_exe,
            upstream_paths=upstream_paths,
            import_module=import_module,
            control="normal",
            isolation_required=isolation_required,
            timeout_s=timeout_s,
        )

    reasons = list(actual.reason_codes)
    mechanism_ok = actual.protocol_ok
    if not actual.protocol_ok:
        reasons = ["VERIFIER_PROTOCOL_ERROR"]
    elif actual.verifier_ok:
        if set(actual.checked_commitment_ids) != set(required_ids):
            mechanism_ok = False
            reasons.append("COMMITMENT_COVERAGE_MISMATCH")
        if not actual.receipts_ok:
            mechanism_ok = False
            reasons.append("UPSTREAM_CALL_NOT_OBSERVED")
    elif not reasons:
        reasons.append("SEMANTIC_MISMATCH")
    reasons = list(dict.fromkeys(reasons))
    passed = bool(actual.verifier_ok and mechanism_ok and not reasons)
    return SemanticCandidateScreenV1(
        mechanism_ok=mechanism_ok,
        passed=passed,
        reason_codes=tuple(reasons),
        checked_commitment_ids=actual.checked_commitment_ids,
        upstream_imports=actual.upstream_imports,
        upstream_calls=actual.upstream_calls,
    )


def run_semantic_verifier(
    *,
    verifier_id: str,
    verifier_source: Path,
    input_path: Path,
    artifact_path: Path,
    python_exe: str,
    upstream_dir: Path,
    import_module: str,
    upstream_commit: str,
    output_contract_sha256: str,
    intent_confirmation_sha256: str,
    required_commitment_ids: list[str] | tuple[str, ...],
    execute_installed_upstream: bool = False,
    isolation_required: bool = True,
    timeout_s: int = 120,
) -> SemanticVerifierEvidenceV1:
    """Execute one task-authored verifier and return identity-bound evidence.

    A verifier PASS is necessary but insufficient: the Harness additionally
    requires signed runtime evidence of at least one call into the declared
    upstream.  Raw input, output, exceptions, and verifier stdout never enter
    the evidence record.
    """

    required_ids = tuple(required_commitment_ids)
    identity = SemanticVerifierEvidenceV1(
        verifier_id=verifier_id,
        verifier_source_sha256="0" * 64,
        input_sha256="0" * 64,
        artifact_sha256="0" * 64,
        output_contract_sha256=output_contract_sha256,
        intent_confirmation_sha256=intent_confirmation_sha256,
        upstream_commit=upstream_commit,
        import_module=import_module,
        upstream_imports=0,
        upstream_calls=0,
        required_commitment_ids=required_ids,
        checked_commitment_ids=(),
        passed=False,
        reason_codes=(),
    )
    del identity  # validation-only: reject malformed public identities before execution

    verifier_source = Path(verifier_source)
    input_path = Path(input_path)
    artifact_path = Path(artifact_path)
    upstream_dir = Path(upstream_dir)
    if upstream_dir.is_symlink() or not upstream_dir.is_dir():
        raise SemanticVerifierError("upstream_dir must be a regular non-symlink directory")
    if not python_exe:
        raise SemanticVerifierError("python_exe is required")

    # Read each untrusted path exactly once.  Every subsequent hash and child
    # execution consumes these bytes, never the caller-controlled live path.
    source_bytes = _read_regular_file_snapshot(verifier_source, label="verifier")
    input_bytes = _read_regular_file_snapshot(input_path, label="input")
    artifact_bytes = _read_regular_file_snapshot(artifact_path, label="artifact")
    negative_bytes = _negative_artifact(artifact_bytes)
    negative_input_bytes = _negative_input(input_bytes)
    source_sha = _sha256_bytes(source_bytes)
    input_sha = _sha256_bytes(input_bytes)
    artifact_sha = _sha256_bytes(artifact_bytes)
    negative_sha = _sha256_bytes(negative_bytes)
    negative_input_sha = _sha256_bytes(negative_input_bytes)

    input_control_result: Literal[
        "NOT_RUN", "REJECTED", "ACCEPTED", "UNTRUSTED"
    ] = "NOT_RUN"
    input_control_imports = 0
    input_control_calls = 0

    artifact_control_result: Literal[
        "NOT_RUN", "REJECTED", "ACCEPTED", "UNTRUSTED"
    ] = "NOT_RUN"
    artifact_control_imports = 0
    artifact_control_calls = 0
    upstream_control_result: Literal[
        "NOT_RUN", "REJECTED", "ACCEPTED", "UNTRUSTED"
    ] = "NOT_RUN"
    upstream_control_imports = 0
    upstream_control_calls = 0

    with tempfile.TemporaryDirectory(prefix="rp-semantic-verifier-") as temp:
        root = Path(temp)
        snapshots = root / "snapshots"
        snapshots.mkdir(mode=0o700)
        source_snapshot = _write_private_snapshot(
            snapshots / "semantic_verifier.py",
            source_bytes,
        )
        input_snapshot = _write_private_snapshot(
            snapshots / "input",
            input_bytes,
        )
        artifact_snapshot = _write_private_snapshot(
            snapshots / "artifact",
            artifact_bytes,
        )
        negative_snapshot = _write_private_snapshot(
            snapshots / "artifact-negative-control",
            negative_bytes,
        )
        negative_input_snapshot = _write_private_snapshot(
            snapshots / "input-negative-control",
            negative_input_bytes,
        )
        upstream_paths = (
            []
            if execute_installed_upstream
            else (
                [str(upstream_dir / "src"), str(upstream_dir)]
                if (upstream_dir / "src").is_dir()
                else [str(upstream_dir)]
            )
        )
        actual = _execute_snapshot(
            stage_root=root / "actual",
            verifier_source=source_snapshot,
            input_path=input_snapshot,
            artifact_path=artifact_snapshot,
            python_exe=python_exe,
            upstream_paths=upstream_paths,
            import_module=import_module,
            control="normal",
            isolation_required=isolation_required,
            timeout_s=timeout_s,
        )
        reasons = list(actual.reason_codes)
        if not actual.protocol_ok:
            reasons = ["VERIFIER_PROTOCOL_ERROR"]
        elif not actual.verifier_ok and not reasons:
            reasons = ["SEMANTIC_MISMATCH"]
        if (
            actual.protocol_ok
            and set(actual.checked_commitment_ids) != set(required_ids)
            and "COMMITMENT_COVERAGE_MISMATCH" not in reasons
        ):
            reasons.append("COMMITMENT_COVERAGE_MISMATCH")
        if (
            not actual.receipts_ok
            and "UPSTREAM_CALL_NOT_OBSERVED" not in reasons
        ):
            reasons.append("UPSTREAM_CALL_NOT_OBSERVED")
        actual_pass = bool(
            actual.protocol_ok
            and actual.verifier_ok
            and set(actual.checked_commitment_ids) == set(required_ids)
            and actual.receipts_ok
            and not reasons
        )

        if actual_pass:
            input_control = _execute_snapshot(
                stage_root=root / "input-control",
                verifier_source=source_snapshot,
                input_path=negative_input_snapshot,
                artifact_path=artifact_snapshot,
                python_exe=python_exe,
                upstream_paths=upstream_paths,
                import_module=import_module,
                control="normal",
                isolation_required=isolation_required,
                timeout_s=timeout_s,
            )
            input_control_imports = input_control.upstream_imports
            input_control_calls = input_control.upstream_calls
            if input_control.verifier_ok:
                input_control_result = "ACCEPTED"
                reasons.append("INPUT_BINDING_CONTROL_FAILED")
            else:
                # A domain parser may reject the counterexample before it can
                # call upstream or emit the normal verifier protocol.  That is
                # still the intended counterfactual outcome: unlike the actual
                # input, these bytes cannot lead to approval of this artifact.
                input_control_result = "REJECTED"

            artifact_control = _execute_snapshot(
                stage_root=root / "artifact-control",
                verifier_source=source_snapshot,
                input_path=input_snapshot,
                artifact_path=negative_snapshot,
                python_exe=python_exe,
                upstream_paths=upstream_paths,
                import_module=import_module,
                control="normal",
                isolation_required=isolation_required,
                timeout_s=timeout_s,
            )
            artifact_control_imports = artifact_control.upstream_imports
            artifact_control_calls = artifact_control.upstream_calls
            if artifact_control.verifier_ok:
                artifact_control_result = "ACCEPTED"
                reasons.append("ARTIFACT_BINDING_CONTROL_FAILED")
            else:
                # The exact same verifier already completed the actual run
                # with a signed upstream call.  Here the Harness changes only
                # the artifact bytes.  Rejection may therefore happen before
                # the verifier calls upstream or emits its normal result
                # protocol (for example, while decoding/parsing the artifact).
                # That is valid artifact sensitivity, not an environment
                # failure.  Requiring receipts here made equivalent verifiers
                # pass or fail solely because they inspected input and
                # artifact in a different order.  A verifier that ignores the
                # artifact still returns ok=True and is rejected above.
                artifact_control_result = "REJECTED"

            upstream_control = _execute_snapshot(
                stage_root=root / "upstream-result-control",
                verifier_source=source_snapshot,
                input_path=input_snapshot,
                artifact_path=artifact_snapshot,
                python_exe=python_exe,
                upstream_paths=upstream_paths,
                import_module=import_module,
                control="upstream-result-counterfactual",
                isolation_required=isolation_required,
                timeout_s=timeout_s,
            )
            upstream_control_imports = upstream_control.upstream_imports
            upstream_control_calls = upstream_control.upstream_calls
            if not upstream_control.receipts_ok:
                upstream_control_result = "UNTRUSTED"
                reasons.append("VERIFIER_PROTOCOL_ERROR")
            elif upstream_control.verifier_ok:
                upstream_control_result = "ACCEPTED"
                reasons.append("VERIFIER_PROTOCOL_ERROR")
            else:
                upstream_control_result = "REJECTED"

        reasons = list(dict.fromkeys(reasons))
        passed = bool(
            actual_pass
            and input_control_result == "REJECTED"
            and artifact_control_result == "REJECTED"
            and upstream_control_result == "REJECTED"
            and not reasons
        )

    return SemanticVerifierEvidenceV1(
        verifier_id=verifier_id,
        verifier_source_sha256=source_sha,
        input_sha256=input_sha,
        artifact_sha256=artifact_sha,
        output_contract_sha256=output_contract_sha256,
        intent_confirmation_sha256=intent_confirmation_sha256,
        upstream_commit=upstream_commit,
        import_module=import_module,
        upstream_imports=actual.upstream_imports,
        upstream_calls=actual.upstream_calls,
        input_negative_control_sha256=negative_input_sha,
        input_negative_control_result=input_control_result,
        input_negative_control_upstream_imports=input_control_imports,
        input_negative_control_upstream_calls=input_control_calls,
        artifact_negative_control_sha256=negative_sha,
        artifact_negative_control_result=artifact_control_result,
        artifact_negative_control_upstream_imports=artifact_control_imports,
        artifact_negative_control_upstream_calls=artifact_control_calls,
        upstream_result_counterfactual_result=upstream_control_result,
        upstream_result_counterfactual_upstream_imports=upstream_control_imports,
        upstream_result_counterfactual_upstream_calls=upstream_control_calls,
        required_commitment_ids=required_ids,
        checked_commitment_ids=actual.checked_commitment_ids,
        passed=passed,
        reason_codes=tuple(reasons),
    )


def write_semantic_verifier_evidence(
    path: Path,
    evidence: SemanticVerifierEvidenceV1,
) -> Path:
    """Create one append-only evidence file; overwrite and symlink targets fail."""

    path = Path(path)
    parent = path.parent
    if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
        raise SemanticVerifierError("unsafe semantic evidence directory")
    parent.mkdir(parents=True, exist_ok=True)
    if parent.is_symlink():
        raise SemanticVerifierError("unsafe semantic evidence directory")
    payload = (
        json.dumps(
            evidence.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise SemanticVerifierError("semantic verifier evidence is append-only") from exc
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    directory_descriptor = os.open(
        parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return path
