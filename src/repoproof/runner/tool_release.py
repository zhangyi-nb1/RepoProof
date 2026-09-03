"""Operational release decisions for verified local tools (RFC-011 M5-c/d).

Historical verification stays in ``tool.json``.  This module owns the separate,
append-only operational decision ledger.  The ledger is deliberately small and
strict: a malformed line makes every consumer fail closed instead of silently
resurrecting a withdrawn tool.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import secrets
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from repoproof.runner.tool_registry import ReleaseAuditTrustIdentityV1

from repoproof.execution.audit_failure import AuditFailureMetadata
from repoproof.execution.frozen_python_env import (
    FrozenPythonEnvironmentError,
    frozen_python_environment,
)
from repoproof.execution.git_checkout import (
    GitCheckoutIdentityError,
    verify_clean_git_checkout,
)
from repoproof.runner.tool_package_identity import (
    ToolPackageIdentityError,
    package_payload_sha256,
    runtime_environment_sha256,
)
from repoproof.runner.tool_paths import (
    ToolPathError,
    append_control_file,
    canonical_tool_path,
    control_file_lock,
    ensure_safe_package_tree,
    read_control_file,
    tool_install_lock,
    validate_tool_name,
    validate_tool_task_id,
)
from repoproof.verification.semantic_artifact import semantic_mechanism_failure

RELEASE_LEDGER_NAME = ".repoproof-release-decisions.jsonl"
RELEASE_LOCK_NAME = ".repoproof-release.lock"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
ACTIVE = "ACTIVE"
REVOKED = "REVOKED"
VALID_RELEASE_DECISIONS = frozenset({REVIEW_REQUIRED, ACTIVE, REVOKED})
VALID_ACTORS = frozenset({"human", "operator", "migration"})
HISTORICAL_READY_VERDICTS = frozenset({"VERIFIED_TOOL_READY", "VERIFIED_TOOL_READY (DIRECT)"})

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

_AUDIT_INTERNAL_FAILURE = AuditFailureMetadata(
    failure_owner="HARNESS",
    failure_stage="AUDIT_PRECONDITION",
    failure_class="HARNESS_ENVIRONMENT",
    retry_policy="RETRY_AFTER_ENVIRONMENT_REPAIR",
    requires_new_task_version=False,
    recommended_action_code="REPAIR_AUDIT_ENVIRONMENT",
    recommended_action=("修复审核环境或受管状态后重试；不要修改 adapter 来绕过审核。"),
    product_stop_code="STOP_HARNESS_OR_EXTERNAL",
)
_AUDIT_INPUT_FAILURE = AuditFailureMetadata(
    failure_owner="USER_INPUT",
    failure_stage="AUDIT_INPUT",
    failure_class="USER_INPUT",
    retry_policy="RETRY_AFTER_INPUT_CORRECTION",
    requires_new_task_version=False,
    recommended_action_code="CORRECT_AUDIT_INPUT",
    recommended_action="修正 Fresh audit 输入、期望文件或参数后重试。",
    product_stop_code="STOP_NEEDS_HUMAN",
)
_STALE_AUDIT_CANDIDATE_FAILURE = AuditFailureMetadata(
    failure_owner="HARNESS",
    failure_stage="AUDIT_PRECONDITION",
    failure_class="PACKAGE_IDENTITY",
    retry_policy="RETRY_AFTER_INPUT_REFRESH",
    requires_new_task_version=False,
    recommended_action_code="REFRESH_AUDIT_CANDIDATE",
    recommended_action=("丢弃旧候选并刷新当前工具版本；重新生成 Fresh audit 候选后再审核。"),
    product_stop_code="STOP_HARNESS_OR_EXTERNAL",
)
_PACKAGE_IDENTITY_FAILURE = AuditFailureMetadata(
    failure_owner="HARNESS",
    failure_stage="PACKAGE_VALIDATION",
    failure_class="PACKAGE_IDENTITY",
    retry_policy="RETRY_AFTER_PACKAGE_RESTORE",
    requires_new_task_version=False,
    recommended_action_code="RESTORE_OR_REEXPORT_PACKAGE",
    recommended_action=("恢复已登记的不可变工具包身份，或重新导出后再审核；不要原地修改已登记包。"),
    product_stop_code="STOP_HARNESS_OR_EXTERNAL",
)
_BUILD_FAILURE = AuditFailureMetadata(
    failure_owner="HARNESS",
    failure_stage="BUILD",
    failure_class="HARNESS_ENVIRONMENT",
    retry_policy="RETRY_AFTER_ENVIRONMENT_REPAIR",
    requires_new_task_version=False,
    recommended_action_code="REPAIR_BUILD_ENVIRONMENT",
    recommended_action=("检查导出包 build.sh、固定依赖与 wheelhouse；环境恢复后重新审核。"),
    product_stop_code="STOP_HARNESS_OR_EXTERNAL",
)
_ADAPTER_EXECUTION_FAILURE = AuditFailureMetadata(
    failure_owner="AGENT_ADAPTER",
    failure_stage="ADAPTER_EXECUTION",
    failure_class="ADAPTER_EXECUTION",
    retry_policy="NEW_TASK_VERSION_REQUIRED",
    requires_new_task_version=True,
    recommended_action_code="FIX_ADAPTER_AND_CREATE_NEW_TASK_VERSION",
    recommended_action="修复 adapter 后创建新任务版本，重新构建并审核。",
    product_stop_code="STOP_NON_REPAIRABLE",
)
_REFERENCE_MISMATCH_FAILURE = AuditFailureMetadata(
    failure_owner="VERIFICATION",
    failure_stage="REFERENCE_COMPARISON",
    failure_class="REFERENCE_MISMATCH",
    retry_policy="REVIEW_REQUIRED",
    requires_new_task_version=False,
    recommended_action_code="REVIEW_REFERENCE_AND_ADAPTER",
    recommended_action=("先核对 operator reference；若真值正确，再修复 adapter 并创建新任务版本。"),
    product_stop_code="STOP_NEEDS_HUMAN",
)
_OUTPUT_CONTRACT_CONFLICT_FAILURE = AuditFailureMetadata(
    failure_owner="CONTRACT",
    failure_stage="OUTPUT_CONTRACT",
    failure_class="CONTRACT_ORACLE_CONFLICT",
    retry_policy="NEW_TASK_VERSION_REQUIRED",
    requires_new_task_version=True,
    recommended_action_code="REVIEW_CONTRACT_AND_CREATE_NEW_TASK_VERSION",
    recommended_action=("人工核对冻结输出合同与 reference；修正冲突后创建新任务版本。"),
    product_stop_code="STOP_NEEDS_HUMAN",
)
_SEMANTIC_MECHANISM_FAILURE = AuditFailureMetadata(
    failure_owner="HARNESS",
    failure_stage="SEMANTIC_VERIFICATION",
    failure_class="HARNESS_ENVIRONMENT",
    retry_policy="REVIEW_REQUIRED",
    requires_new_task_version=False,
    recommended_action_code="RESTORE_SEMANTIC_VERIFIER_AND_REVIEW",
    recommended_action=("恢复冻结 semantic verifier 及证据环境后重新审核；当前需人工复核，不要猜测修改 adapter。"),
    product_stop_code="STOP_HARNESS_OR_EXTERNAL",
)
_SEMANTIC_IDENTITY_FAILURE = AuditFailureMetadata(
    failure_owner="HARNESS",
    failure_stage="SEMANTIC_VERIFICATION",
    failure_class="PACKAGE_IDENTITY",
    retry_policy="RETRY_AFTER_PACKAGE_RESTORE",
    requires_new_task_version=False,
    recommended_action_code="RESTORE_SEMANTIC_VERIFIER_IDENTITY",
    recommended_action=(
        "恢复 registry、冻结合同与 semantic verifier 的一致身份后重新审核；不要修改 adapter 来绕过身份检查。"
    ),
    product_stop_code="STOP_HARNESS_OR_EXTERNAL",
)
_SEMANTIC_ORACLE_CONFLICT_FAILURE = AuditFailureMetadata(
    failure_owner="CONTRACT",
    failure_stage="SEMANTIC_VERIFICATION",
    failure_class="CONTRACT_ORACLE_CONFLICT",
    retry_policy="NEW_TASK_VERSION_REQUIRED",
    requires_new_task_version=True,
    recommended_action_code="REVIEW_CONTRACT_ORACLE_AND_CREATE_NEW_TASK_VERSION",
    recommended_action=(
        "reference bytes 已与工具输出一致；请人工核对冻结合同、reference 与 "
        "semantic oracle，解决冲突后创建新任务版本，不要盲修 adapter。"
    ),
    product_stop_code="STOP_NEEDS_HUMAN",
)
_TERMINAL_CONTRACT_FAILURE = AuditFailureMetadata(
    failure_owner="CONTRACT",
    failure_stage="AUDIT_PRECONDITION",
    failure_class="CONTRACT_ORACLE_CONFLICT",
    retry_policy="NEW_TASK_VERSION_REQUIRED",
    requires_new_task_version=True,
    recommended_action_code="CREATE_NEW_TASK_VERSION_AFTER_CONTRACT_REVIEW",
    recommended_action="复核冻结合同与 oracle 后创建新任务版本；当前版本不能原地恢复。",
    product_stop_code="STOP_NEEDS_HUMAN",
)
_WITHDRAWN_TASK_FAILURE = AuditFailureMetadata(
    failure_owner="USER_INPUT",
    failure_stage="AUDIT_PRECONDITION",
    failure_class="USER_INPUT",
    retry_policy="NEW_TASK_VERSION_REQUIRED",
    requires_new_task_version=True,
    recommended_action_code="CREATE_NEW_TASK_VERSION_AFTER_WITHDRAWAL",
    recommended_action="如需恢复使用，请明确创建新任务版本；普通 audit 不能撤销用户停用。",
    product_stop_code="STOP_NEEDS_HUMAN",
)
_EVIDENCE_PERSISTENCE_FAILURE = AuditFailureMetadata(
    failure_owner="HARNESS",
    failure_stage="EVIDENCE_PERSISTENCE",
    failure_class="HARNESS_ENVIRONMENT",
    retry_policy="RETRY_AFTER_ENVIRONMENT_REPAIR",
    requires_new_task_version=False,
    recommended_action_code="REPAIR_AUDIT_EVIDENCE_STORE",
    recommended_action="修复 release audit 证据目录或存储权限后重新审核。",
    product_stop_code="STOP_HARNESS_OR_EXTERNAL",
)


class ReleaseLedgerError(RuntimeError):
    """The operational ledger cannot be trusted or safely extended."""

    def __init__(
        self,
        message: str,
        *,
        failure: AuditFailureMetadata = _AUDIT_INTERNAL_FAILURE,
    ) -> None:
        super().__init__(message)
        self.failure = failure


class ToolAuditError(RuntimeError):
    """An audit could not safely start (as distinct from an audit failure)."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str | None = None,
        failure: AuditFailureMetadata = _AUDIT_INTERNAL_FAILURE,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.failure = failure
        self.failure_metadata = failure
        self.failure_owner = failure.failure_owner
        self.failure_stage = failure.failure_stage
        self.failure_class = failure.failure_class
        self.retry_policy = failure.retry_policy
        self.requires_new_task_version = failure.requires_new_task_version
        self.recommended_action_code = failure.recommended_action_code
        self.recommended_action = failure.recommended_action
        self.product_stop_code = failure.product_stop_code


