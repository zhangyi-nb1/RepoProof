"""Repository-agnostic semantic evidence for offline workspace bundles.

Task packages own ``verify(input_path, artifact_dir)`` and all domain rules.
Core owns immutable snapshots, pinned-upstream call receipts, commitment
coverage, and three generic sensitivity controls.  This module contains no
qualification-repository vocabulary.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from repoproof.domain.models import WorkspaceArtifactLimits
from repoproof.execution.workspace_bundle import (
    InputPathIdentityV1,
    build_artifact_manifest,
    snapshot_admitted_path,
)
from repoproof.verification.semantic_artifact import (
    SemanticVerifierError,
    _execute_snapshot,
    _read_regular_file_snapshot,
    _write_private_snapshot,
)

WORKSPACE_SEMANTIC_PROTOCOL = "repoproof-workspace-semantic-verifier-v2"
_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,255}")
_MODULE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_REASON_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_SHA256_RE = r"^[0-9a-f]{64}$"
_COMMIT_RE = r"^[0-9a-f]{40}$"
_MECHANISM_REASON_CODES = frozenset(
    {
        "ARTIFACT_BINDING_CONTROL_FAILED",
        "COMMITMENT_COVERAGE_MISMATCH",
        "INPUT_BINDING_CONTROL_FAILED",
        "UPSTREAM_RESULT_BINDING_CONTROL_FAILED",
        "UPSTREAM_CALL_NOT_OBSERVED",
        "VERIFIER_PROTOCOL_ERROR",
    }
)
_ControlResult = Literal["NOT_RUN", "REJECTED", "ACCEPTED", "UNTRUSTED"]


class SemanticVerifierEvidenceV2(BaseModel):
    """Identity-bound directory evidence for one frozen task verifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[4] = 4
    protocol: Literal["repoproof-workspace-semantic-verifier-v2"] = (
        "repoproof-workspace-semantic-verifier-v2"
    )
    verifier_id: str
    verifier_source_sha256: str = Field(pattern=_SHA256_RE)
    input_kind: Literal["file", "directory"]
    input_sha256: str = Field(pattern=_SHA256_RE)
    artifact_tree_sha256: str = Field(pattern=_SHA256_RE)
    artifact_manifest_sha256: str = Field(pattern=_SHA256_RE)
    workspace_contract_sha256: str = Field(pattern=_SHA256_RE)
    intent_confirmation_sha256: str = Field(pattern=_SHA256_RE)
    upstream_commit: str = Field(pattern=_COMMIT_RE)
    import_module: str
    upstream_imports: int = Field(ge=0)
    upstream_calls: int = Field(ge=0)
    input_negative_control_sha256: str | None = Field(default=None, pattern=_SHA256_RE)
    input_negative_control_result: _ControlResult = "NOT_RUN"
    input_negative_control_upstream_imports: int = Field(default=0, ge=0)
    input_negative_control_upstream_calls: int = Field(default=0, ge=0)
    artifact_negative_control_tree_sha256: str | None = Field(
        default=None, pattern=_SHA256_RE
    )
    artifact_negative_control_result: _ControlResult = "NOT_RUN"
    artifact_negative_control_upstream_imports: int = Field(default=0, ge=0)
    artifact_negative_control_upstream_calls: int = Field(default=0, ge=0)
    upstream_result_counterfactual_result: _ControlResult = "NOT_RUN"
    upstream_result_counterfactual_upstream_imports: int = Field(default=0, ge=0)
    upstream_result_counterfactual_upstream_calls: int = Field(default=0, ge=0)
    required_commitment_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    checked_commitment_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    passed: bool
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    # Verifier-authored public explanations keyed by reported reason code.
    reason_details: dict[str, str] = Field(default_factory=dict)

    @field_validator("verifier_id")
    @classmethod
    def _safe_verifier_id(cls, value: str) -> str:
        if _ID_RE.fullmatch(value.strip()) is None:
            raise ValueError("verifier_id must be a safe lowercase identifier")
        return value.strip()

    @field_validator("import_module")
    @classmethod
    def _safe_import_module(cls, value: str) -> str:
        if _MODULE_RE.fullmatch(value.strip()) is None:
            raise ValueError("import_module must be a dotted Python identifier")
        return value.strip()

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
    def _safe_commitments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_ID_RE.fullmatch(item) is None for item in value):
            raise ValueError("commitment ids must be safe stable identifiers")
        if len(value) != len(set(value)):
            raise ValueError("commitment ids must be unique")
        return value

    @model_validator(mode="after")
    def _pass_requires_all_controls(self) -> SemanticVerifierEvidenceV2:
        if self.passed and (
            self.input_negative_control_result != "REJECTED"
            or self.input_negative_control_sha256 is None
            or self.artifact_negative_control_result != "REJECTED"
            or self.artifact_negative_control_tree_sha256 is None
            or self.upstream_result_counterfactual_result != "REJECTED"
            or self.upstream_result_counterfactual_upstream_calls < 1
            or self.upstream_calls < 1
        ):
            raise ValueError("workspace semantic PASS requires all binding controls")
        return self


