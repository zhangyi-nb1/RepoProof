"""Read-only Product Mode projection for RepoProof Studio.

The registry, package manifests, metrics file and release ledger remain the
facts.  This module deliberately does not import the completion gate and does
not invent operational approvals when the M5 ledger is absent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REGISTRY_NAME = ".repoproof-registry.json"
RELEASE_LEDGER_NAME = ".repoproof-release-decisions.jsonl"
VALID_RELEASE = frozenset({"ACTIVE", "REVIEW_REQUIRED", "REVOKED"})


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def tool_root() -> Path:
    return Path(os.environ.get("REPOPROOF_TOOL_ROOT", "~/tools")).expanduser()


def ui_state_root() -> Path:
    return Path(os.environ.get("REPOPROOF_UI_STATE_ROOT", "~/.repoproof")).expanduser()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须是 JSON object")
    return value


def load_registry(dest_root: Path | None = None) -> tuple[dict[str, Any], str | None]:
    root = Path(dest_root or tool_root())
    path = root / REGISTRY_NAME
    if not path.is_file():
        return {"schema_version": 1, "tools": {}}, None
    try:
        doc = _read_json(path)
        if not isinstance(doc.get("tools", {}), dict):
            raise ValueError("registry.tools 必须是 object")
        return doc, None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"schema_version": 1, "tools": {}}, str(exc)


def load_release_projection(
    dest_root: Path | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], str | None, bool]:
    """Fold append-only release decisions by tool and task id, fail closed."""
    root = Path(dest_root or tool_root())
    path = root / RELEASE_LEDGER_NAME
    if not path.is_file():
        return {}, {}, None, False
    by_tool: dict[str, dict[str, Any]] = {}
    by_task: dict[str, dict[str, Any]] = {}
    try:
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no} 必须是 JSON object")
            decision = row.get("decision")
            if decision not in VALID_RELEASE:
                raise ValueError(f"{path}:{line_no} 非法 decision={decision!r}")
            tool = row.get("tool")
            task_id = row.get("task_id")
            if isinstance(tool, str) and tool:
                by_tool[tool] = row
            if isinstance(task_id, str) and task_id:
                by_task[task_id] = row
            if not tool and not task_id:
                raise ValueError(f"{path}:{line_no} 缺少 tool/task_id")
        return by_tool, by_task, None, True
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {}, {}, str(exc), True


def _scan_packages(dest_root: Path) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    if not dest_root.is_dir():
        return found
    for child in sorted(p for p in dest_root.iterdir() if p.is_dir()):
        manifest = child / "tool.json"
        if not manifest.is_file():
            continue
        try:
            doc = _read_json(manifest)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        name = doc.get("name")
        if isinstance(name, str) and name:
            found[name] = {
                "path": str(child),
                "verdict": (doc.get("verification") or {}).get("verdict"),
                "source": doc.get("source") or {},
                "summary": doc.get("summary") or "",
                "provenance": "scan",
            }
    return found


def list_tools(dest_root: Path | None = None) -> dict[str, Any]:
    root = Path(dest_root or tool_root())
    registry, registry_error = load_registry(root)
    entries = dict(registry.get("tools") or {})
    for name, entry in _scan_packages(root).items():
        entries.setdefault(name, entry)
    by_tool, by_task, release_error, ledger_present = load_release_projection(root)

    rows: list[dict[str, Any]] = []
    for name, entry in sorted(entries.items()):
        package_path = Path(str(entry.get("path") or (root / name))).expanduser()
        manifest_path = package_path / "tool.json"
        manifest: dict[str, Any] = {}
        health = "MISSING"
        if manifest_path.is_file():
            try:
                manifest = _read_json(manifest_path)
                health = "OK" if (manifest.get("verification") or {}).get("verdict") else "UNVERIFIED"
            except (OSError, ValueError, json.JSONDecodeError):
                health = "CORRUPT"

        verification = manifest.get("verification") or {}
        historical = (
            verification.get("verdict")
            or entry.get("historical_verdict")
            or entry.get("verdict")
        )
        task_id = entry.get("task_id") or verification.get("task_id")
        release = by_tool.get(name) or (by_task.get(str(task_id)) if task_id else None)
        if release_error:
            operational = "REVIEW_REQUIRED"
        elif release:
            operational = release["decision"]
        elif historical:
            operational = "REVIEW_REQUIRED"
        else:
            operational = "UNVERIFIED"
        source = manifest.get("source") or entry.get("source") or {}
        rows.append(
            {
                "name": name,
                "summary": manifest.get("summary") or entry.get("summary") or "",
                "path": str(package_path),
                "task_id": task_id,
                "historical_verdict": historical,
                "operational_status": operational,
                "operational_reason": (release or {}).get("reason_code"),
                "health": health,
                "source_url": source.get("url"),
                "source_distribution": source.get("distribution"),
                "resolved_commit": source.get("resolved_commit"),
                "run_id": entry.get("run_id") or verification.get("run_id"),
                "contract_sha256": entry.get("contract_sha256") or verification.get("contract_sha256"),
            }
        )
    return {
        "root": str(root),
        "tools": rows,
        "registry_error": registry_error,
        "release_error": release_error,
        "release_ledger_present": ledger_present,
    }


def load_recorded_metrics(root: Path | None = None) -> dict[str, Any]:
    path = Path(root or project_root()) / "docs" / "m4_metrics.json"
    if not path.is_file():
        return {}
    try:
        return _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def dashboard_snapshot(
    dest_root: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    library = list_tools(dest_root)
    tools = library["tools"]
    metrics = load_recorded_metrics(root)
    operational = {key: 0 for key in ("ACTIVE", "REVIEW_REQUIRED", "REVOKED", "UNVERIFIED")}
    for tool in tools:
        operational[tool["operational_status"]] = operational.get(tool["operational_status"], 0) + 1
    verified = sum(1 for tool in tools if tool.get("historical_verdict"))
    return {
        **library,
        "metrics": metrics,
        "installed": len(tools),
        "historically_verified": verified,
        "operational": operational,
        "false_success": (metrics.get("false_success") or {}).get("flagged", 0),
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
