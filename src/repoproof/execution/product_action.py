"""Structured Product Mode action outcomes.

The durable worker state answers only whether a process ran and produced its
declared artifact.  This module records the semantic outcome emitted by the
Product CLI so Studio never has to infer a pipeline verdict from log text.
Operational status in this document is historical context only; callers must
always re-read the Core registry and append-only release ledger for the current
status.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from repoproof.execution.audit_failure import (
    AuditFailureClass,
    AuditFailureStage,
    AuditRecommendedActionCode,
    AuditRetryPolicy,
)
from repoproof.execution.core_execution import atomic_write_json

ACTION_RESULT_SCHEMA_VERSION = 2
MAX_ACTION_RESULT_BYTES = 1024 * 1024

ProductFailureStage = AuditFailureStage | Literal["INTAKE", "DRAFTING"]
ProductFailureClass = AuditFailureClass | Literal[
    "PROVIDER_TRANSPORT",
    "PROVIDER_CAPABILITY",
    "HARNESS_CONFIGURATION",
    "MODEL_OUTPUT_INVALID",
]
ProductRetryPolicy = AuditRetryPolicy | Literal[
    "RETRY_AFTER_PROVIDER_RECOVERY",
    "RETRY_AFTER_CONFIGURATION_REPAIR",
]
ProductRecommendedActionCode = AuditRecommendedActionCode | Literal[
    "RETRY_DRAFT_AFTER_PROVIDER_RECOVERY",
    "CONFIGURE_STRUCTURED_DRAFTER",
    "REPAIR_DRAFTER_CONFIGURATION",
    "REVIEW_INVALID_DRAFTER_OUTPUT",
]

_DRAFTER_FAILURES: dict[
    str,
    tuple[
        str,
        str,
        ProductFailureClass,
        ProductRetryPolicy,
        bool,
        ProductRecommendedActionCode,
        str,
        str,
    ],
] = {
    "DRAFTER_TIMEOUT": (
        "DRAFTER_TIMEOUT",
        "EXTERNAL",
        "PROVIDER_TRANSPORT",
        "RETRY_AFTER_PROVIDER_RECOVERY",
        False,
        "RETRY_DRAFT_AFTER_PROVIDER_RECOVERY",
        "STOP_HARNESS_OR_EXTERNAL",
        "网关恢复稳定后重新创建任务；本次未进入 Agent 或 repair。",
    ),
    "DRAFTER_CONNECTIVITY_ERROR": (
        "DRAFTER_CONNECTIVITY_ERROR",
        "EXTERNAL",
        "PROVIDER_TRANSPORT",
        "RETRY_AFTER_PROVIDER_RECOVERY",
        False,
        "RETRY_DRAFT_AFTER_PROVIDER_RECOVERY",
        "STOP_HARNESS_OR_EXTERNAL",
        "恢复网关连接后重新创建任务；本次未进入 Agent 或 repair。",
    ),
    "DRAFTER_STRUCTURED_OUTPUT_UNSUPPORTED": (
        "DRAFTER_STRUCTURED_OUTPUT_UNSUPPORTED",
        "EXTERNAL",
        "PROVIDER_CAPABILITY",
        "RETRY_AFTER_CONFIGURATION_REPAIR",
        False,
        "CONFIGURE_STRUCTURED_DRAFTER",
        "STOP_HARNESS_OR_EXTERNAL",
        "为网关启用 JSON Schema structured output，或显式选择支持同一 schema 的起草通道。",
    ),
    "DRAFTER_TIMEOUT_CONFIG_INVALID": (
        "DRAFTER_TIMEOUT_CONFIG_INVALID",
        "HARNESS",
        "HARNESS_CONFIGURATION",
        "RETRY_AFTER_CONFIGURATION_REPAIR",
        False,
        "REPAIR_DRAFTER_CONFIGURATION",
        "STOP_HARNESS_OR_EXTERNAL",
        "修正起草超时配置后重新创建任务；本次未进入 Agent 或 repair。",
    ),
}

_INVALID_MODEL_OUTPUT_FAILURE: tuple[
    str,
    str,
    ProductFailureClass,
    ProductRetryPolicy,
    bool,
    ProductRecommendedActionCode,
    str,
    str,
] = (
    "DRAFTER_INVALID_MODEL_OUTPUT",
    "EXTERNAL",
    "MODEL_OUTPUT_INVALID",
    "REVIEW_REQUIRED",
    False,
    "REVIEW_INVALID_DRAFTER_OUTPUT",
    "STOP_NEEDS_HUMAN",
    "模型在一次起草和一次公开投影修正后仍未满足合同协议；已停止自动重试。"
    "请检查需求是否可由当前交付 profile 表达，再创建任务。",
)


def _typed_drafter_failure(
    draft_error: str,
) -> tuple[
    str,
    str,
    ProductFailureClass,
    ProductRetryPolicy,
    bool,
    ProductRecommendedActionCode,
    str,
    str,
] | None:
    """Project stable drafter semantics without exposing private diagnostics."""

    known = _DRAFTER_FAILURES.get(draft_error)
    if known is not None:
        return known
    if (
        draft_error.endswith(":INVALID_MODEL_OUTPUT")
        or draft_error.startswith("tool-draft:")
    ):
        return _INVALID_MODEL_OUTPUT_FAILURE
    return None


def _invalid_model_output_detail(draft_error: str) -> str | None:
    """Project only a stable Core reason token, never provider/model text."""

    prefix = "tool-draft:INVALID_MODEL_OUTPUT:"
    if not draft_error.startswith(prefix):
        return None
    detail = draft_error.removeprefix(prefix)
    if (
        1 <= len(detail) <= 96
        and detail[0].isalpha()
        and all(char.isupper() or char.isdigit() or char == "_" for char in detail)
    ):
        return f"DRAFTER_{detail}"
    return None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class _ProductActionResultBase(BaseModel):
    """Fields shared by versioned Product action results."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=128)
    journey_id: str = Field(default="", max_length=128)
    action: str = Field(min_length=1, max_length=64)
    ok: bool
    tool_name: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    pipeline_verdict: str | None = None
    product_stop_code: str | None = None
    failure_owner: str | None = None
    failure_stage: ProductFailureStage | None = None
    failure_class: ProductFailureClass | None = None
    retry_policy: ProductRetryPolicy | None = None
    requires_new_task_version: bool | None = None
    recommended_action_code: ProductRecommendedActionCode | None = None
    reason_codes: list[str] = Field(default_factory=list)
    recommended_action: str | None = None
    exported_path: str | None = None
    historical_verdict: str | None = None
    recorded_operational_status: str | None = None
    route: str | None = None
    agent_invoked: bool | None = None
    semantic_verifier_id: str | None = None
    semantic_verifier_evidence_sha256: str | None = None
    semantic_verifier_artifact_sha256: str | None = None
    semantic_verifier_passed: bool | None = None
    error: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now)