@contextmanager
def release_decision_lock(dest_root: Path):
    """Serialize compound release checks and appends across processes."""

    try:
        with control_file_lock(dest_root, RELEASE_LOCK_NAME):
            yield
    except ToolPathError as exc:
        raise ReleaseLedgerError(str(exc)) from exc


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"non-standard JSON constant: {constant}")


def _strict_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _strict_json_loads(value: str | bytes) -> Any:
    return json.loads(
        value,
        parse_constant=_reject_json_constant,
        parse_float=_strict_json_float,
    )


def _same_commitment_coverage(
    observed: Any,
    required: tuple[str, ...],
) -> bool:
    """Compare commitment coverage as a unique set, not verifier output order.

    ``required`` keeps its frozen order as part of the trust identity.  A
    verifier's ``checked_commitment_ids`` only reports coverage, however, and
    different verifier implementations may visit those commitments in a
    different deterministic order.  Reject malformed/duplicate values while
    accepting a complete permutation of the frozen set.
    """

    if not isinstance(observed, (list, tuple)):
        return False
    if any(not isinstance(item, str) for item in observed):
        return False
    return bool(
        len(observed) == len(required) and len(observed) == len(set(observed)) and set(observed) == set(required)
    )


def validate_release_audit_evidence(
    tool_dir: Path,
    *,
    evidence_sha256: str,
    require_semantic_pass: bool,
    trust_identity: ReleaseAuditTrustIdentityV1 | None = None,
) -> bool:
    """Re-resolve one ledger evidence hash from append-only package records.

    The ledger deliberately stores a digest rather than a mutable pathname.
    For a current v3 ACTIVE decision, Core must nevertheless prove that the
    digest still resolves to a regular outer audit record and that its nested
    semantic record is present, hash-valid, bound to the same input/artifact,
    and records PASS.  Older task versions are not retroactively reinterpreted.
    """

    if _SHA256_RE.fullmatch(evidence_sha256) is None:
        return False
    root = Path(tool_dir)
    evidence_dir = root / "evidence" / "release-audits"
    if evidence_dir.is_symlink() or not evidence_dir.is_dir():
        return False
    outer: dict[str, Any] | None = None
    try:
        for candidate in sorted(evidence_dir.glob("*.json")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            parsed = _strict_json_loads(candidate.read_bytes())
            if not isinstance(parsed, dict):
                continue
            if _canonical_sha256(parsed) == evidence_sha256:
                outer = parsed
                break
    except (OSError, UnicodeError, ValueError):
        return False
    if outer is None:
        return False
    if not require_semantic_pass:
        return True
    if trust_identity is None:
        return False

    semantic = outer.get("semantic_verifier")
    execution = outer.get("execution")
    if not isinstance(semantic, dict) or not isinstance(execution, dict):
        return False
    if semantic.get("passed") is not True:
        return False
    nested_hash = semantic.get("evidence_sha256")
    nested_path_raw = semantic.get("evidence_path")
    if (
        not isinstance(nested_hash, str)
        or _SHA256_RE.fullmatch(nested_hash) is None
        or not isinstance(nested_path_raw, str)
        or not nested_path_raw
    ):
        return False
    nested_path = Path(nested_path_raw)
    if not nested_path.is_absolute():
        nested_path = root / nested_path
    semantic_dir = root / "evidence" / "semantic-audits"
    if semantic_dir.is_symlink() or not semantic_dir.is_dir() or nested_path.is_symlink() or not nested_path.is_file():
        return False
    try:
        nested_path.resolve().relative_to(semantic_dir.resolve())
        nested_document = _strict_json_loads(nested_path.read_bytes())
        if not isinstance(nested_document, dict):
            return False
    except (OSError, TypeError, UnicodeError, ValueError):
        return False
    verifier = trust_identity.semantic_verifier
    try:
        current_runtime_environment_sha256 = runtime_environment_sha256(root)
    except (OSError, ToolPackageIdentityError):
        return False
    if nested_document.get("protocol") == "repoproof-workspace-semantic-verifier-v2":
        try:
            from repoproof.domain.models import WorkspaceArtifactContractV1
            from repoproof.execution.workspace_bundle import WorkspaceRuntimeEvidenceV1
            from repoproof.verification.workspace_semantic import (
                SemanticVerifierEvidenceV2,
                workspace_semantic_evidence_sha256,
            )

            workspace = SemanticVerifierEvidenceV2.model_validate(nested_document)
            package_manifest = _strict_json_loads((root / "tool.json").read_bytes())
            if not isinstance(package_manifest, dict):
                return False
            workspace_contract = WorkspaceArtifactContractV1.model_validate(
                package_manifest.get("workspace_contract")
            )
            runtime_document = outer.get("workspace_runtime")
            runtime_ok = not workspace_contract.runnable
            if workspace_contract.runnable:
                runtime = WorkspaceRuntimeEvidenceV1.model_validate(runtime_document)
                runtime_ok = bool(
                    runtime.passed
                    and runtime.artifact_tree_sha256
                    == execution.get("artifact_tree_sha256")
                    and runtime.command_sha256
                    == _canonical_sha256(list(workspace_contract.smoke_command))
                )
        except (OSError, TypeError, ValueError):
            return False
        return bool(
            workspace.passed
            and runtime_ok
            and workspace_semantic_evidence_sha256(workspace) == nested_hash
            and workspace.input_sha256 == outer.get("input_sha256")
            and workspace.artifact_tree_sha256 == execution.get("artifact_tree_sha256")
            and workspace.artifact_tree_sha256 == semantic.get("artifact_tree_sha256")
            and workspace.artifact_manifest_sha256 == execution.get("artifact_manifest_sha256")
            and workspace.verifier_id == verifier.verifier_id
            and workspace.verifier_source_sha256 == verifier.source_sha256
            and workspace.workspace_contract_sha256 == trust_identity.output_contract_sha256
            and workspace.intent_confirmation_sha256 == trust_identity.intent_confirmation_sha256
            and workspace.upstream_commit == trust_identity.upstream_commit
            and workspace.import_module == trust_identity.import_module
            and workspace.required_commitment_ids == trust_identity.required_commitment_ids
            and _same_commitment_coverage(
                workspace.checked_commitment_ids,
                trust_identity.required_commitment_ids,
            )
            and workspace.upstream_calls >= 1
            and workspace.input_negative_control_result == "REJECTED"
            and workspace.artifact_negative_control_result == "REJECTED"
            and workspace.upstream_result_counterfactual_result == "REJECTED"
            and semantic.get("verifier_id") == verifier.verifier_id
            and semantic.get("required_commitment_ids") == list(trust_identity.required_commitment_ids)
            and _same_commitment_coverage(
                semantic.get("checked_commitment_ids"),
                trust_identity.required_commitment_ids,
            )
            and outer.get("runtime_environment_sha256") == current_runtime_environment_sha256
        )
    try:
        from repoproof.verification.semantic_artifact import (
            SemanticVerifierEvidenceV1,
            semantic_verifier_evidence_sha256,
        )

        nested = SemanticVerifierEvidenceV1.model_validate(nested_document)
    except (TypeError, ValueError):
        return False
    return bool(
        nested.passed
        and semantic_verifier_evidence_sha256(nested) == nested_hash
        and nested.input_sha256 == outer.get("input_sha256")
        and nested.artifact_sha256 == execution.get("stdout_sha256")
        and nested.artifact_sha256 == semantic.get("artifact_sha256")
        and nested.verifier_id == verifier.verifier_id
        and nested.verifier_source_sha256 == verifier.source_sha256
        and nested.output_contract_sha256 == trust_identity.output_contract_sha256
        and nested.intent_confirmation_sha256 == trust_identity.intent_confirmation_sha256
        and nested.upstream_commit == trust_identity.upstream_commit
        and nested.import_module == trust_identity.import_module
        and nested.required_commitment_ids == trust_identity.required_commitment_ids
        and _same_commitment_coverage(
            nested.checked_commitment_ids,
            trust_identity.required_commitment_ids,
        )
        and nested.upstream_calls >= 1
        and semantic.get("verifier_id") == verifier.verifier_id
        and semantic.get("required_commitment_ids") == list(trust_identity.required_commitment_ids)
        and _same_commitment_coverage(
            semantic.get("checked_commitment_ids"),
            trust_identity.required_commitment_ids,
        )
        and outer.get("runtime_environment_sha256") == current_runtime_environment_sha256
    )


def is_historical_tool_ready(verdict: Any) -> bool:
    """Accept only the two Product Mode verdicts mapped from completion PASS."""

    return isinstance(verdict, str) and verdict in HISTORICAL_READY_VERDICTS


def parse_operator_audit_outcome(row: dict[str, Any], *, where: str) -> bool:
    """Parse compatible audit outcome fields and reject contradictions."""

    has_ok = "ok" in row
    ok = row.get("ok")
    if has_ok and type(ok) is not bool:
        raise ReleaseLedgerError(f"{where}: ok 必须为 boolean")

    has_verdict = "verdict" in row
    verdict = row.get("verdict")
    verdict_ok: bool | None = None
    if has_verdict:
        if not isinstance(verdict, str) or verdict.upper() not in {"PASS", "FAIL"}:
            raise ReleaseLedgerError(f"{where}: verdict 必须为 PASS 或 FAIL")
        verdict_ok = verdict.upper() == "PASS"
    if not has_ok and not has_verdict:
        raise ReleaseLedgerError(f"{where}: audit 缺 PASS/FAIL verdict 或 boolean ok")
    if has_ok and verdict_ok is not None and ok != verdict_ok:
        raise ReleaseLedgerError(f"{where}: ok 与 verdict 矛盾")
    return bool(ok if has_ok else verdict_ok)


def _validate_rfc3339_utc(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0)


def _validate_decision(row: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ReleaseLedgerError(f"{where}: release decision 必须是 JSON object")

    required = {
        "schema_version",
        "tool",
        "task_id",
        "run_id",
        "decision",
        "reason_code",
        "reason",
        "evidence_sha256",
        "decided_at",
        "actor",
    }
    missing = sorted(required - row.keys())
    if missing:
        raise ReleaseLedgerError(f"{where}: release decision 缺字段 {missing}")
    if type(row["schema_version"]) is not int or row["schema_version"] != 1:
        raise ReleaseLedgerError(f"{where}: schema_version 必须为 1")
    try:
        validate_tool_name(row["tool"])
    except ToolPathError as exc:
        raise ReleaseLedgerError(f"{where}: {exc}") from exc
    try:
        validate_tool_task_id(row["tool"], row["task_id"])
    except ToolPathError as exc:
        raise ReleaseLedgerError(f"{where}: {exc}") from exc
    if row["run_id"] is not None and not isinstance(row["run_id"], str):
        raise ReleaseLedgerError(f"{where}: run_id 必须为字符串或 null")
    if row["decision"] not in VALID_RELEASE_DECISIONS:
        raise ReleaseLedgerError(f"{where}: decision={row['decision']!r}，只允许 {sorted(VALID_RELEASE_DECISIONS)}")
    if not isinstance(row["reason_code"], str) or not row["reason_code"].strip():
        raise ReleaseLedgerError(f"{where}: reason_code 必须为非空字符串")
    if not isinstance(row["reason"], str) or not row["reason"].strip():
        raise ReleaseLedgerError(f"{where}: reason 必须为非空字符串")
    if not isinstance(row["evidence_sha256"], str) or not _SHA256_RE.fullmatch(row["evidence_sha256"]):
        raise ReleaseLedgerError(f"{where}: evidence_sha256 必须为 64 位小写十六进制")
    if not _validate_rfc3339_utc(row["decided_at"]):
        raise ReleaseLedgerError(f"{where}: decided_at 必须为 RFC3339 UTC 时间")
    if row["actor"] not in VALID_ACTORS:
        raise ReleaseLedgerError(f"{where}: actor 只允许 {sorted(VALID_ACTORS)}")
    return row


def load_release_decisions_file(ledger: Path) -> list[dict[str, Any]]:
    """Load one ledger path and validate every row; damage fails closed.

    Path-based consumers such as the metrics exporter use this entry point so
    release-state schema validation has one implementation across the product.
    A missing ledger is the valid pre-audit state and therefore folds to no
    decisions (``REVIEW_REQUIRED`` at the consumer boundary).
    """

    ledger = Path(ledger)
    try:
        encoded = read_control_file(ledger, missing_ok=True)
        if encoded is None:
            return []
        if encoded and not encoded.endswith(b"\n"):
            raise ReleaseLedgerError(f"{ledger}: 非空 append-only ledger 必须以换行结束")
        raw = encoded.decode("utf-8")
    except (ToolPathError, UnicodeError) as exc:
        raise ReleaseLedgerError(f"无法读取 release ledger {ledger}: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise ReleaseLedgerError(f"{ledger}:{line_no}: 空行使 append-only ledger 不可信")
        try:
            row = _strict_json_loads(line)
        except ValueError as exc:
            raise ReleaseLedgerError(f"{ledger}:{line_no}: 损坏 JSON: {exc}") from exc
        rows.append(_validate_decision(row, where=f"{ledger}:{line_no}"))
    return rows


def load_release_decisions(dest_root: Path) -> list[dict[str, Any]]:
    """Load the standard ledger below ``dest_root``."""

    return load_release_decisions_file(Path(dest_root) / RELEASE_LEDGER_NAME)


def fold_release_decisions(dest_root: Path) -> dict[str, dict[str, Any]]:
    """Fold by tool name; the last valid append-only decision wins."""

    folded: dict[str, dict[str, Any]] = {}
    for row in load_release_decisions(dest_root):
        folded[row["tool"]] = row
    return folded


def fold_release_statuses(dest_root: Path) -> dict[str, str]:
    """Stable read-only projection used by registry, metrics, and consumers."""

    return {tool: row["decision"] for tool, row in fold_release_decisions(dest_root).items()}


def operational_status(dest_root: Path, tool: str, *, task_id: str | None = None) -> str:
    """Return current status; absence or a task-version mismatch needs review.

    A tool name is a stable local command, but an audit decision is scoped to
    the frozen task version that produced it.  Passing ``task_id`` prevents a
    newly registered version from inheriting an older version's ``ACTIVE``.
    """

    row = fold_release_decisions(dest_root).get(tool)
    if row is None:
        return REVIEW_REQUIRED
    if task_id is not None and row["task_id"] != task_id:
        return REVIEW_REQUIRED
    # Registered packages use the same Core projection as ``tool list``.  This
    # revalidates v3 package and evidence identities instead of trusting the
    # last ledger line.  Pre-registry legacy callers retain their historical
    # ledger-only behavior.
    from repoproof.runner.tool_registry import list_tools, load_registry

    registry = load_registry(dest_root)
    if tool not in registry.get("tools", {}):
        return row["decision"]
    listed = next((item for item in list_tools(dest_root, scan=False) if item["name"] == tool), None)
    if listed is None:
        return REVIEW_REQUIRED
    if task_id is not None and listed.get("task_id") != task_id:
        return REVIEW_REQUIRED
    status = listed.get("operational_status")
    return status if status in VALID_RELEASE_DECISIONS else REVIEW_REQUIRED


def _append_release_decision_unlocked(
    dest_root: Path,
    *,
    tool: str,
    task_id: str,
    run_id: str | None,
    decision: str,
    reason_code: str,
    reason: str,
    evidence_sha256: str,
    actor: str,
    decided_at: str | None = None,
) -> dict[str, Any]:
    """Validate and append while the caller holds ``release_decision_lock``."""

    dest_root = Path(dest_root)
    # Crucial fail-closed step: never append behind a damaged row.
    load_release_decisions(dest_root)
    row: dict[str, Any] = {
        "schema_version": 1,
        "tool": tool,
        "task_id": task_id,
        "run_id": run_id,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "evidence_sha256": evidence_sha256,
        "decided_at": decided_at or _utc_now(),
        "actor": actor,
    }
    _validate_decision(row, where="new release decision")
    dest_root.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        # One O_APPEND write keeps each validated decision as one record.
        append_control_file(dest_root / RELEASE_LEDGER_NAME, encoded)
    except (OSError, ToolPathError) as exc:
        raise ReleaseLedgerError(f"无法 append release decision: {exc}") from exc
    return row


def append_release_decision(
    dest_root: Path,
    *,
    tool: str,
    task_id: str,
    run_id: str | None,
    decision: str,
    reason_code: str,
    reason: str,
    evidence_sha256: str,
    actor: str,
    decided_at: str | None = None,
) -> dict[str, Any]:
    """Atomically validate the existing ledger and append one decision."""

    with release_decision_lock(dest_root):
        return _append_release_decision_unlocked(
            dest_root,
            tool=tool,
            task_id=task_id,
            run_id=run_id,
            decision=decision,
            reason_code=reason_code,
            reason=reason,
            evidence_sha256=evidence_sha256,
            actor=actor,
            decided_at=decided_at,
        )


def ensure_initial_review_decision(
    dest_root: Path,
    *,
    tool: str,
    task_id: str,
    run_id: str | None,
    evidence_sha256: str,
) -> dict[str, Any] | None:
    """Append initial REVIEW_REQUIRED only if this tool has no prior decision.

    Re-registration must never override an existing ACTIVE or REVOKED state.
    """

    with release_decision_lock(dest_root):
        current = fold_release_decisions(dest_root).get(tool)
        if current is not None and current["task_id"] == task_id:
            return None
        return _append_release_decision_unlocked(
            dest_root,
            tool=tool,
            task_id=task_id,
            run_id=run_id,
            decision=REVIEW_REQUIRED,
            reason_code="INITIAL_EXPORT_REVIEW_REQUIRED",
            reason="Export completed; fresh-input operational audit is required before activation.",
            evidence_sha256=evidence_sha256,
            actor="operator",
        )


def _tool_context(dest_root: Path, name: str) -> tuple[Path, dict[str, Any], str, str | None]:
    try:
        tool_dir = canonical_tool_path(dest_root, name)
        ensure_safe_package_tree(tool_dir)
    except ToolPathError as exc:
        raise ToolAuditError(str(exc), failure=_PACKAGE_IDENTITY_FAILURE) from exc
    manifest_path = tool_dir / "tool.json"
    if not manifest_path.is_file():
        raise ToolAuditError(
            f"工具 manifest 不存在: {manifest_path}",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ToolAuditError(
            f"工具 manifest 无法读取: {manifest_path}: {exc}",
            failure=_PACKAGE_IDENTITY_FAILURE,
        ) from exc
    if not isinstance(manifest, dict):
        raise ToolAuditError(
            f"工具 manifest 必须为 JSON object: {manifest_path}",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    manifest_name = manifest.get("name")
    if manifest_name != name:
        raise ToolAuditError(
            f"目录名 {name!r} 与 tool.json name={manifest_name!r} 不一致",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )

    provenance_path = tool_dir / "evidence" / "provenance.json"
    if not provenance_path.is_file():
        raise ToolAuditError(
            f"工具 provenance 不存在: {provenance_path}",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ToolAuditError(
            f"provenance 无法读取: {provenance_path}: {exc}",
            failure=_PACKAGE_IDENTITY_FAILURE,
        ) from exc
    if not isinstance(provenance, dict):
        raise ToolAuditError(
            f"provenance 必须为 JSON object: {provenance_path}",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    task_id = provenance.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ToolAuditError(
            f"provenance task_id 必须为非空字符串: {provenance_path}",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    try:
        validate_tool_task_id(name, task_id)
    except ToolPathError as exc:
        raise ToolAuditError(str(exc), failure=_PACKAGE_IDENTITY_FAILURE) from exc
    if provenance.get("tool") != name:
        raise ToolAuditError(
            "provenance tool 与 manifest/canonical name 不一致",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    verification = manifest.get("verification")
    if not isinstance(verification, dict):
        raise ToolAuditError(
            "tool.json verification 必须为 JSON object",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    run_id = verification.get("run_id")
    contract_sha256 = verification.get("contract_sha256")
    if not isinstance(run_id, str) or not run_id or provenance.get("run_id") != run_id:
        raise ToolAuditError(
            "manifest/provenance run_id 不一致",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    if (
        not isinstance(contract_sha256, str)
        or not contract_sha256
        or provenance.get("tool_contract_sha256") != contract_sha256
    ):
        raise ToolAuditError(
            "manifest/provenance contract_sha256 不一致",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    return tool_dir, manifest, task_id, run_id


def _package_control_identity(tool_dir: Path) -> str:
    """Bind audit execution to every immutable installed payload byte."""

    try:
        return package_payload_sha256(tool_dir)
    except (OSError, ToolPackageIdentityError) as exc:
        raise ToolAuditError(
            f"无法读取 package identity:{exc}",
            failure=_PACKAGE_IDENTITY_FAILURE,
        ) from exc


def _managed_release_identity(
    *,
    dest_root: Path,
    name: str,
    tool_dir: Path,
    manifest: dict[str, Any],
    task_id: str,
    run_id: str | None,
) -> tuple[
    int,
    dict[str, Any] | None,
    ReleaseAuditTrustIdentityV1 | None,
]:
    """Resolve semantic trust from the managed registry, not the audited package.

    Legacy packages created before ToolSpec v3 remain readable.  A package that
    claims v3, however, must have had its schema, verifier identity and complete
    immutable payload identity recorded during managed installation.  Removing
    both v3 fields from the package therefore cannot downgrade it to legacy.
    """

    from repoproof.runner.tool_registry import (
        load_registry,
        validate_contract_schema_version,
        validate_release_audit_trust_identity,
        validate_semantic_verifier_identity,
    )

    try:
        package_schema = validate_contract_schema_version(manifest)
        provenance = _read_package_provenance(tool_dir)
        package_semantic = validate_semantic_verifier_identity(
            provenance.get("semantic_verifier_identity"),
            required=package_schema >= 3,
        )
        registry = load_registry(dest_root)
        entry = registry.get("tools", {}).get(name)
    except (OSError, TypeError, ValueError) as exc:
        raise ToolAuditError(
            "managed package trust identity is unreadable",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        ) from exc

    if not isinstance(entry, dict):
        if package_schema >= 3 or package_semantic is not None:
            raise ToolAuditError(
                "ToolSpec v3 package is missing its managed registry identity",
                reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
                failure=_SEMANTIC_IDENTITY_FAILURE,
            )
        return package_schema, None, None

    verification = manifest.get("verification") or {}
    if (
        entry.get("task_id") != task_id
        or entry.get("run_id") != run_id
        or entry.get("contract_sha256") != verification.get("contract_sha256")
    ):
        raise ToolAuditError(
            "registry and package task identity differ",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        )

    registered_schema = entry.get("contract_schema_version")
    if registered_schema is None:
        if package_schema >= 3:
            raise ToolAuditError(
                "ToolSpec v3 package lacks a frozen registry schema identity",
                reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
                failure=_SEMANTIC_IDENTITY_FAILURE,
            )
        registered_schema = package_schema
    if registered_schema != package_schema:
        raise ToolAuditError(
            "registry and package contract schema differ",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        )

    registry_semantic = validate_semantic_verifier_identity(
        entry.get("semantic_verifier_identity"),
        required=registered_schema >= 3,
    )
    if registry_semantic != package_semantic:
        raise ToolAuditError(
            "registry and package semantic verifier identities differ",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        )
    package_release_identity = validate_release_audit_trust_identity(
        provenance.get("release_audit_trust_identity"),
        required=registered_schema >= 3,
    )
    registry_release_identity = validate_release_audit_trust_identity(
        entry.get("release_audit_trust_identity"),
        required=registered_schema >= 3,
    )
    if package_release_identity != registry_release_identity:
        raise ToolAuditError(
            "registry and package release audit trust identities differ",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        )
    registered_payload = entry.get("package_payload_sha256")
    observed_payload = _package_control_identity(tool_dir)
    if registered_schema >= 3 and registered_payload is None:
        raise ToolAuditError(
            "ToolSpec v3 package lacks a frozen payload identity",
            reason_code="PACKAGE_PAYLOAD_IDENTITY_INVALID",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    if registered_payload not in (None, observed_payload):
        raise ToolAuditError(
            "installed package payload differs from its registered identity",
            reason_code="PACKAGE_PAYLOAD_IDENTITY_INVALID",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    return registered_schema, registry_semantic, registry_release_identity


def withdraw_tool(dest_root: Path, name: str, *, reason: str) -> dict[str, Any]:
    """Append a human withdrawal without deleting or rewriting the tool package."""

    dest_root = Path(dest_root)
    if not reason.strip():
        raise ToolAuditError("withdraw reason 不能为空", failure=_AUDIT_INPUT_FAILURE)
    with tool_install_lock(dest_root):
        with release_decision_lock(dest_root):
            load_release_decisions(dest_root)
            _tool_dir, _manifest, task_id, run_id = _tool_context(dest_root, name)
            evidence_sha256 = _canonical_sha256(
                {
                    "action": "withdraw",
                    "tool": name,
                    "task_id": task_id,
                    "run_id": run_id,
                    "reason": reason,
                }
            )
            return _append_release_decision_unlocked(
                dest_root,
                tool=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="USER_WITHDRAWAL",
                reason=reason.strip(),
                evidence_sha256=evidence_sha256,
                actor="human",
            )


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _public_fixture_hashes(tool_dir: Path) -> set[str]:
    """Hash exported public fixtures so copying one elsewhere is not "fresh"."""

    hashes: set[str] = set()
    for relative_root in ("public_examples", "public_tests"):
        root = tool_dir / relative_root
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            if candidate.is_file():
                try:
                    hashes.add(_sha256(candidate.read_bytes()))
                except OSError as exc:
                    raise ToolAuditError(
                        f"无法读取公开 fixture {candidate}: {exc}",
                        failure=_PACKAGE_IDENTITY_FAILURE,
                    ) from exc
    return hashes


def _public_fixture_path_identities(tool_dir: Path) -> set[str]:
    """Collect file and directory identities without following fixture links."""
    from repoproof.execution.workspace_bundle import identify_input_path

    identities = _public_fixture_hashes(tool_dir)
    for relative_root in ("public_examples", "public_tests"):
        root = tool_dir / relative_root
        if root.is_symlink() or not root.is_dir():
            continue
        for candidate in sorted(root.rglob("*")):
            if candidate.is_symlink() or not candidate.is_dir():
                continue
            try:
                identities.add(identify_input_path(candidate).sha256)
            except (OSError, ValueError):
                continue
    return identities


def _output_contract_errors(manifest: dict[str, Any], actual: bytes) -> list[str]:
    contract = ((manifest.get("interface") or {}).get("output") or {}).get("contract")
    if contract is None:  # Compatible legacy frozen tools retain exact-output audit semantics.
        return []
    try:
        text = actual.decode("utf-8")
    except UnicodeDecodeError:
        return ["[tool-output-contract] stdout is not UTF-8"]

    # This is the same deterministic parser used by freeze/runtime gates.
    from repoproof.adoption.assembly.output_contract import validate_output_text

    try:
        return validate_output_text(text, contract)
    except (TypeError, ValueError):
        return ["[tool-output-contract] declared contract is invalid"]


def _record_audit_decision(
    dest_root: Path,
    *,
    name: str,
    task_id: str,
    run_id: str | None,
    decision: str,
    reason_code: str,
    reason: str,
    evidence: dict[str, Any],
    failure: AuditFailureMetadata | None,
) -> dict[str, Any]:
    if decision != ACTIVE and failure is None:
        raise ToolAuditError(
            "non-active audit decision is missing typed failure metadata",
            failure=_AUDIT_INTERNAL_FAILURE,
        )
    evidence_sha256 = _canonical_sha256(evidence)
    tool_dir = canonical_tool_path(dest_root, name)
    evidence_dir = tool_dir / "evidence" / "release-audits"
    if evidence_dir.exists() and (evidence_dir.is_symlink() or not evidence_dir.is_dir()):
        raise ToolAuditError(
            "release audit evidence directory is unsafe",
            failure=_EVIDENCE_PERSISTENCE_FAILURE,
        )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if evidence_dir.is_symlink():
        raise ToolAuditError(
            "release audit evidence directory is unsafe",
            failure=_EVIDENCE_PERSISTENCE_FAILURE,
        )
    evidence_path = evidence_dir / f"{secrets.token_hex(16)}.json"
    encoded = (
        json.dumps(
            evidence,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(evidence_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ToolAuditError(
            "release audit evidence could not be persisted",
            failure=_EVIDENCE_PERSISTENCE_FAILURE,
        ) from exc
    evidence_directory_descriptor = os.open(
        evidence_dir,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(evidence_directory_descriptor)
    finally:
        os.close(evidence_directory_descriptor)
    row = _append_release_decision_unlocked(
        dest_root,
        tool=name,
        task_id=task_id,
        run_id=run_id,
        decision=decision,
        reason_code=reason_code,
        reason=reason,
        evidence_sha256=evidence_sha256,
        actor="operator",
    )
    result = {
        "ok": decision == ACTIVE,
        "tool": name,
        "task_id": task_id,
        "historical_verdict": evidence.get("historical_verdict"),
        "operational_status": decision,
        "reason_code": reason_code,
        "evidence_sha256": evidence_sha256,
        "evidence_path": str(evidence_path),
        "decision": row,
    }
    if failure is not None:
        result.update(failure.as_payload())
    semantic = evidence.get("semantic_verifier")
    if isinstance(semantic, dict):
        for key in (
            "verifier_id",
            "artifact_sha256",
            "artifact_tree_sha256",
            "artifact_manifest_sha256",
            "evidence_sha256",
            "evidence_path",
            "passed",
        ):
            if key in semantic:
                result[f"semantic_verifier_{key}"] = semantic[key]
    if evidence.get("artifact_kind") == "directory":
        result["delivery_profile_id"] = "workspace_bundle_v1"
        result["artifact_kind"] = "directory"
        structure = evidence.get("workspace_structure")
        if isinstance(structure, dict) and type(structure.get("ok")) is bool:
            result["workspace_structure_passed"] = structure["ok"]
        execution = evidence.get("execution")
        if isinstance(execution, dict):
            for key in ("artifact_tree_sha256", "artifact_manifest_sha256"):
                value = execution.get(key)
                if isinstance(value, str):
                    result[key] = value
    return result


def _read_package_provenance(tool_dir: Path) -> dict[str, Any]:
    path = tool_dir / "evidence" / "provenance.json"
    if path.is_symlink() or not path.is_file():
        raise ToolAuditError(
            "semantic audit requires regular package provenance",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    try:
        value = _strict_json_loads(path.read_bytes())
    except (OSError, UnicodeError, ValueError) as exc:
        raise ToolAuditError(
            "semantic audit could not read package provenance",
            failure=_PACKAGE_IDENTITY_FAILURE,
        ) from exc
    if not isinstance(value, dict):
        raise ToolAuditError(
            "semantic audit package provenance must be an object",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    return value


def _run_required_semantic_audit(
    *,
    project_root: Path | None,
    tool_dir: Path,
    manifest: dict[str, Any],
    task_id: str,
    input_path: Path,
    artifact: bytes | Path,
    required_schema_version: int,
    required_semantic_identity: dict[str, Any] | None,
    required_release_identity: ReleaseAuditTrustIdentityV1 | None,
) -> dict[str, Any] | None:
    """Run the frozen task oracle for ToolSpec v3, or return None for history.

    No domain rule lives here. The task-authored verifier owns semantic logic;
    this function only resolves immutable identities, enforces isolation and
    binds an append-only evidence record to the exact audit artifact.
    """

    provenance = _read_package_provenance(tool_dir)
    claimed_identity = provenance.get("semantic_verifier_identity")
    requires_semantic = required_schema_version >= 3
    if not requires_semantic:
        if (
            required_semantic_identity is not None
            or required_release_identity is not None
            or claimed_identity is not None
        ):
            raise ToolAuditError(
                "legacy package has an unexpected semantic verifier identity",
                reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
                failure=_SEMANTIC_IDENTITY_FAILURE,
            )
        return None
    if project_root is None:
        raise ToolAuditError(
            "ToolSpec v3 audit requires its frozen project evidence root",
            reason_code="SEMANTIC_VERIFIER_CONTEXT_REQUIRED",
            failure=_SEMANTIC_MECHANISM_FAILURE,
        )
    root_candidate = Path(project_root)
    if root_candidate.is_symlink() or not root_candidate.is_dir():
        raise ToolAuditError(
            "semantic verifier project root is unsafe",
            reason_code="SEMANTIC_VERIFIER_CONTEXT_INVALID",
            failure=_SEMANTIC_MECHANISM_FAILURE,
        )
    root = root_candidate.resolve()

    from repoproof.domain.models import TaskContract
    from repoproof.harness.task_package import load_and_verify
    from repoproof.runner.tool_registry import (
        release_audit_trust_identity_from_contract,
    )
    from repoproof.verification.semantic_artifact import (
        SemanticVerifierError,
        run_semantic_verifier,
        semantic_verifier_evidence_sha256,
        write_semantic_verifier_evidence,
    )
    from repoproof.verification.workspace_semantic import (
        run_workspace_semantic_verifier,
        workspace_semantic_evidence_sha256,
        write_workspace_semantic_evidence,
    )

    contract_path = root / "contracts" / f"{task_id}.yaml"
    try:
        contract, contract_sha = TaskContract.load_frozen(
            contract_path,
            require_sidecar=True,
        )
        package = load_and_verify(root, contract_path)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ToolAuditError(
            "frozen task package cannot be verified for semantic audit",
            reason_code="SEMANTIC_VERIFIER_CONTEXT_INVALID",
            failure=_SEMANTIC_MECHANISM_FAILURE,
        ) from exc
    if (
        contract.task_id != task_id
        or contract_sha != provenance.get("tool_contract_sha256")
        or contract.tool is None
        or contract.tool.name != manifest.get("name")
        or contract.tool.schema_version < 3
    ):
        raise ToolAuditError(
            "semantic verifier task/package identity mismatch",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        )
    spec = contract.acceptance.semantic_verifier
    frozen_release_identity = release_audit_trust_identity_from_contract(contract)
    if (
        spec is None
        or required_semantic_identity != spec.model_dump(mode="json")
        or claimed_identity != required_semantic_identity
        or required_release_identity is None
        or frozen_release_identity != required_release_identity
    ):
        raise ToolAuditError(
            "semantic verifier identity is absent or differs from the frozen contract",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        )
    source = root / spec.source_file
    try:
        source.resolve().relative_to(root)
    except ValueError as exc:
        raise ToolAuditError(
            "semantic verifier escaped the project root",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        ) from exc
    if source.is_symlink() or not source.is_file():
        raise ToolAuditError(
            "semantic verifier source is missing or unsafe",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        )
    if _sha256(source.read_bytes()) != spec.source_sha256:
        raise ToolAuditError(
            "semantic verifier source differs from its frozen hash",
            reason_code="SEMANTIC_VERIFIER_IDENTITY_INVALID",
            failure=_SEMANTIC_IDENTITY_FAILURE,
        )

    upstream = root / "upstream-cache" / (f"upstream-{contract.source_repo.resolved_commit[:12]}")
    try:
        verify_clean_git_checkout(
            upstream,
            expected_commit=contract.source_repo.resolved_commit,
            expected_tree=package.source_git_tree_hash,
        )
    except (GitCheckoutIdentityError, OSError, subprocess.SubprocessError) as exc:
        raise ToolAuditError(
            "pinned upstream checkout differs from the frozen clean identity",
            reason_code="SEMANTIC_VERIFIER_CONTEXT_INVALID",
            failure=_SEMANTIC_MECHANISM_FAILURE,
        ) from exc

    intent = contract.capability.intent_contract
    artifact_contract = (
        contract.tool.workspace_contract
        if contract.tool.schema_version == 4
        else contract.tool.interface.output.contract
    )
    if artifact_contract is None or intent is None:
        raise ToolAuditError(
            "v3+ semantic audit is missing artifact contract or intent identity",
            reason_code="SEMANTIC_VERIFIER_CONTEXT_INVALID",
            failure=_SEMANTIC_MECHANISM_FAILURE,
        )
    output_contract_sha256 = _canonical_sha256(artifact_contract.model_dump(mode="json"))
    host_contract = root / "tool_tasks" / task_id / "contract.yaml"
    try:
        import yaml

        host_document = yaml.safe_load(host_contract.read_text(encoding="utf-8")) or {}
        wheelhouse = Path(str((host_document.get("host") or {}).get("wheelhouse_path") or ""))
    except (OSError, TypeError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        raise ToolAuditError(
            "semantic audit cannot resolve its frozen wheel environment",
            reason_code="SEMANTIC_VERIFIER_CONTEXT_INVALID",
            failure=_SEMANTIC_MECHANISM_FAILURE,
        ) from exc

    try:
        semantic_evidence: Any
        with frozen_python_environment(
            wheelhouse=wheelhouse,
            expected_wheels=package.wheelhouse_wheels,
            expected_root=package.wheelhouse_root,
        ) as python_exe:
            if contract.tool.schema_version == 4:
                if not isinstance(artifact, Path):
                    raise SemanticVerifierError("workspace semantic audit requires an artifact directory")
                artifact_path = artifact
                semantic_evidence = run_workspace_semantic_verifier(
                    verifier_id=spec.verifier_id,
                    verifier_source=source,
                    input_path=input_path,
                    artifact_dir=artifact_path,
                    python_exe=python_exe,
                    upstream_dir=upstream,
                    import_module=contract.source_repo.import_name,
                    upstream_commit=contract.source_repo.resolved_commit,
                    workspace_contract_sha256=output_contract_sha256,
                    intent_confirmation_sha256=intent.confirmation.semantics_sha256,
                    required_commitment_ids=[commitment.commitment_id for commitment in intent.commitments],
                    execute_installed_upstream=True,
                    isolation_required=True,
                )
            else:
                if not isinstance(artifact, bytes):
                    raise SemanticVerifierError("single-artifact semantic audit requires bytes")
                with tempfile.TemporaryDirectory(prefix="rp-release-semantic-") as temp:
                    artifact_path = Path(temp) / "artifact"
                    artifact_path.write_bytes(artifact)
                    semantic_evidence = run_semantic_verifier(
                        verifier_id=spec.verifier_id,
                        verifier_source=source,
                        input_path=input_path,
                        artifact_path=artifact_path,
                        python_exe=python_exe,
                        upstream_dir=upstream,
                        import_module=contract.source_repo.import_name,
                        upstream_commit=contract.source_repo.resolved_commit,
                        output_contract_sha256=output_contract_sha256,
                        intent_confirmation_sha256=(intent.confirmation.semantics_sha256),
                        required_commitment_ids=[commitment.commitment_id for commitment in intent.commitments],
                        execute_installed_upstream=True,
                        isolation_required=True,
                    )
        evidence_path = tool_dir / "evidence" / "semantic-audits" / f"{secrets.token_hex(16)}.json"
        if contract.tool.schema_version == 4:
            evidence_sha256 = workspace_semantic_evidence_sha256(semantic_evidence)
            write_workspace_semantic_evidence(evidence_path, semantic_evidence)
        else:
            evidence_sha256 = semantic_verifier_evidence_sha256(semantic_evidence)
            write_semantic_verifier_evidence(evidence_path, semantic_evidence)
    except (FrozenPythonEnvironmentError, SemanticVerifierError) as exc:
        raise ToolAuditError(
            "semantic verifier could not run inside the trusted execution boundary",
            reason_code="SEMANTIC_VERIFIER_UNAVAILABLE",
            failure=_SEMANTIC_MECHANISM_FAILURE,
        ) from exc
    common = {
        "verifier_id": semantic_evidence.verifier_id,
        "evidence_sha256": evidence_sha256,
        "evidence_path": str(evidence_path),
        "passed": semantic_evidence.passed,
        "reason_codes": list(semantic_evidence.reason_codes),
        "required_commitment_ids": list(semantic_evidence.required_commitment_ids),
        "checked_commitment_ids": list(semantic_evidence.checked_commitment_ids),
    }
    if contract.tool.schema_version == 4:
        common["artifact_tree_sha256"] = semantic_evidence.artifact_tree_sha256
        common["artifact_manifest_sha256"] = semantic_evidence.artifact_manifest_sha256
    else:
        common["artifact_sha256"] = semantic_evidence.artifact_sha256
    return common


def _audit_workspace_execution(
    *,
    dest_root: Path,
    name: str,
    tool_dir: Path,
    manifest: dict[str, Any],
    task_id: str,
    run_id: str | None,
    input_path: Path,
    expected_dir: Path,
    executable: Path,
    timeout: int,
    evidence: dict[str, Any],
    project_root: Path | None,
    package_identity: str,
    runtime_environment_identity: str | None,
    required_schema_version: int,
    required_semantic_identity: dict[str, Any] | None,
    required_release_identity: ReleaseAuditTrustIdentityV1 | None,
) -> dict[str, Any]:
    """Execute and judge one v4 workspace without leaking directory truth."""
    from repoproof.domain.models import WorkspaceArtifactContractV1
    from repoproof.execution.workspace_bundle import (
        build_artifact_manifest,
        run_workspace_smoke,
        validate_workspace,
    )

    try:
        workspace_contract = WorkspaceArtifactContractV1.model_validate(manifest.get("workspace_contract"))
    except ValueError:
        evidence["workspace_contract"] = {"status": "invalid"}
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVIEW_REQUIRED,
            reason_code="WORKSPACE_CONTRACT_INVALID",
            reason="The installed workspace contract is invalid.",
            evidence=evidence,
            failure=_SEMANTIC_IDENTITY_FAILURE,
        )

    with tempfile.TemporaryDirectory(prefix="rp-fresh-workspace-") as temp:
        artifact_dir = Path(temp) / "artifact"
        try:
            result = subprocess.run(
                [
                    str(executable),
                    str(input_path.resolve()),
                    "--out-dir",
                    str(artifact_dir),
                ],
                cwd=tool_dir,
                capture_output=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            evidence["execution"] = {"status": type(exc).__name__}
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="FRESH_INPUT_EXECUTION_FAILED",
                reason="The workspace tool did not complete the fresh-input audit.",
                evidence=evidence,
                failure=_ADAPTER_EXECUTION_FAILURE,
            )
        evidence["execution"] = {
            "returncode": result.returncode,
            "stdout_sha256": _sha256(result.stdout),
            "stderr_sha256": _sha256(result.stderr),
        }
        if result.returncode != 0 or not artifact_dir.is_dir():
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="FRESH_INPUT_EXECUTION_FAILED",
                reason="The workspace tool failed to atomically create its output directory.",
                evidence=evidence,
                failure=_ADAPTER_EXECUTION_FAILURE,
            )

        try:
            post_dir, post_manifest, post_task_id, post_run_id = _tool_context(dest_root, name)
            post_package_identity = _package_control_identity(post_dir)
            (
                post_schema_version,
                post_semantic_identity,
                post_release_identity,
            ) = _managed_release_identity(
                dest_root=dest_root,
                name=name,
                tool_dir=post_dir,
                manifest=post_manifest,
                task_id=post_task_id,
                run_id=post_run_id,
            )
            post_runtime_identity = runtime_environment_sha256(post_dir)
            if (
                post_dir != tool_dir
                or post_task_id != task_id
                or post_run_id != run_id
                or post_package_identity != package_identity
                or post_schema_version != required_schema_version
                or post_semantic_identity != required_semantic_identity
                or post_release_identity != required_release_identity
                or post_runtime_identity != runtime_environment_identity
            ):
                raise ToolAuditError(
                    "package or runtime identity changed during workspace audit",
                    failure=_PACKAGE_IDENTITY_FAILURE,
                )
        except (OSError, ToolAuditError, ToolPathError, ValueError) as exc:
            evidence["post_execution_identity"] = {
                "status": "changed",
                "diagnostic_sha256": _sha256(str(exc).encode("utf-8")),
            }
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVIEW_REQUIRED,
                reason_code="PACKAGE_IDENTITY_CHANGED_DURING_AUDIT",
                reason="The managed package changed during workspace execution.",
                evidence=evidence,
                failure=_PACKAGE_IDENTITY_FAILURE,
            )

        structure = validate_workspace(artifact_dir, workspace_contract)
        if not structure.ok:
            evidence["workspace_structure"] = {
                "ok": False,
                "reason_codes": list(structure.reason_codes),
            }
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="WORKSPACE_CONTRACT_MISMATCH",
                reason="The fresh workspace violated its frozen structural contract.",
                evidence=evidence,
                failure=_OUTPUT_CONTRACT_CONFLICT_FAILURE,
            )
        actual_manifest = build_artifact_manifest(artifact_dir, limits=workspace_contract.limits)
        expected_manifest = build_artifact_manifest(expected_dir, limits=workspace_contract.limits)
        actual_manifest_sha = _canonical_sha256(actual_manifest.model_dump(mode="json"))
        evidence["execution"].update(
            {
                "artifact_tree_sha256": actual_manifest.tree_sha256,
                "artifact_manifest_sha256": actual_manifest_sha,
                "file_count": len(actual_manifest.entries),
            }
        )
        evidence["workspace_structure"] = {"ok": True}
        from repoproof.adoption.delivery.portable_workspace_runtime import golden_tree_sha256

        # Equality for acceptance is the golden identity (zip containers by
        # their members); the raw tree hashes above stay in the evidence.
        reference_tree_match = (
            golden_tree_sha256(artifact_dir) == golden_tree_sha256(expected_dir)
        )
        evidence["reference_tree_match"] = reference_tree_match
        evidence["expected_tree_sha256"] = expected_manifest.tree_sha256

        if workspace_contract.runnable:
            runtime = run_workspace_smoke(artifact_dir, workspace_contract)
            evidence["workspace_runtime"] = runtime.model_dump(mode="json")
            if not runtime.passed:
                isolation_unavailable = (
                    "WORKSPACE_SMOKE_ISOLATION_UNAVAILABLE"
                    in runtime.reason_codes
                )
                return _record_audit_decision(
                    dest_root,
                    name=name,
                    task_id=task_id,
                    run_id=run_id,
                    decision=REVIEW_REQUIRED if isolation_unavailable else REVOKED,
                    reason_code=(
                        "WORKSPACE_SMOKE_ISOLATION_UNAVAILABLE"
                        if isolation_unavailable
                        else "WORKSPACE_RUNTIME_FAILED"
                    ),
                    reason=(
                        "The reviewed offline runtime boundary was unavailable."
                        if isolation_unavailable
                        else "The frozen workspace smoke command did not complete safely."
                    ),
                    evidence=evidence,
                    failure=(
                        _SEMANTIC_MECHANISM_FAILURE
                        if isolation_unavailable
                        else _ADAPTER_EXECUTION_FAILURE
                    ),
                )

        # A workspace reference is an independent implementation, not a hidden
        # byte-format contract.  Both the confirmed reference artifact and the
        # delivered artifact must satisfy the same frozen semantic verifier.
        # Only then may incidental wording/formatting bytes differ.  This keeps
        # the reference meaningful without introducing undeclared presentation
        # rules ahead of the semantic gate.
        try:
            reference_semantic = _run_required_semantic_audit(
                project_root=project_root,
                tool_dir=tool_dir,
                manifest=manifest,
                task_id=task_id,
                input_path=input_path,
                artifact=expected_dir,
                required_schema_version=required_schema_version,
                required_semantic_identity=required_semantic_identity,
                required_release_identity=required_release_identity,
            )
        except ToolAuditError as exc:
            mechanism_code = exc.reason_code or "SEMANTIC_VERIFIER_UNAVAILABLE"
            evidence["reference_semantic_verifier"] = {
                "passed": False,
                "reason_codes": [mechanism_code],
            }
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVIEW_REQUIRED,
                reason_code=mechanism_code,
                reason="The frozen verifier could not validate the reference workspace.",
                evidence=evidence,
                failure=exc.failure,
            )
        if reference_semantic is None:
            raise ToolAuditError(
                "ToolSpec v4 reference semantic audit returned no evidence",
                failure=_SEMANTIC_MECHANISM_FAILURE,
            )
        evidence["reference_semantic_verifier"] = reference_semantic
        if semantic_mechanism_failure(reference_semantic["reason_codes"]):
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVIEW_REQUIRED,
                reason_code="SEMANTIC_VERIFIER_UNAVAILABLE",
                reason="Reference semantic controls did not produce trustworthy evidence.",
                evidence=evidence,
                failure=_SEMANTIC_MECHANISM_FAILURE,
            )
        if reference_semantic["passed"] is not True:
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVIEW_REQUIRED,
                reason_code="REFERENCE_SEMANTIC_MISMATCH",
                reason="The confirmed reference workspace failed frozen semantics.",
                evidence=evidence,
                failure=_SEMANTIC_ORACLE_CONFLICT_FAILURE,
            )

        try:
            semantic = _run_required_semantic_audit(
                project_root=project_root,
                tool_dir=tool_dir,
                manifest=manifest,
                task_id=task_id,
                input_path=input_path,
                artifact=artifact_dir,
                required_schema_version=required_schema_version,
                required_semantic_identity=required_semantic_identity,
                required_release_identity=required_release_identity,
            )
        except ToolAuditError as exc:
            mechanism_code = exc.reason_code or "SEMANTIC_VERIFIER_UNAVAILABLE"
            evidence["semantic_verifier"] = {
                "passed": False,
                "reason_codes": [mechanism_code],
            }
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVIEW_REQUIRED,
                reason_code=mechanism_code,
                reason="The frozen workspace semantic verifier was unavailable.",
                evidence=evidence,
                failure=exc.failure,
            )
        if semantic is None:
            raise ToolAuditError(
                "ToolSpec v4 semantic audit unexpectedly returned no evidence",
                failure=_SEMANTIC_MECHANISM_FAILURE,
            )
        evidence["semantic_verifier"] = semantic
        if semantic_mechanism_failure(semantic["reason_codes"]):
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVIEW_REQUIRED,
                reason_code="SEMANTIC_VERIFIER_UNAVAILABLE",
                reason="Workspace semantic controls did not produce trustworthy evidence.",
                evidence=evidence,
                failure=_SEMANTIC_MECHANISM_FAILURE,
            )
        if semantic["passed"] is not True:
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="SEMANTIC_VERIFIER_MISMATCH",
                reason="The fresh workspace failed frozen semantic verification.",
                evidence=evidence,
                failure=_SEMANTIC_ORACLE_CONFLICT_FAILURE,
            )
        pass_reason = (
            "FRESH_INPUT_PASS"
            if reference_tree_match
            else "FRESH_INPUT_SEMANTIC_PASS"
        )
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=ACTIVE,
            reason_code=pass_reason,
            reason=(
                "Fresh workspace structure, runtime and frozen semantics passed; "
                + (
                    "the reference tree also matched exactly."
                    if reference_tree_match
                    else "reference and delivered presentation bytes differed without a semantic mismatch."
                )
            ),
            evidence=evidence,
            failure=None,
        )


def _audit_tool_locked(
    dest_root: Path,
    name: str,
    *,
    input_path: Path,
    expected_file: Path,
    expected_task_id: str | None = None,
    project_root: Path | None = None,
    run_build: bool = False,
    timeout: int = 300,
) -> dict[str, Any]:
    """Run one fresh-input audit and append ACTIVE or REVOKED.

    No input, stdout, expected output, or stderr body is persisted.  The ledger
    receives only a digest of their hashes and the deterministic outcome.
    """

    dest_root = Path(dest_root)
    all_decisions = load_release_decisions(dest_root)  # validate before executing anything

    # A Studio candidate is truth for one frozen task, not for the stable tool
    # name.  The install lock held by ``audit_tool`` makes this registry check
    # atomic with package execution: if an upgrade won the lock after candidate
    # generation, the old candidate cannot activate (or revoke) the new task.
    # task_id is sufficient here because registration forbids changing a
    # same-task run/contract identity in place.
    if expected_task_id is not None:
        expected_task_id = str(expected_task_id).strip()
        try:
            validate_tool_task_id(name, expected_task_id)
            # Import lazily: tool_registry owns the registry parser and imports
            # release-state helpers from this module at module initialization.
            from repoproof.runner.tool_registry import load_registry

            registry = load_registry(dest_root)
            current_entry = registry["tools"].get(name)
            current_task_id = current_entry.get("task_id") if isinstance(current_entry, dict) else None
        except (KeyError, OSError, ToolPathError, TypeError, ValueError) as exc:
            raise ToolAuditError(
                f"{name}: 无法确认 registry 当前 task，拒绝执行 Fresh audit",
                reason_code="AUDIT_TASK_IDENTITY_MISMATCH",
                failure=_STALE_AUDIT_CANDIDATE_FAILURE,
            ) from exc
        if current_task_id != expected_task_id:
            raise ToolAuditError(
                f"{name}: Fresh audit 绑定 {expected_task_id}，但 registry 当前为 "
                f"{current_task_id or '未登记'}；候选已失效",
                reason_code="AUDIT_TASK_IDENTITY_MISMATCH",
                failure=_STALE_AUDIT_CANDIDATE_FAILURE,
            )

    tool_dir, manifest, task_id, run_id = _tool_context(dest_root, name)
    if expected_task_id is not None and task_id != expected_task_id:
        raise ToolAuditError(
            f"{name}: registry 与当前 package task identity 不一致，拒绝执行 Fresh audit",
            reason_code="AUDIT_TASK_IDENTITY_MISMATCH",
            failure=_STALE_AUDIT_CANDIDATE_FAILURE,
        )
    (
        required_schema_version,
        required_semantic_identity,
        required_release_identity,
    ) = _managed_release_identity(
        dest_root=dest_root,
        name=name,
        tool_dir=tool_dir,
        manifest=manifest,
        task_id=task_id,
        run_id=run_id,
    )
    package_identity = _package_control_identity(tool_dir)
    historical_verdict = (manifest.get("verification") or {}).get("verdict")
    if not is_historical_tool_ready(historical_verdict):
        raise ToolAuditError(
            f"{name}: historical_verdict={historical_verdict!r} 不是已验证工具，不能运营审核",
            failure=_PACKAGE_IDENTITY_FAILURE,
        )

    terminal_contract_reasons = {
        "OUTPUT_CONTRACT_MISMATCH",
        "WORKSPACE_CONTRACT_MISMATCH",
        "SEMANTIC_VERIFIER_MISMATCH",
    }
    if any(
        row["tool"] == name
        and row["decision"] == REVOKED
        and row["reason_code"] in terminal_contract_reasons
        and row["task_id"] == task_id
        for row in all_decisions
    ):
        raise ToolAuditError(
            f"{name}: 当前 task 因冻结合同/独立语义证据冲突已撤回；必须发布新 task version，不能原地恢复",
            failure=_TERMINAL_CONTRACT_FAILURE,
        )
    current = next(
        (row for row in reversed(all_decisions) if row["tool"] == name),
        None,
    )
    if (
        current is not None
        and current["task_id"] == task_id
        and current["decision"] == REVOKED
        and current["reason_code"] == "USER_WITHDRAWAL"
    ):
        raise ToolAuditError(
            f"{name}: 当前 task 已由用户撤回；普通 audit 无权恢复，需未来显式 restore 决策",
            failure=_WITHDRAWN_TASK_FAILURE,
        )

    input_path = Path(input_path)
    expected_file = Path(expected_file)
    workspace_profile = required_schema_version == 4
    if input_path.is_symlink() or not (input_path.is_file() or (workspace_profile and input_path.is_dir())):
        raise ToolAuditError(
            f"audit input 不存在或类型不受支持: {input_path}",
            failure=_AUDIT_INPUT_FAILURE,
        )
    if expected_file.is_symlink() or not (expected_file.is_dir() if workspace_profile else expected_file.is_file()):
        raise ToolAuditError(
            f"expected artifact 不存在或类型不受支持: {expected_file}",
            failure=_AUDIT_INPUT_FAILURE,
        )
    if _inside(input_path, tool_dir):
        raise ToolAuditError(
            "audit input 位于工具包内，不满足 fresh non-example 要求",
            failure=_AUDIT_INPUT_FAILURE,
        )
    if _inside(expected_file, tool_dir):
        raise ToolAuditError(
            "expected file 位于工具包内，不能直接复用旧真值",
            failure=_AUDIT_INPUT_FAILURE,
        )
    if timeout <= 0:
        raise ToolAuditError("timeout 必须大于 0", failure=_AUDIT_INPUT_FAILURE)

    if workspace_profile:
        from repoproof.execution.workspace_bundle import (
            build_artifact_manifest,
            identify_input_path,
        )

        input_identity = identify_input_path(input_path)
        expected_manifest = build_artifact_manifest(expected_file)
        public_identities = _public_fixture_path_identities(tool_dir)
        if input_identity.sha256 in public_identities:
            raise ToolAuditError(
                "audit input 与工具包公开 fixture 相同，不满足 fresh non-example 要求",
                failure=_AUDIT_INPUT_FAILURE,
            )
        if expected_manifest.tree_sha256 in public_identities:
            raise ToolAuditError(
                "expected workspace 与公开 fixture 相同，不能复用旧真值",
                failure=_AUDIT_INPUT_FAILURE,
            )
        input_sha256 = input_identity.sha256
        expected_sha256 = expected_manifest.tree_sha256
    else:
        expected = expected_file.read_bytes()
        input_bytes = input_path.read_bytes()
        public_hashes = _public_fixture_hashes(tool_dir)
        if _sha256(input_bytes) in public_hashes:
            raise ToolAuditError(
                "audit input 与工具包公开 fixture 相同，不满足 fresh non-example 要求",
                failure=_AUDIT_INPUT_FAILURE,
            )
        if _sha256(expected) in public_hashes:
            raise ToolAuditError(
                "expected file 与工具包公开 fixture 相同，不能复用旧真值",
                failure=_AUDIT_INPUT_FAILURE,
            )
        input_sha256 = _sha256(input_bytes)
        expected_sha256 = _sha256(expected)
    evidence: dict[str, Any] = {
        "schema_version": 2 if workspace_profile else 1,
        "tool": name,
        "task_id": task_id,
        "run_id": run_id,
        "historical_verdict": historical_verdict,
        "input_sha256": input_sha256,
        "expected_sha256": expected_sha256,
        "artifact_kind": "directory" if workspace_profile else "stdout",
        "build_requested": run_build,
    }

    if run_build:
        build_script = tool_dir / "build.sh"
        if not build_script.is_file():
            evidence["build"] = {"status": "missing"}
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="BUILD_FAILED",
                reason="Fresh-input audit requested a rebuild, but build.sh is missing.",
                evidence=evidence,
                failure=_BUILD_FAILURE,
            )
        try:
            built = subprocess.run(["bash", str(build_script)], cwd=tool_dir, capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            evidence["build"] = {"status": type(exc).__name__}
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="BUILD_FAILED",
                reason="Fresh-input audit rebuild did not complete successfully.",
                evidence=evidence,
                failure=_BUILD_FAILURE,
            )
        evidence["build"] = {
            "returncode": built.returncode,
            "stdout_sha256": _sha256(built.stdout),
            "stderr_sha256": _sha256(built.stderr),
        }
        if built.returncode != 0:
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="BUILD_FAILED",
                reason="Fresh-input audit rebuild returned a non-zero exit code.",
                evidence=evidence,
                failure=_BUILD_FAILURE,
            )

        # build.sh is allowed to reconstruct the opaque top-level .venv, but
        # it must not replace a managed launcher with a symlink/special file or
        # rewrite the package identity that this audit is about.  Revalidate
        # after the subprocess and before resolving/executing bin/<name>.
        try:
            rebuilt_dir, rebuilt_manifest, rebuilt_task_id, rebuilt_run_id = _tool_context(dest_root, name)
            rebuilt_identity = _package_control_identity(rebuilt_dir)
            if (
                rebuilt_dir != tool_dir
                or rebuilt_task_id != task_id
                or rebuilt_run_id != run_id
                or rebuilt_identity != package_identity
            ):
                raise ToolAuditError(
                    "build 后 package identity 发生变化",
                    failure=_PACKAGE_IDENTITY_FAILURE,
                )
        except (OSError, ToolAuditError, ToolPathError, UnicodeError, ValueError) as exc:
            evidence["build_postcheck"] = {
                "status": "invalid-package",
                "diagnostic_sha256": _sha256(str(exc).encode("utf-8")),
            }
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="BUILD_FAILED",
                reason="Fresh-input audit rebuild left an unsafe or changed package identity.",
                evidence=evidence,
                failure=_BUILD_FAILURE,
            )
        tool_dir = rebuilt_dir
        manifest = rebuilt_manifest

    if required_schema_version >= 3:
        try:
            runtime_environment_identity = runtime_environment_sha256(tool_dir)
        except (OSError, ToolPackageIdentityError) as exc:
            evidence["runtime_environment"] = {
                "status": "invalid",
                "diagnostic_sha256": _sha256(str(exc).encode("utf-8")),
            }
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVIEW_REQUIRED,
                reason_code="RUNTIME_ENVIRONMENT_IDENTITY_INVALID",
                reason="The runtime environment could not be given a safe identity.",
                evidence=evidence,
                failure=_PACKAGE_IDENTITY_FAILURE,
            )
        evidence["runtime_environment_sha256"] = runtime_environment_identity
    else:
        runtime_environment_identity = None

    executable = tool_dir / "bin" / name
    executable_problem = "missing-executable"
    try:
        executable_metadata = executable.lstat()
    except FileNotFoundError:
        executable_metadata = None
    except OSError as exc:
        executable_problem = type(exc).__name__
        executable_metadata = None
    if executable_metadata is not None and not stat.S_ISREG(executable_metadata.st_mode):
        executable_problem = "unsafe-executable"
    if executable_metadata is None or executable_problem == "unsafe-executable":
        evidence["execution"] = {"status": executable_problem}
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="FRESH_INPUT_EXECUTION_FAILED",
            reason="Tool executable is missing.",
            evidence=evidence,
            failure=_PACKAGE_IDENTITY_FAILURE,
        )
    if workspace_profile:
        return _audit_workspace_execution(
            dest_root=dest_root,
            name=name,
            tool_dir=tool_dir,
            manifest=manifest,
            task_id=task_id,
            run_id=run_id,
            input_path=input_path,
            expected_dir=expected_file,
            executable=executable,
            timeout=timeout,
            evidence=evidence,
            project_root=project_root,
            package_identity=package_identity,
            runtime_environment_identity=runtime_environment_identity,
            required_schema_version=required_schema_version,
            required_semantic_identity=required_semantic_identity,
            required_release_identity=required_release_identity,
        )
    try:
        result = subprocess.run(
            [str(executable), str(input_path.resolve())],
            cwd=tool_dir,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        evidence["execution"] = {"status": type(exc).__name__}
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="FRESH_INPUT_EXECUTION_FAILED",
            reason="Tool did not complete the fresh-input audit.",
            evidence=evidence,
            failure=_ADAPTER_EXECUTION_FAILURE,
        )

    evidence["execution"] = {
        "returncode": result.returncode,
        "stdout_sha256": _sha256(result.stdout),
        "stderr_sha256": _sha256(result.stderr),
    }
    if required_schema_version >= 3:
        try:
            post_dir, post_manifest, post_task_id, post_run_id = _tool_context(dest_root, name)
            post_package_identity = _package_control_identity(post_dir)
            (
                post_schema_version,
                post_semantic_identity,
                post_release_identity,
            ) = _managed_release_identity(
                dest_root=dest_root,
                name=name,
                tool_dir=post_dir,
                manifest=post_manifest,
                task_id=post_task_id,
                run_id=post_run_id,
            )
            post_runtime_identity = runtime_environment_sha256(post_dir)
            if (
                post_dir != tool_dir
                or post_task_id != task_id
                or post_run_id != run_id
                or post_package_identity != package_identity
                or post_schema_version != required_schema_version
                or post_semantic_identity != required_semantic_identity
                or post_release_identity != required_release_identity
                or post_runtime_identity != runtime_environment_identity
            ):
                raise ToolAuditError(
                    "package or runtime identity changed during audit execution",
                    reason_code="PACKAGE_IDENTITY_CHANGED_DURING_AUDIT",
                    failure=_PACKAGE_IDENTITY_FAILURE,
                )
        except (OSError, ToolAuditError, ToolPathError, ValueError) as exc:
            evidence["post_execution_identity"] = {
                "status": "changed",
                "diagnostic_sha256": _sha256(str(exc).encode("utf-8")),
            }
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVIEW_REQUIRED,
                reason_code="PACKAGE_IDENTITY_CHANGED_DURING_AUDIT",
                reason=("The managed package or runtime environment changed while the fresh audit was executing."),
                evidence=evidence,
                failure=_PACKAGE_IDENTITY_FAILURE,
            )
    if result.returncode != 0:
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="FRESH_INPUT_EXECUTION_FAILED",
            reason="Tool returned a non-zero exit code for the fresh input.",
            evidence=evidence,
            failure=_ADAPTER_EXECUTION_FAILURE,
        )
    # 判据取自**冻结合同声明的 root_type**,并且与合同自己的验收测试
    # 共用同一份实现(verification.output_match)—— 两把尺子的病根见
    # LESSONS #57。
    from repoproof.verification.output_match import compare_output

    _root_type = str(
        (((manifest.get("interface") or {}).get("output") or {}).get("contract") or {}).get("root_type") or "text"
    )
    stdout_matches, _mode = compare_output(
        result.stdout.decode("utf-8", errors="replace"),
        expected.decode("utf-8", errors="replace"),
        root_type=_root_type,
    )
    evidence["execution"]["comparison"] = _mode
    evidence["execution"]["root_type"] = _root_type
    if not stdout_matches:
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="FRESH_INPUT_MISMATCH",
            reason="Tool stdout did not exactly match the operator-provided expected file.",
            evidence=evidence,
            failure=_REFERENCE_MISMATCH_FAILURE,
        )

    contract_errors = _output_contract_errors(manifest, result.stdout)
    if contract_errors:
        # Error strings are stable structural diagnostics and never contain stdout.
        evidence["output_contract_errors"] = contract_errors
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="OUTPUT_CONTRACT_MISMATCH",
            reason="Fresh output matched the expected file but violated the declared output contract.",
            evidence=evidence,
            failure=_OUTPUT_CONTRACT_CONFLICT_FAILURE,
        )

    try:
        semantic = _run_required_semantic_audit(
            project_root=project_root,
            tool_dir=tool_dir,
            manifest=manifest,
            task_id=task_id,
            input_path=input_path,
            artifact=result.stdout,
            required_schema_version=required_schema_version,
            required_semantic_identity=required_semantic_identity,
            required_release_identity=required_release_identity,
        )
    except ToolAuditError as exc:
        # A broken or unavailable judge is not evidence that the delivered
        # capability is semantically wrong.  It *is* evidence that a previous
        # ACTIVE decision can no longer be relied on, so the append-only state
        # must move to REVIEW_REQUIRED instead of leaving stale ACTIVE behind.
        mechanism_code = exc.reason_code or "SEMANTIC_VERIFIER_UNAVAILABLE"
        evidence["semantic_verifier"] = {
            "passed": False,
            "reason_codes": [mechanism_code],
        }
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVIEW_REQUIRED,
            reason_code=mechanism_code,
            reason=(
                "The frozen semantic verification mechanism or its evidence "
                "context was unavailable; no product-semantic verdict was made."
            ),
            evidence=evidence,
            failure=exc.failure,
        )
    if semantic is not None:
        evidence["semantic_verifier"] = semantic
        mechanism_failure = semantic_mechanism_failure(semantic["reason_codes"])
        if mechanism_failure:
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVIEW_REQUIRED,
                reason_code="SEMANTIC_VERIFIER_UNAVAILABLE",
                reason=(
                    "The frozen semantic verifier did not produce complete "
                    "trustworthy runtime evidence; no product-semantic verdict "
                    "was made."
                ),
                evidence=evidence,
                failure=_SEMANTIC_MECHANISM_FAILURE,
            )
        if semantic["passed"] is not True:
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="SEMANTIC_VERIFIER_MISMATCH",
                reason=(
                    "Fresh output matched the reference bytes and representation "
                    "contract but failed the frozen independent semantic verifier."
                ),
                evidence=evidence,
                failure=_SEMANTIC_ORACLE_CONFLICT_FAILURE,
            )

    return _record_audit_decision(
        dest_root,
        name=name,
        task_id=task_id,
        run_id=run_id,
        decision=ACTIVE,
        reason_code="FRESH_INPUT_PASS",
        reason="Fresh-input execution matched the expected file and declared output contract.",
        evidence=evidence,
        failure=None,
    )


