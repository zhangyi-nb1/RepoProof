"""Immutable Product qualification records.

Each batch attempt writes one final JSON file.  A framework repair invalidates
the attempt and the next attempt receives a new execution id; no earlier file
is updated or deleted.  These records describe Product evidence only and can
never opt into Benchmark Lab scoring.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from repoproof.verification.semantic_artifact import (
    SemanticVerifierEvidenceV1,
    semantic_verifier_evidence_sha256,
)
from repoproof.verification.workspace_semantic import (
    SemanticVerifierEvidenceV2,
    workspace_semantic_evidence_sha256,
)

_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")


class QualificationRecordError(RuntimeError):
    """A record is invalid or would violate append-only storage."""


def qualification_framework_tree_sha256(package_root: Path) -> str:
    """Fingerprint the executable RepoProof Python package deterministically.

    The frozen protocol has its own byte hash, while this identity binds the
    Product implementation actually executed.  The algorithm matches Studio's
    stale-process guard: sorted ``*.py`` paths relative to ``src/repoproof``,
    each framed by path/content length before hashing.  Symlinks are excluded
    from the executable identity and an empty/unsafe root fails closed.
    """

    raw_root = Path(package_root)
    if raw_root.is_symlink():
        raise QualificationRecordError(
            f"unsafe qualification framework root: {raw_root}"
        )
    package_root = raw_root.resolve()
    if not package_root.is_dir():
        raise QualificationRecordError(
            f"unsafe qualification framework root: {package_root}"
        )
    digest = hashlib.sha256()
    count = 0
    for path in sorted(package_root.rglob("*.py")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(package_root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        count += 1
    if count == 0:
        raise QualificationRecordError("qualification framework tree is empty")
    return digest.hexdigest()


class QualificationCaseResultV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_name: str = Field(min_length=1, max_length=128)
    journey_id: str | None = Field(default=None, max_length=128)
    task_id: str | None = Field(default=None, max_length=256)
    run_id: str | None = Field(default=None, max_length=256)
    status: Literal["PASSED", "FAILED", "NOT_REACHED"]
    historical_verdict: Literal["VERIFIED_TOOL_READY"] | None = None
    clean_replay: Literal["PASS"] | None = None
    fresh_audit: Literal["PASS"] | None = None
    operational_status: Literal["ACTIVE"] | None = None
    package_health: Literal["OK"] | None = None
    output_validation_profile: str | None = Field(default=None, max_length=128)
    semantic_verifier_id: str | None = Field(default=None, max_length=256)
    semantic_verifier_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    semantic_verifier_evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    semantic_verifier_passed: bool | None = None
    semantic_verifier_evidence: SemanticVerifierEvidenceV1 | None = None
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=32)

    @model_validator(mode="after")
    def _passed_requires_independent_evidence(self) -> QualificationCaseResultV1:
        if self.status != "PASSED":
            return self
        required = {
            "journey_id": self.journey_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "historical_verdict": self.historical_verdict,
            "clean_replay": self.clean_replay,
            "fresh_audit": self.fresh_audit,
            "operational_status": self.operational_status,
            "package_health": self.package_health,
            "output_validation_profile": self.output_validation_profile,
            "semantic_verifier_id": self.semantic_verifier_id,
            "semantic_verifier_sha256": self.semantic_verifier_sha256,
            "semantic_verifier_evidence_sha256": (
                self.semantic_verifier_evidence_sha256
            ),
            "semantic_verifier_evidence": self.semantic_verifier_evidence,
            "artifact_sha256": self.artifact_sha256,
        }
        missing = sorted(name for name, value in required.items() if not value)
        if missing:
            raise ValueError(
                "PASSED qualification case is missing evidence: "
                + ", ".join(missing)
            )
        if self.semantic_verifier_passed is not True:
            raise ValueError("PASSED qualification case requires semantic verifier PASS")
        evidence = self.semantic_verifier_evidence
        assert evidence is not None  # included in the required mapping above
        mismatches: list[str] = []
        if evidence.verifier_id != self.semantic_verifier_id:
            mismatches.append("semantic_verifier_id")
        if evidence.verifier_source_sha256 != self.semantic_verifier_sha256:
            mismatches.append("semantic_verifier_sha256")
        if evidence.artifact_sha256 != self.artifact_sha256:
            mismatches.append("artifact_sha256")
        if evidence.passed is not True:
            mismatches.append("semantic_verifier_evidence.passed")
        if (
            semantic_verifier_evidence_sha256(evidence)
            != self.semantic_verifier_evidence_sha256
        ):
            mismatches.append("semantic_verifier_evidence_sha256")
        if mismatches:
            raise ValueError(
                "PASSED qualification case has mismatched evidence: "
                + ", ".join(mismatches)
            )
        return self


class QualificationExecutionRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    execution_id: str = Field(min_length=1, max_length=128)
    protocol_id: str = Field(min_length=1, max_length=256)
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    framework_git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    framework_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend: Literal["mini-swe", "codex-cli"]
    started_at: str
    completed_at: str
    status: Literal["PASSED", "FAILED", "INVALIDATED"]
    invalidated_batch_and_restart_reason: str | None = Field(
        default=None,
        max_length=2000,
    )
    cases: tuple[QualificationCaseResultV1, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    test_mode: Literal["PRODUCT"] = "PRODUCT"
    counts_toward_model_score: Literal[False] = False
    counts_toward_stage_gate: Literal[False] = False
    counts_toward_profile_qualification: Literal[False] = False
    counts_toward_observation_policy_qualification: Literal[False] = False

    @model_validator(mode="after")
    def _identity_and_terminal_status_are_consistent(
        self,
    ) -> QualificationExecutionRecordV1:
        if _ID_RE.fullmatch(self.execution_id) is None:
            raise ValueError("execution_id must be a safe lowercase identifier")
        if self.status == "INVALIDATED" and not (
            self.invalidated_batch_and_restart_reason or ""
        ).strip():
            raise ValueError("INVALIDATED requires a restart reason")
        if self.status == "PASSED" and (
            not self.cases or any(case.status != "PASSED" for case in self.cases)
        ):
            raise ValueError("PASSED requires every preregistered case to pass")
        return self


class QualificationCaseResultV2(BaseModel):
    """One workspace case with either proof of success or one failure owner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_name: str = Field(min_length=1, max_length=128)
    delivery_profile_id: Literal["workspace_bundle_v1"] = "workspace_bundle_v1"
    status: Literal["PASSED", "FAILED", "EXPECTED_REJECTION"]
    journey_id: str | None = Field(default=None, max_length=128)
    task_id: str | None = Field(default=None, max_length=256)
    run_id: str | None = Field(default=None, max_length=256)
    historical_verdict: Literal["VERIFIED_TOOL_READY"] | None = None
    clean_replay: Literal["PASS"] | None = None
    fresh_audit: Literal["PASS"] | None = None
    operational_status: Literal["ACTIVE", "REVIEW_REQUIRED", "REVOKED"] | None = None
    package_health: Literal["OK"] | None = None
    artifact_tree_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    artifact_manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    workspace_structure_passed: bool | None = None
    semantic_verifier_id: str | None = Field(default=None, max_length=256)
    semantic_verifier_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    semantic_verifier_evidence_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    semantic_verifier_evidence: SemanticVerifierEvidenceV2 | None = None
    failure_stage: str | None = Field(default=None, max_length=64)
    failure_owner: str | None = Field(default=None, max_length=64)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    recommended_action: str | None = Field(default=None, max_length=2000)
    agent_invoked: bool
    repair_attempts: int = Field(ge=0, le=2)

    @model_validator(mode="after")
    def _terminal_evidence_is_unambiguous(self) -> QualificationCaseResultV2:
        if self.status == "PASSED":
            required = {
                "journey_id": self.journey_id,
                "task_id": self.task_id,
                "run_id": self.run_id,
                "historical_verdict": self.historical_verdict,
                "clean_replay": self.clean_replay,
                "fresh_audit": self.fresh_audit,
                "package_health": self.package_health,
                "artifact_tree_sha256": self.artifact_tree_sha256,
                "artifact_manifest_sha256": self.artifact_manifest_sha256,
                "semantic_verifier_id": self.semantic_verifier_id,
                "semantic_verifier_sha256": self.semantic_verifier_sha256,
                "semantic_verifier_evidence_sha256": (
                    self.semantic_verifier_evidence_sha256
                ),
                "semantic_verifier_evidence": self.semantic_verifier_evidence,
            }
            missing = sorted(name for name, value in required.items() if not value)
            if missing:
                raise ValueError(
                    "PASSED workspace case is missing evidence: " + ", ".join(missing)
                )
            if self.workspace_structure_passed is not True:
                raise ValueError("PASSED workspace case requires structure PASS")
            if self.operational_status != "ACTIVE":
                raise ValueError("PASSED workspace case requires ACTIVE")
            evidence = self.semantic_verifier_evidence
            assert evidence is not None
            mismatches: list[str] = []
            if evidence.verifier_id != self.semantic_verifier_id:
                mismatches.append("semantic_verifier_id")
            if evidence.verifier_source_sha256 != self.semantic_verifier_sha256:
                mismatches.append("semantic_verifier_sha256")
            if evidence.artifact_tree_sha256 != self.artifact_tree_sha256:
                mismatches.append("artifact_tree_sha256")
            if evidence.artifact_manifest_sha256 != self.artifact_manifest_sha256:
                mismatches.append("artifact_manifest_sha256")
            if not evidence.passed:
                mismatches.append("semantic_verifier_evidence.passed")
            if (
                workspace_semantic_evidence_sha256(evidence)
                != self.semantic_verifier_evidence_sha256
            ):
                mismatches.append("semantic_verifier_evidence_sha256")
            if mismatches:
                raise ValueError(
                    "PASSED workspace case has mismatched evidence: "
                    + ", ".join(mismatches)
                )
            if self.failure_owner or self.failure_stage or self.reason_codes:
                raise ValueError("PASSED workspace case cannot carry a failure verdict")
            return self

        if not self.failure_owner or not self.failure_stage or not self.reason_codes:
            raise ValueError("non-passing workspace case requires one failure verdict")
        if not (self.recommended_action or "").strip():
            raise ValueError("non-passing workspace case requires a next action")
        if self.operational_status == "ACTIVE":
            raise ValueError("non-passing workspace case cannot be ACTIVE")
        if self.status == "EXPECTED_REJECTION" and (
            self.agent_invoked or self.repair_attempts != 0
        ):
            raise ValueError("admission rejection must use zero Agent and zero repair")
        return self


