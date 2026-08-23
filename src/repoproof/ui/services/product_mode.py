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