class ProductActionResultV1(_ProductActionResultBase):
    """One CLI action's semantic result, bound to one durable job."""

    schema_version: Literal[1] = 1


class ProductActionResultV2(_ProductActionResultBase):
    """Directory-aware action result without changing the v1 wire contract."""

    schema_version: Literal[2] = 2
    delivery_profile_id: str = Field(min_length=1, max_length=64)
    artifact_kind: Literal["file", "directory"]
    artifact_root: str | None = None
    artifact_tree_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    artifact_manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    workspace_structure_passed: bool | None = None

    @model_validator(mode="after")
    def _validate_workspace_result(self) -> ProductActionResultV2:
        if self.delivery_profile_id != "workspace_bundle_v1":
            return self
        if self.artifact_kind != "directory":
            raise ValueError("workspace_bundle_v1 requires artifact_kind=directory")
        hashes_present = (
            self.artifact_tree_sha256 is not None,
            self.artifact_manifest_sha256 is not None,
        )
        if any(hashes_present) and not all(hashes_present):
            raise ValueError(
                "workspace artifact evidence requires both tree and manifest hashes"
            )
        if self.ok and any(hashes_present) and self.workspace_structure_passed is not True:
            raise ValueError("successful workspace evidence requires a passing structure verdict")
        return self


ProductActionResult = ProductActionResultV1 | ProductActionResultV2