def _canonical_sha256(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def workspace_semantic_evidence_sha256(
    evidence: SemanticVerifierEvidenceV2 | dict,
) -> str:
    parsed = (
        evidence
        if isinstance(evidence, SemanticVerifierEvidenceV2)
        else SemanticVerifierEvidenceV2.model_validate(evidence)
    )
    return _canonical_sha256(parsed)


def _make_negative_path(
    root: Path,
    *,
    name: str,
    identity: InputPathIdentityV1,
) -> tuple[Path, InputPathIdentityV1]:
    target = root / name
    marker = (
        b"REPOPROOF-WORKSPACE-NEGATIVE-CONTROL-v1\x00"
        + bytes.fromhex(identity.sha256)
    )
    if identity.kind == "directory":
        target.mkdir()
        (target / "controlled.bin").write_bytes(marker)
    else:
        target.write_bytes(marker)
    return target, snapshot_admitted_path(target, root / f"{name}-snapshot")


def run_workspace_semantic_verifier(
    *,
    verifier_id: str,
    verifier_source: Path,
    input_path: Path,
    artifact_dir: Path,
    python_exe: str,
    upstream_dir: Path,
    import_module: str,
    upstream_commit: str,
    workspace_contract_sha256: str,
    intent_confirmation_sha256: str,
    required_commitment_ids: list[str] | tuple[str, ...],
    execute_installed_upstream: bool = False,
    isolation_required: bool = True,
    timeout_s: int = 120,
) -> SemanticVerifierEvidenceV2:
    """Run a frozen directory verifier and all generic counterfactuals."""

    required_ids = tuple(required_commitment_ids)
    # Validate all public identities before touching untrusted paths.
    SemanticVerifierEvidenceV2(
        verifier_id=verifier_id,
        verifier_source_sha256="0" * 64,
        input_kind="file",
        input_sha256="0" * 64,
        artifact_tree_sha256="0" * 64,
        artifact_manifest_sha256="0" * 64,
        workspace_contract_sha256=workspace_contract_sha256,
        intent_confirmation_sha256=intent_confirmation_sha256,
        upstream_commit=upstream_commit,
        import_module=import_module,
        upstream_imports=0,
        upstream_calls=0,
        required_commitment_ids=required_ids,
        passed=False,
    )
    upstream_dir = Path(upstream_dir)
    if upstream_dir.is_symlink() or not upstream_dir.is_dir():
        raise SemanticVerifierError("upstream_dir must be a regular non-symlink directory")
    if not python_exe:
        raise SemanticVerifierError("python_exe is required")
    source_bytes = _read_regular_file_snapshot(Path(verifier_source), label="verifier")
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    limits = WorkspaceArtifactLimits()

    input_result: _ControlResult = "NOT_RUN"
    artifact_result: _ControlResult = "NOT_RUN"
    upstream_result: _ControlResult = "NOT_RUN"
    input_imports = input_calls = 0
    artifact_imports = artifact_calls = 0
    upstream_imports = upstream_calls = 0

    with tempfile.TemporaryDirectory(prefix="rp-workspace-semantic-") as temp:
        root = Path(temp)
        snapshots = root / "snapshots"
        snapshots.mkdir(mode=0o700)
        source_snapshot = _write_private_snapshot(
            snapshots / "semantic_verifier.py", source_bytes
        )
        input_snapshot = snapshots / "input"
        input_identity = snapshot_admitted_path(Path(input_path), input_snapshot)
        artifact_snapshot = snapshots / "artifact"
        artifact_identity = snapshot_admitted_path(
            Path(artifact_dir), artifact_snapshot, limits=limits
        )
        if artifact_identity.kind != "directory":
            raise SemanticVerifierError("workspace artifact must be a directory")
        artifact_manifest = build_artifact_manifest(artifact_snapshot, limits)
        artifact_manifest_sha = _canonical_sha256(artifact_manifest)

        negative_input, negative_input_identity = _make_negative_path(
            snapshots,
            name="input-negative-source",
            identity=input_identity,
        )
        # _make_negative_path returns a second immutable snapshot; remove the
        # source control so child executions can only see the bound snapshot.
        if negative_input.is_dir():
            for child in negative_input.iterdir():
                child.unlink()
            negative_input.rmdir()
        else:
            negative_input.unlink()
        negative_input_snapshot = snapshots / "input-negative-source-snapshot"

        artifact_control_source = snapshots / "artifact-negative-source"
        artifact_control_source.mkdir()
        (artifact_control_source / "controlled.bin").write_bytes(
            b"REPOPROOF-ARTIFACT-DIRECTORY-NEGATIVE-CONTROL-v1\x00"
            + bytes.fromhex(artifact_manifest.tree_sha256)
        )
        negative_artifact_snapshot = snapshots / "artifact-negative"
        negative_artifact_identity = snapshot_admitted_path(
            artifact_control_source, negative_artifact_snapshot
        )
        (artifact_control_source / "controlled.bin").unlink()
        artifact_control_source.rmdir()

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
        verdict_details: dict[str, str] = {}
        if not actual.protocol_ok:
            reasons = ["VERIFIER_PROTOCOL_ERROR"]
        elif not actual.verifier_ok and not reasons:
            reasons = ["SEMANTIC_MISMATCH"]
        elif actual.verifier_ok and reasons:
            # A passing verdict that still carries reason codes (models like to
            # emit an informational "OK") is a protocol inconsistency.  The screen
            # has always refused it (a pass must carry no failure codes); naming
            # the rule here is what makes the refusal repairable instead of a
            # disagreement whose only diagnostic reads "OK".
            listed = ", ".join(reasons[:8])
            reasons = ["VERIFIER_INFORMATIONAL_REASON_CODES_ON_PASS"]
            verdict_details["VERIFIER_INFORMATIONAL_REASON_CODES_ON_PASS"] = (
                f"verify() returned ok=true together with reason_codes [{listed}]; a passing "
                "verdict must return an empty reason_codes list (no informational codes)"
            )[:200]
        if (
            actual.protocol_ok
            and set(actual.checked_commitment_ids) != set(required_ids)
        ):
            reasons.append("COMMITMENT_COVERAGE_MISMATCH")
            missing = sorted(set(required_ids) - set(actual.checked_commitment_ids))
            extra = sorted(set(actual.checked_commitment_ids) - set(required_ids))
            verdict_details["COMMITMENT_COVERAGE_MISMATCH"] = (
                "checked_commitment_ids must equal the supplied commitment ids; "
                f"missing={missing[:8]} extra={extra[:8]}"
            )[:200]
        if not actual.receipts_ok:
            reasons.append("UPSTREAM_CALL_NOT_OBSERVED")
            verdict_details["UPSTREAM_CALL_NOT_OBSERVED"] = (
                "the verifier finished without a recorded call into the pinned upstream module; "
                "the verdict must depend on values the upstream returns"
            )
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
            input_imports = input_control.upstream_imports
            input_calls = input_control.upstream_calls
            input_result = "ACCEPTED" if input_control.verifier_ok else "REJECTED"
            if input_result == "ACCEPTED":
                reasons.append("INPUT_BINDING_CONTROL_FAILED")
                verdict_details["INPUT_BINDING_CONTROL_FAILED"] = (
                    "the verifier still accepted the same artifact when given a different input; "
                    "expectations must be recomputed from the input so a wrong input is rejected"
                )

            artifact_control = _execute_snapshot(
                stage_root=root / "artifact-control",
                verifier_source=source_snapshot,
                input_path=input_snapshot,
                artifact_path=negative_artifact_snapshot,
                python_exe=python_exe,
                upstream_paths=upstream_paths,
                import_module=import_module,
                control="normal",
                isolation_required=isolation_required,
                timeout_s=timeout_s,
            )
            artifact_imports = artifact_control.upstream_imports
            artifact_calls = artifact_control.upstream_calls
            artifact_result = "ACCEPTED" if artifact_control.verifier_ok else "REJECTED"
            if artifact_result == "ACCEPTED":
                reasons.append("ARTIFACT_BINDING_CONTROL_FAILED")
                verdict_details["ARTIFACT_BINDING_CONTROL_FAILED"] = (
                    "the verifier accepted a corrupted artifact for the same input; "
                    "it must read the delivered files and compare them to recomputed expectations"
                )

            upstream_control = _execute_snapshot(
                stage_root=root / "upstream-control",
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
            upstream_imports = upstream_control.upstream_imports
            upstream_calls = upstream_control.upstream_calls
            if not upstream_control.receipts_ok:
                upstream_result = "UNTRUSTED"
                reasons.append("VERIFIER_PROTOCOL_ERROR")
            elif upstream_control.verifier_ok:
                upstream_result = "ACCEPTED"
                reasons.append("UPSTREAM_RESULT_BINDING_CONTROL_FAILED")
                verdict_details["UPSTREAM_RESULT_BINDING_CONTROL_FAILED"] = (
                    "the verifier still accepted the artifact when the pinned upstream returned "
                    "counterfactual values; the verdict must depend on what the upstream returns"
                )
            else:
                upstream_result = "REJECTED"

        reasons = list(dict.fromkeys(reasons))
        if any(item in _MECHANISM_REASON_CODES for item in actual.reason_codes):
            reasons = ["VERIFIER_PROTOCOL_ERROR"]
        passed = bool(
            actual_pass
            and input_result == "REJECTED"
            and artifact_result == "REJECTED"
            and upstream_result == "REJECTED"
            and not reasons
        )

    return SemanticVerifierEvidenceV2(
        verifier_id=verifier_id,
        verifier_source_sha256=source_sha,
        input_kind=input_identity.kind,
        input_sha256=input_identity.sha256,
        artifact_tree_sha256=artifact_manifest.tree_sha256,
        artifact_manifest_sha256=artifact_manifest_sha,
        workspace_contract_sha256=workspace_contract_sha256,
        intent_confirmation_sha256=intent_confirmation_sha256,
        upstream_commit=upstream_commit,
        import_module=import_module,
        upstream_imports=actual.upstream_imports,
        upstream_calls=actual.upstream_calls,
        input_negative_control_sha256=negative_input_identity.sha256,
        input_negative_control_result=input_result,
        input_negative_control_upstream_imports=input_imports,
        input_negative_control_upstream_calls=input_calls,
        artifact_negative_control_tree_sha256=negative_artifact_identity.sha256,
        artifact_negative_control_result=artifact_result,
        artifact_negative_control_upstream_imports=artifact_imports,
        artifact_negative_control_upstream_calls=artifact_calls,
        upstream_result_counterfactual_result=upstream_result,
        upstream_result_counterfactual_upstream_imports=upstream_imports,
        upstream_result_counterfactual_upstream_calls=upstream_calls,
        required_commitment_ids=required_ids,
        checked_commitment_ids=actual.checked_commitment_ids,
        passed=passed,
        reason_codes=tuple(reasons),
        reason_details={
            **{
                code: text
                for code, text in dict(getattr(actual, "reason_details", {}) or {}).items()
                if code in reasons
            },
            **verdict_details,
        },
    )


def write_workspace_semantic_evidence(
    path: Path,
    evidence: SemanticVerifierEvidenceV2,
) -> Path:
    """Persist one append-only directory-semantic evidence record."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.exists() or path.is_symlink():
        raise SemanticVerifierError("workspace semantic evidence is append-only")
    payload = (
        json.dumps(
            evidence.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    return path


# --------------------------------------------------------------------------
# Verifier discrimination probe
#
# A verifier can pass the positive control and all three counterfactuals while
# never recomputing the *content* of a delivered file (existence or heading
# checks only).  Such a verifier would accept a producer that writes the right
# skeleton with wrong data.  The probe applies deterministic content mutations
# to every delivered file the task owns and requires the verifier to reject at
# least one mutation per file.  Deleting a file is deliberately not a mutation:
# structure validation already guards presence, and presence is not semantics.
# --------------------------------------------------------------------------

MutationResult = Literal["REJECTED", "ACCEPTED", "PROTOCOL_ERROR"]


class WorkspaceVerifierMutationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1, max_length=40)
    result: MutationResult


class WorkspaceVerifierFileProbeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1, max_length=512)
    mutations: tuple[WorkspaceVerifierMutationV1, ...] = ()
    discriminated: bool


class WorkspaceVerifierDiscriminationV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    probed_files: int = Field(ge=0)
    files: tuple[WorkspaceVerifierFileProbeV1, ...] = ()
    gaps: tuple[str, ...] = ()
    ok: bool


def _alter_character(char: str) -> str:
    if char.isdigit():
        return str((int(char) + 1) % 10)
    return "y" if char == "x" else "x"


def _text_content_mutations(payload: bytes, *, limit: int) -> list[tuple[str, bytes]]:
    """Edit one character on each of up to ``limit`` sampled lines, then truncate.

    Commitments usually cover only some lines of a delivered file (a heading,
    a command, a table row).  Sampling first, last and evenly spaced lines asks
    the honest question — does the verifier recompute *any* content of this
    file — instead of demanding that every prose line be checked.
    """

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return []
    lines = text.splitlines(keepends=True)
    nonempty = [index for index, line in enumerate(lines) if line.strip()]
    if not nonempty:
        return []

    def _edit(index: int) -> bytes | None:
        line = lines[index]
        body = line.rstrip("\r\n")
        if not body:
            return None
        position = len(body) // 2
        edited = body[:position] + _alter_character(body[position]) + body[position + 1:]
        return "".join(lines[:index] + [edited + line[len(body):]] + lines[index + 1:]).encode("utf-8")

    budget = max(1, int(limit))
    edit_budget = max(1, budget - 1)
    if len(nonempty) <= edit_budget:
        sampled = list(nonempty)
    else:
        step = (len(nonempty) - 1) / (edit_budget - 1) if edit_budget > 1 else 0
        sampled = sorted({nonempty[round(k * step)] for k in range(edit_budget)})
    mutations: list[tuple[str, bytes]] = []
    for index in sampled:
        edited = _edit(index)
        if edited is not None:
            mutations.append((f"edit-line-{index + 1}", edited))
    truncated = "".join(lines[: nonempty[-1]]).encode("utf-8")
    if truncated != payload:
        mutations.append(("truncate-last-line", truncated))
    return mutations


def _binary_content_mutations(payload: bytes) -> list[tuple[str, bytes]]:
    if not payload:
        return []
    middle = len(payload) // 2
    flipped = payload[:middle] + bytes([payload[middle] ^ 0x5A]) + payload[middle + 1:]
    mutations = [("flip-middle-byte", flipped)]
    if len(payload) > 16:
        mutations.append(("truncate-tail", payload[:-16]))
    return mutations


def content_mutations(payload: bytes, *, limit: int) -> list[tuple[str, bytes]]:
    """Deterministic content mutations for one delivered file."""

    mutations = _text_content_mutations(payload, limit=limit) or _binary_content_mutations(payload)
    return mutations[: max(1, int(limit))]


def probe_workspace_verifier_discrimination(
    *,
    verifier_source: Path,
    input_path: Path,
    artifact_dir: Path,
    python_exe: str,
    upstream_dir: Path,
    import_module: str,
    excluded_patterns: tuple[str, ...] | list[str] = (),
    focus_paths: tuple[str, ...] | list[str] | None = None,
    execute_installed_upstream: bool = False,
    isolation_required: bool = True,
    timeout_s: int = 120,
    max_files: int = 8,
    max_mutations_per_file: int = 8,
) -> WorkspaceVerifierDiscriminationV1:
    """Require the verifier to reject a content mutation of every probed file.

    ``focus_paths`` narrows the probe to the delivered files the public artifact
    protocol actually refers to; files no observation mentions are not
    semantically claimed and are therefore not gaps.
    """

    import shutil
    from fnmatch import fnmatch

    from repoproof.verification.semantic_artifact import (
        _execute_snapshot,
        _write_private_snapshot,
    )

    upstream_dir = Path(upstream_dir)
    if upstream_dir.is_symlink() or not upstream_dir.is_dir():
        raise SemanticVerifierError("upstream_dir must be a regular non-symlink directory")
    if not python_exe:
        raise SemanticVerifierError("python_exe is required")
    source_bytes = _read_regular_file_snapshot(Path(verifier_source), label="verifier")
    limits = WorkspaceArtifactLimits()
    artifact_dir = Path(artifact_dir)
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise SemanticVerifierError("workspace artifact must be a directory")

    owned: list[tuple[str, Path]] = []
    for path in sorted(artifact_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(artifact_dir).as_posix()
        if any(fnmatch(relative, pattern) for pattern in excluded_patterns):
            continue
        if focus_paths is not None and relative not in set(focus_paths):
            continue
        if path.stat().st_size == 0:
            continue
        owned.append((relative, path))
        if len(owned) >= max(1, int(max_files)):
            break

    upstream_paths = (
        []
        if execute_installed_upstream
        else (
            [str(upstream_dir / "src"), str(upstream_dir)]
            if (upstream_dir / "src").is_dir()
            else [str(upstream_dir)]
        )
    )
    files: list[WorkspaceVerifierFileProbeV1] = []
    with tempfile.TemporaryDirectory(prefix="rp-workspace-probe-") as temp:
        root = Path(temp)
        snapshots = root / "snapshots"
        snapshots.mkdir(mode=0o700)
        source_snapshot = _write_private_snapshot(
            snapshots / "semantic_verifier.py", source_bytes
        )
        input_snapshot = snapshots / "input"
        snapshot_admitted_path(Path(input_path), input_snapshot)
        for index, (relative, path) in enumerate(owned):
            payload = path.read_bytes()
            results: list[WorkspaceVerifierMutationV1] = []
            for mutation_index, (kind, mutated_payload) in enumerate(
                content_mutations(payload, limit=max_mutations_per_file)
            ):
                stage = root / f"mutation-{index}-{mutation_index}"
                source_copy = stage / "source"
                shutil.copytree(artifact_dir, source_copy, symlinks=False)
                (source_copy / relative).write_bytes(mutated_payload)
                artifact_snapshot = stage / "artifact"
                snapshot_admitted_path(source_copy, artifact_snapshot, limits=limits)
                run = _execute_snapshot(
                    stage_root=stage / "run",
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
                if not run.protocol_ok:
                    outcome: MutationResult = "PROTOCOL_ERROR"
                elif run.verifier_ok:
                    outcome = "ACCEPTED"
                else:
                    outcome = "REJECTED"
                results.append(WorkspaceVerifierMutationV1(kind=kind, result=outcome))
            files.append(
                WorkspaceVerifierFileProbeV1(
                    path=relative,
                    mutations=tuple(results),
                    discriminated=any(item.result == "REJECTED" for item in results),
                )
            )
    gaps = tuple(item.path for item in files if not item.discriminated)
    return WorkspaceVerifierDiscriminationV1(
        probed_files=len(files),
        files=tuple(files),
        gaps=gaps,
        ok=not gaps,
    )