def audit_tool(
    dest_root: Path,
    name: str,
    *,
    input_path: Path,
    expected_file: Path,
    expected_task_id: str | None = None,
    project_root: Path | None = None,
    run_build: bool = False,
    timeout: int = 300,
) -> dict[str, Any]:
    """Serialize audit against withdrawal and package upgrades.

    ``expected_task_id`` binds pre-generated fresh truth to its frozen task.
    Legacy/manual callers may omit it and explicitly audit whichever task is
    current, while managed Studio journeys always provide it.
    """

    with tool_install_lock(dest_root):
        with release_decision_lock(dest_root):
            return _audit_tool_locked(
                dest_root,
                name,
                input_path=input_path,
                expected_file=expected_file,
                expected_task_id=expected_task_id,
                project_root=project_root,
                run_build=run_build,
                timeout=timeout,
            )


def _migration_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return _utc_now()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ReleaseLedgerError(f"audit audited_at 非法: {value!r}") from exc
        return f"{value}T00:00:00Z"
    if not _validate_rfc3339_utc(value):
        raise ReleaseLedgerError(f"audit audited_at 非 RFC3339 UTC: {value!r}")
    return value


def import_audit_decisions(
    audits_path: Path,
    dest_root: Path,
    *,
    actor: str = "migration",
) -> dict[str, int]:
    """Import audits while preventing concurrent package replacement."""

    with tool_install_lock(dest_root):
        return _import_audit_decisions_install_locked(
            audits_path,
            dest_root,
            actor=actor,
        )