def _string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def action_result_from_payload(
    *,
    job_id: str,
    journey_id: str,
    action: str,
    ok: bool,
    payload: Mapping[str, Any],
) -> ProductActionResultV1:
    """Project a CLI payload into the stable Product action contract."""

    stages = payload.get("stages")
    stages = stages if isinstance(stages, Mapping) else {}
    route_doc = stages.get("route")
    route_doc = route_doc if isinstance(route_doc, Mapping) else {}
    segment = stages.get("direct") or stages.get("real") or stages.get("preflight") or {}
    segment = segment if isinstance(segment, Mapping) else {}
    assessment = segment.get("failure_assessment")
    assessment = assessment if isinstance(assessment, Mapping) else segment

    provider_preflight = segment.get("preflight")
    provider_preflight = (
        provider_preflight if isinstance(provider_preflight, Mapping) else {}
    )
    provider_status = _string(provider_preflight.get("status"))
    preflight_reason = _string(provider_preflight.get("reason"))

    route = _string(route_doc.get("route"))
    if route is None and stages:
        route = "DIRECT_WRAP" if "direct" in stages else "AGENT_ADAPT"
    agent_invoked: bool | None = None
    if route:
        agent_invoked = bool(route_doc.get("agent_invoked", route != "DIRECT_WRAP"))

    exported = _string(payload.get("exported"))
    task_id = _string(payload.get("task_id"))
    tool_name = _string(payload.get("tool_name"))
    # tool build payloads historically carried the exported path but not the
    # tool name.  ProductActivity must still be able to re-read the Core
    # registry/ledger instead of displaying the stale status embedded in the
    # action result.  The export directory basename is the managed package
    # identity and is safer than guessing from a task-id slug.
    if tool_name is None and exported:
        tool_name = Path(exported).name or None
    run_id = _string(segment.get("run_id") or payload.get("run_id"))
    verdict = _string(payload.get("verdict") or segment.get("verdict"))
    historical_verdict = _string(payload.get("historical_verdict"))
    preflight_doc = stages.get("preflight")
    if (
        isinstance(preflight_doc, Mapping)
        and preflight_doc.get("ok") is False
    ) or verdict == "REHEARSAL_PASS_ONLY":
        agent_invoked = False
    # ``route=AGENT_ADAPT`` is a plan, not proof of a model call. Any stop
    # before a real/direct execution stage is necessarily zero-agent, including
    # dependency and upstream-conformance preflights.
    if "real" not in stages and "direct" not in stages:
        agent_invoked = False
    agent_model_call_count = segment.get("agent_model_call_count")
    if isinstance(agent_model_call_count, int):
        agent_invoked = agent_model_call_count > 0
    reason_codes = assessment.get("reason_codes") or payload.get("reason_codes") or []
    if not isinstance(reason_codes, list):
        reason_codes = [str(reason_codes)]
    if payload.get("reason_code"):
        reason_codes = [*reason_codes, str(payload["reason_code"])]
    reason_codes = sorted({str(code) for code in reason_codes if str(code).strip()})
    artifacts: dict[str, str] = {}
    if exported:
        artifacts["exported_tool"] = exported
    draft_bundle = _string(payload.get("draft_bundle"))
    if draft_bundle:
        artifacts["draft_bundle"] = draft_bundle
    server = _string(payload.get("server"))
    if server:
        artifacts["mcp_server"] = server
    semantic_evidence_path = _string(
        payload.get("semantic_verifier_evidence_path")
    )
    if semantic_evidence_path:
        artifacts["semantic_verifier_evidence"] = semantic_evidence_path

    decision = payload.get("decision")
    decision_status = decision.get("decision") if isinstance(decision, Mapping) else decision
    recorded_status = _string(
        payload.get("operational_status") or decision_status
    )
    if action == "tool-build" and exported and not recorded_status:
        recorded_status = "REVIEW_REQUIRED"

    failure_owner = _string(
        assessment.get("failure_owner") or payload.get("failure_owner")
    )
    failure_stage = cast(
        ProductFailureStage | None,
        _string(assessment.get("failure_stage") or payload.get("failure_stage")),
    )
    failure_class = cast(
        ProductFailureClass | None,
        _string(assessment.get("failure_class") or payload.get("failure_class")),
    )
    retry_policy = cast(
        ProductRetryPolicy | None,
        _string(assessment.get("retry_policy") or payload.get("retry_policy")),
    )
    requires_new_task_version_value = assessment.get(
        "requires_new_task_version",
        payload.get("requires_new_task_version"),
    )
    requires_new_task_version = (
        requires_new_task_version_value
        if type(requires_new_task_version_value) is bool
        else None
    )
    recommended_action_code = cast(
        ProductRecommendedActionCode | None,
        _string(
            assessment.get("recommended_action_code")
            or payload.get("recommended_action_code")
        ),
    )
    product_stop_code = _string(
        segment.get("product_stop_code") or payload.get("product_stop_code")
    )
    recommended_action = _string(
        assessment.get("recommended_action") or payload.get("recommended_action")
    )
    if provider_status and provider_status != "PROVIDER_READY":
        reason_codes = sorted({*reason_codes, provider_status})
        product_stop_code = product_stop_code or "STOP_HARNESS_OR_EXTERNAL"
        recommended_action = recommended_action or (
            "模型服务恢复后重试；本次未进入 Agent repair。"
        )
        if provider_status in {
            "PROVIDER_UNAVAILABLE",
            "RATE_LIMITED",
            "PROVIDER_TIMEOUT",
        }:
            failure_owner = "EXTERNAL"
        else:
            failure_owner = "HARNESS"
    elif preflight_reason:
        reason_codes = sorted({*reason_codes, preflight_reason})
        product_stop_code = product_stop_code or "STOP_HARNESS_OR_EXTERNAL"
        failure_owner = "HARNESS"
        recommended_action = recommended_action or _string(
            segment.get("remediation")
        ) or "按预检提示清理运行环境后重试；本次未进入 Agent repair。"
    if action == "tool-audit" and not ok:
        # Current Core audit results carry typed remediation metadata.  Older
        # payloads remain readable, but Product Mode intentionally does not
        # reverse-map their reason codes into a guessed owner/action.
        failure_owner = failure_owner or "VERIFICATION"
        product_stop_code = product_stop_code or "STOP_NEEDS_HUMAN"
        recommended_action = recommended_action or (
            "旧审核结果没有 typed failure metadata；请人工复核后重新审核。"
        )
    if not ok and failure_owner is None:
        admission = payload.get("admission")
        admission = admission if isinstance(admission, Mapping) else {}
        if action == "tool-add" and admission.get("status") == "UNSUPPORTED":
            failure_owner = "USER_INPUT"
            admission_codes = admission.get("reason_codes") or []
            if not isinstance(admission_codes, list):
                admission_codes = [str(admission_codes)]
            reason_codes = sorted({
                *reason_codes,
                *(str(code) for code in admission_codes if str(code).strip()),
                *([] if admission_codes else ["ADMISSION_UNSUPPORTED"]),
            })
            failure_stage = "INTAKE"
            product_stop_code = product_stop_code or "STOP_NEEDS_HUMAN"
            recommended_action = recommended_action or _string(
                admission.get("next_step")
            ) or "收紧能力范围或选择受支持的公开 Python 仓库。"
        elif action == "tool-add":
            draft_error = _string(payload.get("draft_error"))
            failure = _typed_drafter_failure(draft_error or "")
            if failure is None:
                failure_owner = "EXTERNAL"
                reason_codes = sorted({*reason_codes, "DRAFT_CREATION_FAILED"})
                recommended_action = (
                    recommended_action or "恢复起草通道后重新创建任务。"
                )
                product_stop_code = (
                    product_stop_code or "STOP_HARNESS_OR_EXTERNAL"
                )
            else:
                (
                    public_reason_code,
                    failure_owner,
                    failure_class,
                    retry_policy,
                    requires_new_task_version,
                    recommended_action_code,
                    typed_stop_code,
                    typed_action,
                ) = failure
                failure_stage = "DRAFTING"
                reason_codes = sorted({*reason_codes, public_reason_code})
                detail = _invalid_model_output_detail(draft_error or "")
                if detail is not None:
                    reason_codes = sorted({*reason_codes, detail})
                recommended_action = recommended_action or typed_action
                product_stop_code = product_stop_code or typed_stop_code
        elif action == "tool-mcp":
            failure_owner = "USER_INPUT"
            reason_codes = sorted({*reason_codes, "MCP_EXPOSURE_DENIED"})
            product_stop_code = product_stop_code or "STOP_NEEDS_HUMAN"
            recommended_action = recommended_action or "先完成 Fresh audit 并确认当前状态为 ACTIVE。"
        else:
            failure_owner = "HARNESS"
            reason_codes = sorted({*reason_codes, "PRODUCT_ACTION_FAILED"})
            product_stop_code = product_stop_code or "STOP_HARNESS_OR_EXTERNAL"
            recommended_action = recommended_action or "检查 Core 状态与环境后重试。"

    return ProductActionResultV1(
        job_id=job_id,
        journey_id=journey_id,
        action=action,
        ok=bool(ok),
        tool_name=tool_name,
        task_id=task_id,
        run_id=run_id,
        pipeline_verdict=verdict,
        product_stop_code=product_stop_code,
        failure_owner=failure_owner,
        failure_stage=failure_stage,
        failure_class=failure_class,
        retry_policy=retry_policy,
        requires_new_task_version=requires_new_task_version,
        recommended_action_code=recommended_action_code,
        reason_codes=reason_codes,
        recommended_action=recommended_action,
        exported_path=exported,
        historical_verdict=historical_verdict,
        recorded_operational_status=recorded_status,
        route=route,
        agent_invoked=agent_invoked,
        semantic_verifier_id=_string(
            payload.get("semantic_verifier_verifier_id")
        ),
        semantic_verifier_evidence_sha256=_string(
            payload.get("semantic_verifier_evidence_sha256")
        ),
        semantic_verifier_artifact_sha256=_string(
            payload.get("semantic_verifier_artifact_sha256")
        ),
        semantic_verifier_passed=(
            payload.get("semantic_verifier_passed")
            if type(payload.get("semantic_verifier_passed")) is bool
            else None
        ),
        error=_string(payload.get("error") or payload.get("draft_error")),
        artifacts=artifacts,
    )


