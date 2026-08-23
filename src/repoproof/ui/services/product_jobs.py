"""Bounded Product Mode jobs and draft editing for RepoProof Studio.

Product state lives below ``REPOPROOF_UI_STATE_ROOT`` (``~/.repoproof`` by
default).  This service never writes Benchmark Lab ``runs/``, benchmarks or
evidence, and every CLI launch uses an argv list rather than a shell.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

from repoproof.ui.services.product_mode import ui_state_root

PRODUCT_LOCK = "product-job.json"


def _product_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _product_python(root: Path | None = None) -> str:
    candidate = Path(root or _product_root()) / ".venv" / "bin" / "python"
    return str(candidate if candidate.is_file() else Path(sys.executable))


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        stat = subprocess.run(
            ["ps", "-p", str(int(pid)), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        return bool(stat) and "Z" not in stat
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def tool_add_argv(
    root: Path,
    *,
    repo: str,
    capability: str,
    draft_dir: Path,
    revision: str | None = None,
    fake_drafter: bool = False,
) -> list[str]:
    argv = [
        _product_python(root),
        "-m",
        "repoproof.cli",
        "tool",
        "add",
        "--repo",
        repo,
        "--capability",
        capability,
        "--draft-out",
        str(draft_dir),
    ]
    if revision:
        argv += ["--revision", revision]
    if fake_drafter:
        argv.append("--fake-drafter")
    return argv


def tool_build_argv(
    root: Path,
    *,
    draft_dir: Path,
    dest_root: Path,
    rehearsal_only: bool,
) -> list[str]:
    argv = [
        _product_python(root),
        "-m",
        "repoproof.cli",
        "tool",
        "build",
        "--draft-dir",
        str(draft_dir),
        "--dest-root",
        str(dest_root),
    ]
    if rehearsal_only:
        argv.append("--rehearsal-only")
    return argv


def _artifact_signature(path: Path | None) -> dict | None:
    """Enough identity to reject a stale pre-existing artifact as job success."""
    if path is None or not Path(path).exists():
        return None
    try:
        stat = Path(path).stat()
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    except OSError:
        return None


def product_job_state() -> dict | None:
    path = ui_state_root() / PRODUCT_LOCK
    if not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "alive": False,
            "finished": True,
            "ok": False,
            "note": "后台任务状态文件损坏，未猜测执行结果。",
        }
    state["alive"] = _pid_alive(state.get("pid"))
    artifact = Path(state["expected_artifact"]) if state.get("expected_artifact") else None
    current_signature = _artifact_signature(artifact)
    artifact_ok = bool(
        artifact
        and current_signature is not None
        and current_signature != state.get("artifact_before")
    )
    state["finished"] = not state["alive"]
    state["ok"] = bool(state["finished"] and artifact_ok)
    if state["finished"]:
        state["note"] = (
            f"{state.get('label')} 已形成预期产物：{artifact}"
            if artifact_ok
            else f"{state.get('label')} 已结束，但未发现预期产物；请查看日志。"
        )
    return state


def _start_product_job(
    argv: list[str],
    *,
    kind: str,
    label: str,
    expected_artifact: Path | None = None,
) -> dict:
    root = _product_root()
    current = product_job_state()
    if current and current.get("alive"):
        return {"ok": False, "error": f"已有任务在运行：{current.get('label')}"}
    state_root = ui_state_root()
    state_root.mkdir(parents=True, exist_ok=True)
    log_dir = state_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log = log_dir / f"{kind}-{stamp}.log"
    stream = log.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        argv,
        cwd=str(root),
        stdout=stream,
        stderr=subprocess.STDOUT,
        env=dict(os.environ),
        start_new_session=True,
    )
    stream.close()
    state = {
        "schema_version": 1,
        "pid": proc.pid,
        "kind": kind,
        "label": label,
        "log": str(log),
        "started_at": stamp,
        "expected_artifact": str(expected_artifact) if expected_artifact else None,
        "artifact_before": _artifact_signature(expected_artifact),
    }
    (state_root / PRODUCT_LOCK).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"ok": True, "pid": proc.pid, "note": f"已在后台启动：{label}"}


def start_tool_add(
    *,
    repo: str,
    capability: str,
    draft_dir: Path,
    revision: str | None = None,
    fake_drafter: bool = False,
) -> dict:
    if not repo.startswith("https://github.com/"):
        return {"ok": False, "error": "当前只支持公开 GitHub 仓库地址。"}
    if len(capability.strip()) < 8:
        return {"ok": False, "error": "请用一句完整的话描述想要的能力。"}
    draft_dir = Path(draft_dir).expanduser()
    if draft_dir.exists():
        return {"ok": False, "error": f"草稿目录已存在，拒绝覆盖：{draft_dir}"}
    root = _product_root()
    return _start_product_job(
        tool_add_argv(
            root,
            repo=repo,
            capability=capability.strip(),
            draft_dir=draft_dir,
            revision=revision,
            fake_drafter=fake_drafter,
        ),
        kind="tool-add",
        label=f"分析并起草 {repo.rsplit('/', 1)[-1]}",
        expected_artifact=draft_dir / "draft.yaml",
    )


def start_tool_build(
    *,
    draft_dir: Path,
    dest_root: Path,
    rehearsal_only: bool,
) -> dict:
    draft_dir = Path(draft_dir).expanduser()
    draft_path = draft_dir / "draft.yaml"
    if not draft_path.is_file():
        return {"ok": False, "error": f"未找到草稿：{draft_path}"}
    try:
        draft = yaml.safe_load(draft_path.read_text(encoding="utf-8")) or {}
        name = draft["tool"]["name"]
        task_id = draft["task_id"]
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"草稿无法读取：{exc}"}
    root = _product_root()
    expected = (
        root / "contracts" / f"{task_id}.yaml"
        if rehearsal_only
        else Path(dest_root).expanduser() / name / "tool.json"
    )
    return _start_product_job(
        tool_build_argv(
            root,
            draft_dir=draft_dir,
            dest_root=Path(dest_root).expanduser(),
            rehearsal_only=rehearsal_only,
        ),
        kind="tool-build",
        label=("离线彩排" if rehearsal_only else "完整构建") + f" {name}",
        expected_artifact=expected,
    )


def save_draft_review(
    draft_dir: Path,
    *,
    tool_name: str,
    summary: str,
    statement: str,
    input_format: str,
    output_format: str,
    output_schema: str,
    reference_impl: str,
    output_contract: dict | None = None,
) -> dict:
    draft_dir = Path(draft_dir)
    path = draft_dir / "draft.yaml"
    clean_name = tool_name.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", clean_name):
        return {"ok": False, "error": "工具名只能包含小写字母、数字和连字符。"}
    try:
        draft = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        draft["tool"]["name"] = clean_name
        draft["tool"]["summary"] = summary.strip()
        draft["tool"]["interface"]["input"]["format"] = input_format.strip()
        draft["tool"]["interface"]["output"]["format"] = output_format.strip()
        if output_contract is not None:
            draft["tool"]["interface"]["output"]["contract"] = output_contract
        draft["capability"]["statement"] = statement.strip()
        draft["capability"]["output_schema"] = output_schema.strip()
        draft["task_id"] = f"tool-{clean_name}-v1"
        target = draft.get("target_project") or {}
        target["path"] = f"fixtures/tool_skeleton_{clean_name}"
        target["package"] = clean_name.replace("-", "_")
        target["entry_point"] = clean_name
        draft["target_project"] = target
        draft["tool"]["interface"]["usage"] = f"{clean_name} <input> [--out FILE]"
        path.write_text(
            yaml.safe_dump(draft, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (draft_dir / "reference_impl.py").write_text(reference_impl, encoding="utf-8")
        return {"ok": True, "note": "审核修改已保存；冻结前仍会经过确定性检查。"}
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"保存失败：{exc}"}


def add_golden_example(
    draft_dir: Path,
    *,
    input_name: str,
    input_bytes: bytes,
    expected_name: str,
    expected_bytes: bytes,
) -> dict:
    draft_dir = Path(draft_dir)
    if Path(input_name).name != input_name or Path(expected_name).name != expected_name:
        return {"ok": False, "error": "样例文件名不能包含目录。"}
    examples_dir = draft_dir / "examples"
    input_rel = Path("inputs") / input_name
    expected_rel = Path("expected") / expected_name
    input_path = examples_dir / input_rel
    expected_path = examples_dir / expected_rel
    if input_path.exists() or expected_path.exists():
        return {"ok": False, "error": "同名样例已存在，拒绝覆盖。"}
    try:
        input_path.parent.mkdir(parents=True, exist_ok=True)
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(input_bytes)
        expected_path.parent.mkdir(parents=True, exist_ok=True)
        expected_path.write_bytes(expected_bytes)
        manifest = draft_dir / "examples.yaml"
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {"examples": []}
        doc.setdefault("examples", []).append(
            {"input_file": str(input_rel), "expected_file": str(expected_rel)}
        )
        manifest.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return {"ok": True, "note": f"已加入样例：{input_name} → {expected_name}"}
    except (OSError, TypeError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"保存样例失败：{exc}"}


def product_tool_commands() -> set[str]:
    root = _product_root()
    try:
        proc = subprocess.run(
            [_product_python(root), "-m", "repoproof.cli", "tool", "--help"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        text = proc.stdout + proc.stderr
    except (OSError, subprocess.SubprocessError):
        return set()
    return {
        name
        for name in ("add", "build", "list", "mcp", "audit", "withdraw")
        if name in text
    }


def start_tool_mcp(name: str, dest_root: Path) -> dict:
    root = _product_root()
    expected = Path(dest_root) / name / "mcp_server.py"
    return _start_product_job(
        [
            _product_python(root),
            "-m",
            "repoproof.cli",
            "tool",
            "mcp",
            name,
            "--dest-root",
            str(dest_root),
        ],
        kind="tool-mcp",
        label=f"生成 {name} MCP 适配器",
        expected_artifact=expected,
    )


def start_tool_audit(
    name: str,
    input_path: Path,
    expected_path: Path,
    dest_root: Path,
) -> dict:
    if not input_path.is_file() or not expected_path.is_file():
        return {"ok": False, "error": "新鲜输入和期望输出文件都必须存在。"}
    root = _product_root()
    return _start_product_job(
        [
            _product_python(root),
            "-m",
            "repoproof.cli",
            "tool",
            "audit",
            name,
            "--input",
            str(input_path),
            "--expected-file",
            str(expected_path),
            "--dest-root",
            str(dest_root),
        ],
        kind="tool-audit",
        label=f"审核 {name}",
        expected_artifact=Path(dest_root) / ".repoproof-release-decisions.jsonl",
    )


def start_tool_withdraw(name: str, reason: str, dest_root: Path) -> dict:
    if not reason.strip():
        return {"ok": False, "error": "请填写撤回原因。"}
    root = _product_root()
    return _start_product_job(
        [
            _product_python(root),
            "-m",
            "repoproof.cli",
            "tool",
            "withdraw",
            name,
            "--reason",
            reason.strip(),
            "--dest-root",
            str(dest_root),
        ],
        kind="tool-withdraw",
        label=f"撤回 {name}",
        expected_artifact=Path(dest_root) / ".repoproof-release-decisions.jsonl",
    )
