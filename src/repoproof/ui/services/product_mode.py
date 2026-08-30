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
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from repoproof.adoption.assembly.example_compiler import CONTAINS, Example
from repoproof.adoption.assembly.output_contract import (
    is_capability_output_invocation,
    normalize_output_format,
    output_contract_matches_format,
    validate_output_text,
)
from repoproof.adoption.assembly.tool_assembler import next_tool_task_id
from repoproof.adoption.delivery.product_profile import (
    ProductProfileError,
    product_delivery_profile,
)
from repoproof.adoption.intake.intent_contract import IntentContractDraftV1
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

    raw_source = row.get("source")
    source = raw_source if isinstance(raw_source, dict) else {}
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
    """Compile a default through the same Core registry used at freeze."""

    try:
        _, contract = product_delivery_profile().contract_for_label(format_name)
        return contract.model_dump(mode="json")
    except ProductProfileError:
        # Preserve the historical editor preview for an unknown custom label.
        # Save/freeze still fails closed in ProductDeliveryProfile.assert_interface;
        # this fallback never grants admission or a specialized validator.
        pass

    family = normalize_output_format(format_name)
    if family == "text":
        contract = ToolOutputContract(
            media_type="text/plain",
            root_type="text",
        )
    elif family == "json_lines":
        contract = ToolOutputContract(
            media_type="application/x-ndjson", root_type="json_lines"
        )
    else:
        # root_type 是 Literal 字面量集合;经 dict.get 会退化成 str,
        # 显式分支保住字面量身份(拼错的键会在这里当场露馅)
        root_type: Literal["object", "array", "json"] = (
            "object" if family == "json_object"
            else "array" if family == "json_array"
            else "json")
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
    profile = product_delivery_profile()
    try:
        artifact = profile.artifact_for_label(output_format)
    except ProductProfileError:
        artifact = None
    if artifact is not None:
        try:
            profile.assert_compiled_output(
                format_id=artifact.format_id,
                format_name=artifact.format_name,
                contract=contract,
            )
        except ProductProfileError as exc:
            return None, [
                "OUTPUT_CONTRACT_PROFILE_MISMATCH: "
                f"合同不是当前支持面编译结果（{exc}）"
            ]
    elif not output_contract_matches_format(output_format, contract):
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
    if contract is not None and spec.schema_version >= 3:
        try:
            intent = IntentContractDraftV1.model_validate(
                draft.get("_intent_contract")
            )
            if intent.delivery is None:
                raise ProductProfileError("DELIVERY_INTENT_MISSING")
            profile = product_delivery_profile(intent.delivery.profile_id)
            profile.assert_compiled_output(
                format_id=intent.delivery.admitted_output_format_id,
                format_name=output.format,
                contract=contract,
            )
        except (ProductProfileError, ValueError) as exc:
            errors.append(f"OUTPUT_CONTRACT_PROFILE_MISMATCH: {exc}")
    elif contract is not None and not output_contract_matches_format(
        output.format, contract
    ):
        # Historical v1/v2 drafts predate the typed delivery intent.  Keep the
        # old label bridge read-only; it never admits a new v3 Product task.
        errors.append(
            "OUTPUT_CONTRACT_FORMAT_MISMATCH: output.format 与输出合同不一致"
        )

    # Executable structure is a contract property.  Human labels are allowed to
    # vary without changing whether a complete exact golden is required.
    structured = contract is not None and contract.root_type != "text"
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
    "AGENT_ADAPT": "受限 Coding Agent 适配(可插拔 backend,含有界失败修复)",
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


# ------------------------------------------- M6 用户测试 P1:人话语义层
#
# 两名目标用户实测反馈:①「fresh-input 审核 / ACTIVE / MCP」术语堆叠,
# 字面能读通但不知道什么意思;②找不到"回退已成功任务"的入口。
# 本节是产品端全部状态/原因/操作文案的**唯一来源** —— 页面不许再散落
# 自造术语;写法一律「先人话,括号里给术语」。

AUDIT_EXPLAINER = (
    "「新输入抽查」= 拿一份这个工具**从没见过**的输入文件实际跑一遍,"
    "对照你自己准备的正确结果。通过 → 状态变为「可使用」;"
    "不通过 → 自动停用。这是上架前的最后一道人工把关。"
)

STATUS_EXPLAINERS: dict[str, str] = {
    "ACTIVE": "构建、验证、新输入抽查都通过了,现在可以使用、也可以接入 AI 助手。",
    "REVIEW_REQUIRED": "构建与自动验证已通过,但还没做过「新输入抽查」——"
                       "在下方「管理这个工具」里做一次即可上架。",
    "REVOKED": "已停用:今后不能使用、不能接入 AI 助手。历史成绩不受影响"
               "(当时的验证结论永远保留)。",
    "UNVERIFIED": "登记信息与验证证据对不上,系统按最保守方式处理:不可使用。",
}

REASON_CODE_LABELS: dict[str, str] = {
    "INITIAL_EXPORT_REVIEW_REQUIRED":
        "刚构建完成,还没做过新输入抽查(抽查通过后才能使用)",
    "FRESH_INPUT_PASS":
        "已通过新输入抽查(用一份从未见过的输入实测,结果正确)",
    "FRESH_INPUT_MISMATCH":
        "新输入抽查未通过:实测输出与期望不一致,已自动停用",
    "FRESH_INPUT_EXECUTION_FAILED":
        "新输入抽查未通过:工具运行报错,已自动停用",
    "OUTPUT_CONTRACT_MISMATCH":
        "审计发现当初的任务定义自相矛盾(要求的输出格式与验收标准对不上)。"
        "历史成绩保留,但现已停用;恢复使用需要人工修正任务定义后重新构建",
    "USER_WITHDRAWAL":
        "使用者主动停用。注意:主动停用后不能靠普通抽查恢复,"
        "如需再次使用要构建新版本",
    "MIGRATED_FRESH_INPUT_PASS":
        "已通过新输入抽查(历史抽查记录经完整性校验后一次性导入)",
    "MIGRATED_AUDIT_FAIL":
        "历史抽查未通过(记录经完整性校验后一次性导入),已停用",
    "BUILD_FAILED": "构建失败",
    "AUDIT_TASK_IDENTITY_MISMATCH":
        "Fresh audit 候选属于旧任务版本；已拒绝运行，请刷新后重新生成候选",
    "LEGACY_SERVER_MUST_BE_DETACHED":
        "旧版 AI 接入文件已失效:请先从你的 AI 助手里移除它,再重新生成",
    "LEGACY_MCP_MUST_BE_DETACHED":
        "旧版 MCP 文件不具备发布状态闸门：先从 AI 助手解绑并移入备份，再重试升级",
}


def reason_label(code: str) -> str:
    return REASON_CODE_LABELS.get(str(code), str(code))