def workspace_action_result_from_payload(
    *,
    job_id: str,
    journey_id: str,
    action: str,
    ok: bool,
    payload: Mapping[str, Any],
    artifact_root: Path | str | None,
    artifact_tree_sha256: str | None,
    artifact_manifest_sha256: str | None,
    workspace_structure_passed: bool | None,
) -> ProductActionResultV2:
    """Project a workspace action while retaining all v1 failure semantics."""

    base = action_result_from_payload(
        job_id=job_id,
        journey_id=journey_id,
        action=action,
        ok=ok,
        payload=payload,
    )
    values = base.model_dump(mode="json", exclude={"schema_version"})
    root = str(Path(artifact_root).resolve()) if artifact_root is not None else None
    artifacts = dict(base.artifacts)
    if root:
        artifacts["workspace_bundle"] = root
    values["artifacts"] = artifacts
    return ProductActionResultV2(
        **values,
        delivery_profile_id="workspace_bundle_v1",
        artifact_kind="directory",
        artifact_root=root,
        artifact_tree_sha256=artifact_tree_sha256,
        artifact_manifest_sha256=artifact_manifest_sha256,
        workspace_structure_passed=workspace_structure_passed,
    )


def write_product_action_result(path: Path, result: ProductActionResult) -> Path:
    """Atomically persist one validated result."""

    path = Path(path)
    atomic_write_json(path, result.model_dump(mode="json"))
    return path