def _import_audit_decisions_install_locked(
    audits_path: Path,
    dest_root: Path,
    *,
    actor: str = "migration",
) -> dict[str, int]:
    """Import append-only M4 operator audits as idempotent release decisions.

    The evidence digest is the SHA-256 of the exact JSON record bytes (without
    its line ending).  The source file is fully validated before any append.
    """

    if actor not in VALID_ACTORS:
        raise ReleaseLedgerError(f"actor 只允许 {sorted(VALID_ACTORS)}")
    audits_path = Path(audits_path)
    try:
        raw_lines = audits_path.read_bytes().splitlines()
    except OSError as exc:
        raise ReleaseLedgerError(f"无法读取 audit ledger {audits_path}: {exc}") from exc
    if not raw_lines:
        raise ReleaseLedgerError(f"audit ledger 为空: {audits_path}")

    prepared: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.strip():
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 空行")
        try:
            audit = _strict_json_loads(raw_line)
        except (UnicodeError, ValueError) as exc:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 损坏 JSON: {exc}") from exc
        if not isinstance(audit, dict):
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: audit 必须为 JSON object")
        tool = audit.get("tool")
        task_id = audit.get("task_id")
        if not isinstance(tool, str) or not tool or not isinstance(task_id, str):
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: audit 缺 tool/task_id")

        outcome = parse_operator_audit_outcome(audit, where=f"{audits_path}:{line_no}")
        decision = ACTIVE if outcome else REVOKED
        verdict = audit.get("verdict")
        ok = audit.get("ok")

        if audit.get("mode") != "fresh-input-cli":
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: mode 必须为 fresh-input-cli")
        if audit.get("input_is_example") is not False:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: input_is_example 必须显式为 false")

        # Legacy notes are human prose, not typed control data.  Inferring a
        # failure owner from words such as "contract" or "oracle" made the
        # migration result depend on language and phrasing.  Preserve only the
        # outcome the legacy row actually proves; current Product audits carry
        # structured AuditFailureMetadata at the producer boundary.
        reason_code = "MIGRATED_FRESH_INPUT_PASS" if decision == ACTIVE else "MIGRATED_AUDIT_FAIL"
        try:
            tool_dir = canonical_tool_path(dest_root, tool)
            ensure_safe_package_tree(tool_dir)
        except ToolPathError as exc:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: {exc}") from exc
        manifest_path = tool_dir / "tool.json"
        if not manifest_path.is_file():
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 迁移目标 manifest 不存在 {manifest_path}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReleaseLedgerError(f"无法读取迁移目标 manifest {manifest_path}: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 迁移目标 manifest 必须为 JSON object")
        if manifest.get("name") != tool:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: audit tool 与 manifest name 不一致")
        historical_verdict = (manifest.get("verification") or {}).get("verdict")
        if not is_historical_tool_ready(historical_verdict):
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 迁移目标不是历史 VERIFIED_TOOL_READY")
        provenance_path = tool_dir / "evidence" / "provenance.json"
        if not provenance_path.is_file():
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 迁移目标缺 provenance {provenance_path}")
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReleaseLedgerError(f"无法读取迁移目标 provenance {provenance_path}: {exc}") from exc
        if not isinstance(provenance, dict):
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 迁移目标 provenance 必须为 JSON object")
        from repoproof.runner.tool_registry import validate_contract_schema_version

        try:
            contract_schema_version = validate_contract_schema_version(manifest)
        except ValueError as exc:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 迁移目标 contract schema 非法") from exc
        if contract_schema_version >= 3 and decision == ACTIVE:
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: ToolSpec v3 不接受缺少独立语义证据的 "
                "legacy ACTIVE 迁移；请运行当前 Fresh audit"
            )
        if provenance.get("task_id") != task_id:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: audit task_id 与 provenance 不一致")
        try:
            validate_tool_task_id(tool, task_id)
        except ToolPathError as exc:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: {exc}") from exc
        if provenance.get("tool") != tool:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: provenance tool 与 manifest name 不一致")
        verification = manifest.get("verification") or {}
        run_id = verification.get("run_id")
        if (
            not isinstance(run_id, str)
            or not run_id
            or provenance.get("run_id") != run_id
            or provenance.get("tool_contract_sha256") != verification.get("contract_sha256")
        ):
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: manifest/provenance identity 不一致")
        prepared.append(
            {
                "tool": tool,
                "task_id": task_id,
                "run_id": run_id,
                "decision": decision,
                "reason_code": reason_code,
                "reason": f"Migrated operator fresh-input audit: {verdict or ('PASS' if ok else 'FAIL')}.",
                "evidence_sha256": _sha256(raw_line),
                "decided_at": _migration_time(audit.get("audited_at")),
                "actor": actor,
            }
        )

    # Validate every derived row before the first append so a malformed later
    # source record cannot leave a partially migrated decision ledger.
    for line_no, row in enumerate(prepared, start=1):
        _validate_decision(
            {"schema_version": 1, **row},
            where=f"{audits_path}:{line_no} derived release decision",
        )

    with release_decision_lock(dest_root):
        existing = load_release_decisions(dest_root)
        seen = {(row["evidence_sha256"], row["tool"], row["decision"]) for row in existing}
        latest_by_tool: dict[str, dict[str, Any]] = {}
        migrated_failure_tasks: set[tuple[str, str]] = set()
        for existing_row in existing:
            latest_by_tool[existing_row["tool"]] = existing_row
            if existing_row["actor"] == "migration" and existing_row["decision"] == REVOKED:
                migrated_failure_tasks.add((existing_row["tool"], existing_row["task_id"]))
        counts = {"imported": 0, "skipped": 0, "active": 0, "revoked": 0}
        for row in prepared:
            key = (row["evidence_sha256"], row["tool"], row["decision"])
            if key in seen:
                counts["skipped"] += 1
                continue
            current = latest_by_tool.get(row["tool"])
            if (row["decision"] == ACTIVE and (row["tool"], row["task_id"]) in migrated_failure_tasks) or (
                current is not None
                and (
                    current["task_id"] != row["task_id"]
                    or (current["actor"] != "migration" and current["reason_code"] != "INITIAL_EXPORT_REVIEW_REQUIRED")
                )
            ):
                # A historical migration may seed an unreviewed export, but
                # it must never supersede a newer task or explicit human /
                # operator decision merely because its line appends later.
                counts["skipped"] += 1
                continue
            _append_release_decision_unlocked(dest_root, **row)
            seen.add(key)
            latest_by_tool[row["tool"]] = {"schema_version": 1, **row}
            if row["decision"] == REVOKED:
                migrated_failure_tasks.add((row["tool"], row["task_id"]))
            counts["imported"] += 1
            counts["active" if row["decision"] == ACTIVE else "revoked"] += 1
        return counts