class QualificationExecutionRecordV2(BaseModel):
    """Append-only M6.2 record; every preregistered case has one terminal state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    execution_id: str = Field(min_length=1, max_length=128)
    protocol_id: str = Field(min_length=1, max_length=256)
    protocol_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    framework_git_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    framework_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    backend: Literal["mini-swe"] = "mini-swe"
    started_at: str
    completed_at: str
    status: Literal["COMPLETED", "BLOCKED"]
    cases: tuple[QualificationCaseResultV2, ...] = Field(min_length=1, max_length=16)
    test_mode: Literal["PRODUCT"] = "PRODUCT"
    counts_toward_model_score: Literal[False] = False
    counts_toward_stage_gate: Literal[False] = False
    counts_toward_profile_qualification: Literal[False] = False
    counts_toward_observation_policy_qualification: Literal[False] = False

    @model_validator(mode="after")
    def _valid_execution(self) -> QualificationExecutionRecordV2:
        if _ID_RE.fullmatch(self.execution_id) is None:
            raise ValueError("execution_id must be a safe lowercase identifier")
        names = [case.case_name for case in self.cases]
        if len(names) != len(set(names)):
            raise ValueError("qualification case names must be unique")
        return self


QualificationExecutionRecord = (
    QualificationExecutionRecordV1 | QualificationExecutionRecordV2
)


def write_qualification_record(
    root: Path,
    record: QualificationExecutionRecord,
) -> Path:
    """Create one immutable record; duplicate ids and symlinks fail closed."""

    root = Path(root)
    if root.exists() and (not root.is_dir() or root.is_symlink()):
        raise QualificationRecordError(f"unsafe qualification record root: {root}")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise QualificationRecordError(f"unsafe qualification record root: {root}")
    path = root / f"{record.execution_id}.json"
    payload = (
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise QualificationRecordError(
            f"qualification record is append-only: {record.execution_id}"
        ) from exc
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    directory_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return path
