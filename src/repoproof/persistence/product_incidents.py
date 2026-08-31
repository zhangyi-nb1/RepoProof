"""Append-only M6.2 Product incidents and generic Harness-change evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IncidentStage = Literal[
    "INTENT_ADMISSION",
    "CONTRACT_AUTHORING",
    "FIXTURE_REFERENCE",
    "PREFLIGHT_UPSTREAM",
    "AGENT_ADAPTER",
    "ARTIFACT_STRUCTURE",
    "SEMANTIC_VERIFIER",
    "CLEAN_REPLAY",
    "RELEASE_UI",
]
IncidentOwner = Literal[
    "USER_INPUT",
    "CONTRACT",
    "HARNESS",
    "UPSTREAM",
    "AGENT_ADAPTER",
    "VERIFIER",
    "PACKAGE",
    "EXTERNAL",
]
IncidentDisposition = Literal[
    "REPAIR_AGENT",
    "NEW_TASK_VERSION",
    "RETRY_INFRASTRUCTURE",
    "RECORD_PENDING_SECOND_INCIDENT",
    "GENERIC_HARNESS_CHANGE_AUTHORIZED",
    "STOP_NEEDS_HUMAN",
    "UNSUPPORTED",
]

_SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_SAFE_REASON = re.compile(r"[A-Z][A-Z0-9_]{0,95}")
_SHA = r"^[0-9a-f]{64}$"
_COMMIT = r"^[0-9a-f]{40}$"
_PRE_TASK_STAGES: frozenset[IncidentStage] = frozenset(
    {"INTENT_ADMISSION", "CONTRACT_AUTHORING", "PREFLIGHT_UPSTREAM"}
)


class IncidentRecordError(RuntimeError):
    """An incident/evidence record is invalid or would overwrite history."""


class ProductIncidentV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    incident_id: str
    framework_git_commit: str = Field(pattern=_COMMIT)
    framework_tree_sha256: str = Field(pattern=_SHA)
    profile_id: str = Field(min_length=1, max_length=64)
    task_version: str | None = Field(default=None, max_length=256)
    pre_task_context_sha256: str | None = Field(default=None, pattern=_SHA)
    stage: IncidentStage
    owner: IncidentOwner
    normalized_fingerprint: str = Field(pattern=r"^[0-9a-f]{16}$")
    public_failed_nodes: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=64)
    artifact_tree_diff: dict[str, int | str | list[str]] = Field(default_factory=dict)
    agent_diff_present: bool
    repair_eligible: bool
    safety_or_false_success: bool = False
    disposition: IncidentDisposition
    created_at: str

    @field_validator("incident_id", "profile_id")
    @classmethod
    def _safe_id(cls, value: str) -> str:
        value = value.strip()
        if _SAFE_ID.fullmatch(value) is None:
            raise ValueError("incident identifiers must be safe lowercase values")
        return value

    @field_validator("reason_codes")
    @classmethod
    def _safe_reason_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_SAFE_REASON.fullmatch(item) is None for item in value):
            raise ValueError("incident reason codes must be stable uppercase identifiers")
        if len(value) != len(set(value)):
            raise ValueError("incident reason codes must be unique")
        return value

    @model_validator(mode="after")
    def _repair_is_owned_by_agent_only(self) -> ProductIncidentV1:
        if self.repair_eligible and self.owner != "AGENT_ADAPTER":
            raise ValueError("only AGENT_ADAPTER incidents may consume repair")
        if self.repair_eligible and not self.agent_diff_present:
            raise ValueError("repair eligibility requires an adapter diff")
        if self.repair_eligible and not self.public_failed_nodes:
            raise ValueError("repair eligibility requires public failed nodes")
        if self.disposition == "REPAIR_AGENT" and not self.repair_eligible:
            raise ValueError("REPAIR_AGENT requires an eligible Agent incident")
        if (
            self.disposition == "GENERIC_HARNESS_CHANGE_AUTHORIZED"
            and self.owner != "HARNESS"
        ):
            raise ValueError("generic Harness changes require HARNESS ownership")
        if self.pre_task_context_sha256 is not None:
            if self.task_version is not None:
                raise ValueError("pre-task context cannot accompany a task version")
            if self.stage not in _PRE_TASK_STAGES:
                raise ValueError("pre-task context is limited to pre-task stages")
        return self


class HarnessChangeEvidenceV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    evidence_id: str
    invariant: str = Field(min_length=1, max_length=1000)
    anonymous_fixture_id: str
    normalized_fingerprint: str = Field(pattern=r"^[0-9a-f]{16}$")
    before_control_sha256: str = Field(pattern=_SHA)
    after_control_sha256: str = Field(pattern=_SHA)
    affected_component: str = Field(min_length=1, max_length=240)
    incident_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    safety_or_false_success_exception: bool = False
    regression_tests: tuple[str, ...] = Field(min_length=1, max_length=128)
    case_identifier_scan_passed: bool
    created_at: str

    @field_validator("evidence_id", "anonymous_fixture_id")
    @classmethod
    def _safe_evidence_id(cls, value: str) -> str:
        value = value.strip()
        if _SAFE_ID.fullmatch(value) is None:
            raise ValueError("Harness evidence identifiers must be safe lowercase values")
        return value

    @field_validator("incident_ids")
    @classmethod
    def _safe_incident_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(_SAFE_ID.fullmatch(item) is None for item in value):
            raise ValueError("Harness evidence incident ids are invalid")
        if len(value) != len(set(value)):
            raise ValueError("Harness evidence incident ids must be unique")
        return value

    @model_validator(mode="after")
    def _mechanism_evidence_gate(self) -> HarnessChangeEvidenceV1:
        if self.before_control_sha256 == self.after_control_sha256:
            raise ValueError("before and after controls must be distinct evidence")
        if not self.case_identifier_scan_passed:
            raise ValueError("case-specific Core source scan must pass")
        if not self.safety_or_false_success_exception and len(self.incident_ids) < 2:
            raise ValueError("non-safety Harness change requires two independent incidents")
        return self


def public_incident_fingerprint(
    *,
    stage: IncidentStage,
    owner: IncidentOwner,
    reason_codes: list[str] | tuple[str, ...],
    public_failed_nodes: list[str] | tuple[str, ...],
) -> str:
    """Create the public normalized fingerprint without values or paths."""

    safe_nodes = []
    for item in public_failed_nodes:
        leaf = str(item).replace("\\", "/").rsplit("/", 1)[-1]
        leaf = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", leaf)
        leaf = re.sub(r"\b\d+\b", "<n>", leaf)
        safe_nodes.append(leaf[:160])
    basis = json.dumps(
        {
            "stage": stage,
            "owner": owner,
            "reason_codes": sorted(set(reason_codes)),
            "public_failed_nodes": sorted(set(safe_nodes)),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(basis).hexdigest()[:16]


def pre_task_incident_context(
    *,
    repository_url: str,
    resolved_commit: str,
) -> str:
    """Bind a pre-task incident to one repository revision without naming its case."""

    repository_url = repository_url.strip()
    resolved_commit = resolved_commit.strip().lower()
    if not repository_url:
        raise IncidentRecordError("pre-task context requires a repository URL")
    if re.fullmatch(_COMMIT, resolved_commit) is None:
        raise IncidentRecordError("pre-task context requires a resolved commit")
    return hashlib.sha256(
        repository_url.encode("utf-8") + b"\0" + resolved_commit.encode("ascii")
    ).hexdigest()


def _stable_reason_code(value: str) -> str:
    code = re.sub(r"[^A-Z0-9]+", "_", str(value).upper()).strip("_")
    if not code or not code[0].isalpha():
        code = f"PRODUCT_{code or 'ACTION_FAILED'}"
    return code[:96]


def product_action_failure_incident(
    result: object,
    *,
    framework_git_commit: str,
    framework_tree_sha256: str,
) -> ProductIncidentV1:
    """Project one failed workspace action into public append-only evidence.

    Per-round Agent incidents remain more detailed.  This projection closes the
    other stage boundaries (admission through release) using only typed action
    metadata and stable reason codes; it never copies errors, paths, hashes,
    artifact bytes or held-out values into the public fingerprint.
    """

    from repoproof.execution.product_action import ProductActionResultV2

    if not isinstance(result, ProductActionResultV2):
        raise IncidentRecordError("only ProductActionResultV2 can create an M6.2 incident")
    if result.ok:
        raise IncidentRecordError("a successful Product action is not an incident")

    raw_owner = str(result.failure_owner or "HARNESS")
    owner = cast(
        IncidentOwner,
        {
            "AGENT": "AGENT_ADAPTER",
            "AGENT_ADAPTER": "AGENT_ADAPTER",
            "USER": "USER_INPUT",
            "USER_INPUT": "USER_INPUT",
            "CONTRACT": "CONTRACT",
            "HARNESS": "HARNESS",
            "UPSTREAM": "UPSTREAM",
            "EXTERNAL": "EXTERNAL",
            "VERIFICATION": "VERIFIER",
            "VERIFIER": "VERIFIER",
            "PACKAGE": "PACKAGE",
        }.get(raw_owner, "HARNESS"),
    )
    reason_codes = tuple(
        sorted(
            {
                _stable_reason_code(item)
                for item in (
                    *result.reason_codes,
                    *(tuple([result.product_stop_code]) if result.product_stop_code else ()),
                )
            }
        )
    ) or ("PRODUCT_ACTION_FAILED",)
    reason_blob = " ".join(reason_codes)
    typed_stage = str(result.failure_stage or "")
    action = result.action

    if action == "tool-add":
        stage: IncidentStage = (
            "CONTRACT_AUTHORING" if typed_stage == "DRAFTING" else "INTENT_ADMISSION"
        )
    elif "FIXTURE" in reason_blob or "REFERENCE" in reason_blob:
        stage = "FIXTURE_REFERENCE"
    elif "REPLAY" in reason_blob:
        stage = "CLEAN_REPLAY"
    elif owner == "VERIFIER" or typed_stage in {
        "REFERENCE_COMPARISON",
        "OUTPUT_CONTRACT",
        "SEMANTIC_VERIFICATION",
    }:
        stage = "SEMANTIC_VERIFIER"
    elif (
        "STRUCTURE" in reason_blob
        or "ARTIFACT" in reason_blob
        or "REQUIRED_ENTRY" in reason_blob
    ):
        stage = "ARTIFACT_STRUCTURE"
    elif owner == "AGENT_ADAPTER" or typed_stage in {
        "BUILD",
        "ADAPTER_EXECUTION",
    }:
        stage = "AGENT_ADAPTER"
    elif action in {"tool-audit", "tool-mcp", "tool-withdraw"} or typed_stage in {
        "AUDIT_PRECONDITION",
        "AUDIT_INPUT",
        "PACKAGE_VALIDATION",
        "EVIDENCE_PERSISTENCE",
    }:
        stage = "RELEASE_UI"
    else:
        stage = "PREFLIGHT_UPSTREAM"

    disposition = cast(
        IncidentDisposition,
        {
            "USER_INPUT": "UNSUPPORTED" if stage == "INTENT_ADMISSION" else "STOP_NEEDS_HUMAN",
            "CONTRACT": "NEW_TASK_VERSION",
            "HARNESS": "RETRY_INFRASTRUCTURE",
            "UPSTREAM": "RETRY_INFRASTRUCTURE",
            "EXTERNAL": "RETRY_INFRASTRUCTURE",
            "PACKAGE": "RETRY_INFRASTRUCTURE",
            "VERIFIER": "STOP_NEEDS_HUMAN",
            "AGENT_ADAPTER": "STOP_NEEDS_HUMAN",
        }[owner],
    )
    public_nodes = tuple(reason_codes)
    identity = hashlib.sha256(
        f"{result.job_id}\0{result.action}\0{result.created_at}".encode()
    ).hexdigest()[:24]
    return ProductIncidentV1(
        incident_id=f"incident-action-{identity}",
        framework_git_commit=framework_git_commit,
        framework_tree_sha256=framework_tree_sha256,
        profile_id="workspace_bundle_v1",
        task_version=result.task_id,
        stage=stage,
        owner=owner,
        normalized_fingerprint=public_incident_fingerprint(
            stage=stage,
            owner=owner,
            reason_codes=reason_codes,
            public_failed_nodes=public_nodes,
        ),
        public_failed_nodes=public_nodes,
        reason_codes=reason_codes,
        artifact_tree_diff={
            "tree_hash_present": int(result.artifact_tree_sha256 is not None),
            "manifest_hash_present": int(result.artifact_manifest_sha256 is not None),
            "structure_passed": (
                "YES" if result.workspace_structure_passed is True else "NO_OR_UNMEASURED"
            ),
        },
        agent_diff_present=False,
        repair_eligible=False,
        disposition=disposition,
        created_at=result.created_at,
    )


def _write_append_only(path: Path, payload: bytes) -> Path:
    root = path.parent
    if root.exists() and (not root.is_dir() or root.is_symlink()):
        raise IncidentRecordError(f"unsafe append-only root: {root}")
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink():
        raise IncidentRecordError(f"unsafe append-only root: {root}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise IncidentRecordError(f"append-only record already exists: {path.name}") from exc
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


def write_product_incident(root: Path, incident: ProductIncidentV1) -> Path:
    payload = (
        json.dumps(incident.model_dump(mode="json"), ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return _write_append_only(Path(root) / f"{incident.incident_id}.json", payload)


def write_harness_change_evidence(
    root: Path,
    evidence: HarnessChangeEvidenceV1,
    *,
    incident_root: Path | None = None,
) -> Path:
    """Write change evidence only after referenced incidents prove the gate.

    The Pydantic model makes malformed evidence impossible, but an arbitrary
    pair of strings is not proof of two independent failures.  The writer is
    the trusted boundary: it loads the append-only incident bytes, requires the
    same normalized fingerprint and, outside the safety exception, either two
    distinct task versions or two distinct repository revisions observed before
    a task version could exist.
    """

    incident_root = (
        Path(incident_root)
        if incident_root is not None
        else Path(root).parent / "product-incidents"
    )
    if incident_root.is_symlink() or not incident_root.is_dir():
        raise IncidentRecordError("Harness change evidence requires a safe incident root")
    incidents: list[ProductIncidentV1] = []
    for incident_id in evidence.incident_ids:
        path = incident_root / f"{incident_id}.json"
        if path.is_symlink() or not path.is_file():
            raise IncidentRecordError(
                f"Harness change evidence references a missing incident: {incident_id}"
            )
        try:
            raw = path.read_bytes()
            if len(raw) > 1024 * 1024:
                raise IncidentRecordError("referenced incident is too large")
            incident = ProductIncidentV1.model_validate_json(raw)
        except (OSError, ValueError) as exc:
            raise IncidentRecordError(
                f"Harness change evidence references an invalid incident: {incident_id}"
            ) from exc
        if incident.incident_id != incident_id:
            raise IncidentRecordError("incident filename and identity do not match")
        if incident.normalized_fingerprint != evidence.normalized_fingerprint:
            raise IncidentRecordError("referenced incident fingerprint does not match")
        incidents.append(incident)
    if not evidence.safety_or_false_success_exception:
        task_versions = {item.task_version for item in incidents if item.task_version}
        pre_task_contexts = {
            item.pre_task_context_sha256
            for item in incidents
            if item.pre_task_context_sha256 is not None
        }
        all_pre_task = bool(incidents) and all(
            item.task_version is None
            and item.stage in _PRE_TASK_STAGES
            and item.pre_task_context_sha256 is not None
            for item in incidents
        )
        if len(task_versions) < 2 and not (
            all_pre_task and len(pre_task_contexts) >= 2
        ):
            raise IncidentRecordError(
                "non-safety Harness change requires two independent task versions "
                "or pre-task repository contexts"
            )
    payload = (
        json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False,
                   indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return _write_append_only(Path(root) / f"{evidence.evidence_id}.json", payload)


def scan_core_for_case_identifiers(
    source_root: Path,
    forbidden_identifiers: list[str] | tuple[str, ...],
) -> list[str]:
    """Return generic Core files containing preregistered case identifiers."""

    source_root = Path(source_root)
    if source_root.is_symlink() or not source_root.is_dir():
        raise IncidentRecordError("unsafe Core source root")
    needles = [item.casefold() for item in forbidden_identifiers if item.strip()]
    hits: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        if path.is_symlink() or not path.is_file():
            continue
        content = path.read_text(encoding="utf-8", errors="replace").casefold()
        if any(needle in content for needle in needles):
            hits.append(path.relative_to(source_root).as_posix())
    return hits