def _read_product_action_result_bytes(path: Path) -> bytes:
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(f"action result is not a regular file: {path}")
        if opened.st_size > MAX_ACTION_RESULT_BYTES:
            raise OSError(f"action result is too large: {path}")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            payload = stream.read(MAX_ACTION_RESULT_BYTES + 1)
    finally:
        os.close(fd)
    if len(payload) > MAX_ACTION_RESULT_BYTES:
        raise OSError(f"action result is too large: {path}")
    return payload


def _parse_product_action_result(payload: bytes) -> ProductActionResult:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("action result root must be an object")
    schema_version = value.get("schema_version")
    model = ProductActionResultV2 if schema_version == 2 else ProductActionResultV1
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise ValueError(f"invalid ProductActionResultV1/V2: {exc}") from exc


def read_product_action_result(path: Path) -> ProductActionResult:
    """Safely read a bounded, regular, non-symlink result file."""

    return _parse_product_action_result(_read_product_action_result_bytes(path))


def read_product_action_result_with_sha256(
    path: Path,
) -> tuple[ProductActionResult, str]:
    """Read and hash one immutable byte snapshot of an action result."""

    payload = _read_product_action_result_bytes(path)
    return _parse_product_action_result(payload), hashlib.sha256(payload).hexdigest()
