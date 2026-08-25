"""Product Mode projections backed by RepoProof Core facts.

The UI is deliberately a reader, not a second registry, release-ledger parser
or contract judge. Installed-tool state comes from
``runner.tool_registry.list_tools(scan=False)``; output examples are checked by
the same ``ToolOutputContract`` validator used by freeze, runtime, audit and
MCP generation.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from repoproof.adoption.assembly.example_compiler import CONTAINS, Example
from repoproof.adoption.assembly.output_contract import (
    is_capability_output_invocation,
    is_structured_output_format,
    normalize_output_format,
    output_contract_matches_format,
    validate_output_text,
)
from repoproof.adoption.assembly.tool_assembler import next_tool_task_id
from repoproof.domain.models import ToolOutputContract, ToolSpec
from repoproof.runner import tool_registry
from repoproof.runner.tool_paths import ToolPathError
from repoproof.runner.tool_release import (
    RELEASE_LEDGER_NAME,
    REVIEW_REQUIRED,
    ReleaseLedgerError,
    is_historical_tool_ready,
)

REGISTRY_NAME = tool_registry.REGISTRY_NAME

def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def tool_root() -> Path:
    return Path(os.environ.get("REPOPROOF_TOOL_ROOT", "~/tools")).expanduser()


def ui_state_root() -> Path:
    return Path(os.environ.get("REPOPROOF_UI_STATE_ROOT", "~/.repoproof")).expanduser()


def _empty_library(root: Path) -> dict[str, Any]:
    return {
        "root": str(root),
        "tools": [],
        "registry_error": None,
        "release_error": None,
        "projection_errors": [],
        "release_ledger_present": (root / RELEASE_LEDGER_NAME).is_file(),
    }


def _project_tool(row: dict[str, Any], root: Path) -> dict[str, Any]:
    """Shape one Core row for display, permitting only fail-closed changes."""

    health = str(row.get("status") or "MISSING")
    operational = str(row.get("operational_status") or REVIEW_REQUIRED)
    reason_code = row.get("operational_reason_code")
    if not reason_code:
        reason_code = "NO_CURRENT_RELEASE_DECISION"

    reason_codes = [str(reason_code)] if reason_code else []
    exposure_warning = row.get("mcp_exposure_warning")
    if isinstance(exposure_warning, str) and exposure_warning not in reason_codes:
        reason_codes.append(exposure_warning)

    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    package_path = row.get("path")
    if not isinstance(package_path, str) or not package_path:
        package_path = str(root / str(row.get("name") or ""))
    return {
        **row,
        "name": str(row.get("name") or ""),
        "summary": str(row.get("summary") or ""),
        "path": package_path,
        "task_id": row.get("task_id"),
        "run_id": row.get("run_id"),
        "contract_sha256": row.get("contract_sha256"),
        "historical_verdict": row.get("historical_verdict", row.get("verdict")),
        "operational_status": operational,
        "operational_reason_code": reason_code,
        "reason_codes": reason_codes,
        # Compatibility alias for the first M6 UI; new pages show the explicit
        # Core field name above.
        "operational_reason": reason_code,
        "health": health,
        "source_url": source.get("url"),
        "source_distribution": source.get("distribution"),
        "resolved_commit": source.get("resolved_commit"),
    }


def list_tools(dest_root: Path | None = None) -> dict[str, Any]:
    """Return a read-only UI projection of Core's installed-tool registry.

    Directory discovery is intentionally disabled. A UI refresh must never
    mutate the registry or turn an unregistered directory into a product fact.
    A malformed registry or release ledger returns no actionable tools.
    """

    root = Path(dest_root or tool_root())
    result = _empty_library(root)
    try:
        core_rows = tool_registry.list_tools(root, scan=False)
    except ReleaseLedgerError as exc:
        result["release_error"] = str(exc)
        result["projection_errors"] = [
            {"reason_code": "RELEASE_LEDGER_INVALID", "detail": str(exc)}
        ]
        return result
    except (OSError, UnicodeError, ValueError, ToolPathError) as exc:
        result["registry_error"] = str(exc)
        result["projection_errors"] = [
            {"reason_code": "TOOL_REGISTRY_INVALID", "detail": str(exc)}
        ]
        return result

    result["tools"] = [_project_tool(row, root) for row in core_rows]
    return result


def load_recorded_metrics(root: Path | None = None) -> dict[str, Any]:
    path = Path(root or project_root()) / "docs" / "m4_metrics.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def dashboard_snapshot(
    dest_root: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    library = list_tools(dest_root)
    tools = library["tools"]
    metrics = load_recorded_metrics(root)
    operational = {
        key: 0 for key in ("ACTIVE", "REVIEW_REQUIRED", "REVOKED", "UNVERIFIED")
    }
    for tool in tools:
        status = tool["operational_status"]
        operational[status] = operational.get(status, 0) + 1
    verified = sum(
        1
        for tool in tools
        if is_historical_tool_ready(tool.get("historical_verdict"))
    )
    reason_codes = Counter(
        code
        for tool in tools
        for code in tool.get("reason_codes", [])
    )
    return {
        **library,
        "metrics": metrics,
        "installed": len(tools),
        "historically_verified": verified,
        "operational": operational,
        "operational_reason_codes": dict(sorted(reason_codes.items())),
        "false_success": (metrics.get("false_success") or {}).get("flagged", 0),
    }


def default_output_contract(format_name: str) -> dict[str, Any]:
    """Return a complete v2 contract, including for ordinary text output."""

    family = normalize_output_format(format_name)
    if family == "text":
        contract = ToolOutputContract(media_type="text/plain", root_type="text")
    elif family == "json_lines":
        contract = ToolOutputContract(
            media_type="application/x-ndjson", root_type="json_lines"
        )
    else:
        root_type = {"json_object": "object", "json_array": "array"}.get(
            family, "json"
        )
        contract = ToolOutputContract(
            media_type="application/json", root_type=root_type
        )
    return contract.model_dump(mode="json")


def parse_output_contract(
    value: str | dict[str, Any], *, output_format: str
) -> tuple[ToolOutputContract | None, list[str]]:
    """Parse and cross-check a UI contract using the Core data model."""

    try:
        raw = json.loads(value) if isinstance(value, str) else value
        if not isinstance(raw, dict):
            raise ValueError("输出合同必须是 JSON object")
        contract = ToolOutputContract.model_validate(raw)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        return None, [f"OUTPUT_CONTRACT_INVALID: {exc}"]
    if not output_contract_matches_format(output_format, contract):
        return None, [
            "OUTPUT_CONTRACT_FORMAT_MISMATCH: "
            "output.format 与可执行输出合同的 root_type 不一致"
        ]
    return contract, []


def _safe_example_path(root: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        return None
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def validate_draft_output_examples(draft_dir: Path) -> dict[str, Any]:
    """Read-only pre-build validation of ToolSpec and exact golden outputs.

    This mirrors the assembler's T6-T9 output checks without writing generated
    files. It is an early UI guard only: ``assemble_tool_task`` remains the
    authoritative version allocator and freeze gate.
    """

    draft_dir = Path(draft_dir)
    errors: list[str] = []
    try:
        draft = yaml.safe_load(
            (draft_dir / "draft.yaml").read_text(encoding="utf-8")
        )
        if not isinstance(draft, dict):
            raise ValueError("draft.yaml 必须是 object")
        spec = ToolSpec.model_validate(draft.get("tool"))
    except (OSError, UnicodeError, ValueError, ValidationError, yaml.YAMLError) as exc:
        return {
            "ok": False,
            "structured": False,
            "errors": [f"DRAFT_INVALID: {exc}"],
        }

    output = spec.interface.output
    if spec.schema_version < 2:
        errors.append(
            "TOOL_SCHEMA_VERSION_UNSUPPORTED: 新构建不得用 v1 绕过输出合同门"
        )
    if spec.schema_version >= 2 and output.contract is None:
        errors.append("OUTPUT_CONTRACT_MISSING: v2 工具必须声明完整输出合同")
    contract = output.contract
    if contract is not None and not output_contract_matches_format(
        output.format, contract
    ):
        errors.append(
            "OUTPUT_CONTRACT_FORMAT_MISMATCH: output.format 与输出合同不一致"
        )

    structured = is_structured_output_format(output.format)
    exact_structured = False
    try:
        examples_doc = yaml.safe_load(
            (draft_dir / "examples.yaml").read_text(encoding="utf-8")
        )
        raw_examples = (examples_doc or {}).get("examples")
        if not isinstance(raw_examples, list):
            raise ValueError("examples 必须是 list")
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        errors.append(f"EXAMPLES_INVALID: {exc}")
        raw_examples = []

    examples_root = draft_dir / "examples"
    for index, raw in enumerate(raw_examples, start=1):
        try:
            example = Example.model_validate(raw)
        except ValidationError as exc:
            errors.append(f"EXAMPLE_INVALID: example={index} {exc}")
            continue
        if not is_capability_output_invocation(example.input):
            continue

        golden: str | None = None
        if example.expected_file is not None:
            path = _safe_example_path(examples_root, example.expected_file)
            if path is None:
                errors.append(
                    f"GOLDEN_PATH_INVALID: example={index} expected_file 越界"
                )
                continue
            try:
                golden = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                errors.append(f"GOLDEN_UNREADABLE: example={index} {exc}")
                continue
            exact_structured = True
        elif example.expected is not None and not example.expected.startswith(CONTAINS):
            golden = example.expected
            exact_structured = True

        if golden is not None and contract is not None:
            for detail in validate_output_text(golden, contract):
                errors.append(f"GOLDEN_OUTPUT_INVALID: example={index} {detail}")

    if structured and not exact_structured:
        errors.append(
            "EXACT_STRUCTURED_GOLDEN_MISSING: JSON 家族至少需要一组完整精确真值"
        )
    return {
        "ok": not errors,
        "structured": structured,
        "errors": errors,
        "contract": contract.model_dump(mode="json") if contract is not None else None,
    }


def next_task_version_preview(
    tool_name: str, root: Path | None = None
) -> dict[str, str]:
    """Read-only preview; the assembler remains authoritative at build time."""

    task_id = next_tool_task_id(Path(root or project_root()), tool_name)
    return {
        "task_id": task_id,
        "authority": "assemble_tool_task",
        "note": "只读预览；最终版本由装配器在冻结时重新分配。",
    }


def tool_command(name: str) -> str:
    return f"{name} <input-file>"


def mcp_command(name: str) -> str:
    return f"repoproof tool mcp {name}"


def status_label(status: str) -> str:
    return {
        "ACTIVE": "可使用",
        "REVIEW_REQUIRED": "待审核",
        "REVOKED": "已撤回",
        "UNVERIFIED": "未验证",
    }.get(str(status), str(status or "未知"))


# ---------------------------------------------------- Gate 4:构建结论投影

PRODUCT_STOP_LABELS: dict[str, str] = {
    "NO_REPAIR_NEEDED": "初次候选即通过(未动用修复)",
    "REPAIR_SUCCEEDED": "有界修复后通过独立验证",
    "STOP_NON_REPAIRABLE": "失败类别不允许交给 Agent 修复",
    "STOP_NEEDS_HUMAN": "需要人决策(合同/样例/范围)",
    "STOP_NO_PROGRESS": "连续无可测进展,确定性停止",
    "STOP_SCOPE_DRIFT": "越界/触碰保护面,策略终止",
    "STOP_BUDGET_EXHAUSTED": "修复预算耗尽",
    "STOP_HIDDEN_FAILURE": "隐藏验收面未通过(细节不外泄)",
    "STOP_HARNESS_OR_EXTERNAL": "Harness/外部基础设施故障(可重新发起)",
}

ROUTE_LABELS: dict[str, str] = {
    "DIRECT_WRAP": "确定性直连包装 —— 本次不需要 Agent",
    "AGENT_ADAPT": "受限 Coding Agent 适配(mini-swe,含最多两次有界修复)",
    "NONE": "不进入实现路线",
}


def parse_build_summary(log_text: str) -> dict | None:
    """从 tool-build 日志尾部解析结论 JSON(stages/verdict/exported)。

    解析失败返回 None —— 呈现层照常显示原始日志,不猜、不碎页面。
    """
    import json as _json

    text = (log_text or "").strip()
    end = text.rfind("}")
    while end != -1:
        depth = 0
        for start in range(end, -1, -1):
            ch = text[start]
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    try:
                        doc = _json.loads(text[start:end + 1])
                    except ValueError:
                        break
                    if isinstance(doc, dict) and "stages" in doc:
                        return doc
                    break
        end = text.rfind("}", 0, max(end - 1, 0))
    return None


def build_conclusion(summary: dict) -> dict:
    """构建结论的人读投影(路线/终止码/归因),供活动页渲染。"""
    stages = summary.get("stages") or {}
    route = ((stages.get("route") or {}).get("route")
             or ("DIRECT_WRAP" if "direct" in stages else "AGENT_ADAPT"))
    seg = stages.get("direct") or stages.get("real") or {}
    stop = seg.get("product_stop_code") or ""
    fa = seg.get("failure_assessment") or {}
    return {
        "route": route,
        "route_label": ROUTE_LABELS.get(route, route),
        "agent_invoked": bool((stages.get("route") or {}).get(
            "agent_invoked", route != "DIRECT_WRAP")),
        "verdict": summary.get("verdict"),
        "exported": summary.get("exported"),
        "product_stop_code": stop,
        "stop_label": PRODUCT_STOP_LABELS.get(stop, stop or "—"),
        "failure_owner": fa.get("failure_owner"),
        "reason_codes": fa.get("reason_codes") or [],
        "run_id": seg.get("run_id"),
    }
