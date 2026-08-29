"""Structured Product Mode action outcomes.

The durable worker state answers only whether a process ran and produced its
declared artifact.  This module records the semantic outcome emitted by the
Product CLI so Studio never has to infer a pipeline verdict from log text.
Operational status in this document is historical context only; callers must
always re-read the Core registry and append-only release ledger for the current
status.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from repoproof.execution.core_execution import atomic_write_json

ACTION_RESULT_SCHEMA_VERSION = 1
MAX_ACTION_RESULT_BYTES = 1024 * 1024


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ProductActionResultV1(BaseModel):
    """One CLI action's semantic result, bound to one durable job."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
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
    reason_codes: list[str] = Field(default_factory=list)
    recommended_action: str | None = None
    exported_path: str | None = None
    historical_verdict: str | None = None
    recorded_operational_status: str | None = None
    route: str | None = None
    agent_invoked: bool | None = None
    error: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utc_now)


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
        if "BUILD_FAILED" in reason_codes:
            failure_owner = failure_owner or "HARNESS"
            product_stop_code = product_stop_code or "STOP_HARNESS_OR_EXTERNAL"
            recommended_action = recommended_action or (
                "检查导出包 build.sh、固定依赖与 wheelhouse；环境恢复前不要交给 Agent repair。"
            )
        else:
            failure_owner = failure_owner or "VERIFICATION"
            product_stop_code = product_stop_code or "STOP_NEEDS_HUMAN"
            recommended_action = recommended_action or (
                "核对 fresh input 与期望输出；若真值无误，请修复适配器并创建新任务版本。"
            )
    if not ok and failure_owner is None:
        admission = payload.get("admission")
        admission = admission if isinstance(admission, Mapping) else {}
        if action == "tool-add" and admission.get("status") == "UNSUPPORTED":
            failure_owner = "USER_INPUT"
            reason_codes = sorted({*reason_codes, "ADMISSION_UNSUPPORTED"})
            product_stop_code = product_stop_code or "STOP_NEEDS_HUMAN"
            recommended_action = recommended_action or "收紧能力范围或选择受支持的公开 Python 仓库。"
        elif action == "tool-add":
            failure_owner = "EXTERNAL"
            reason_codes = sorted({*reason_codes, "DRAFT_CREATION_FAILED"})
            product_stop_code = product_stop_code or "STOP_HARNESS_OR_EXTERNAL"
            recommended_action = recommended_action or "恢复起草通道后重新创建任务。"
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
        reason_codes=reason_codes,
        recommended_action=recommended_action,
        exported_path=exported,
        historical_verdict=historical_verdict,
        recorded_operational_status=recorded_status,
        route=route,
        agent_invoked=agent_invoked,
        error=_string(payload.get("error") or payload.get("draft_error")),
        artifacts=artifacts,
    )


def write_product_action_result(path: Path, result: ProductActionResultV1) -> Path:
    """Atomically persist one validated result."""

    path = Path(path)
    atomic_write_json(path, result.model_dump(mode="json"))
    return path


def read_product_action_result(path: Path) -> ProductActionResultV1:
    """Safely read a bounded, regular, non-symlink result file."""

    path = Path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(f"action result is not a regular file: {path}")
        if opened.st_size > MAX_ACTION_RESULT_BYTES:
            raise OSError(f"action result is too large: {path}")
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
            value = json.load(stream)
    finally:
        os.close(fd)
    if not isinstance(value, dict):
        raise ValueError("action result root must be an object")
    try:
        return ProductActionResultV1.model_validate(value)
    except ValidationError as exc:
        raise ValueError(f"invalid ProductActionResultV1: {exc}") from exc
