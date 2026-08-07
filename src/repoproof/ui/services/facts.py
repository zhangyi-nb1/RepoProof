"""UI 事实源(只读)。

规则(Gate 9A):事实只能来自 benchmark_summary.json、Evidence Bundle
(report / run_manifest / trace / adapter)、pyproject 版本与 Docker
守护进程状态。本模块不含任何写操作,不读取 API Key,不访问 LocalFlow。
"""

from __future__ import annotations

import io
import json
import subprocess
import zipfile
from functools import lru_cache
from pathlib import Path

from repoproof.runner.demo import CASES


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


@lru_cache(maxsize=1)
def repoproof_version() -> str:
    try:
        import tomllib

        data = tomllib.loads((repo_root() / "pyproject.toml").read_text(encoding="utf-8"))
        return data["project"]["version"]
    except Exception:  # noqa: BLE001
        return "unknown"


def docker_status() -> dict:
    """守护进程状态(只读探测,5s 超时);失败=不可用,不猜测。"""
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return {"available": True, "server_version": proc.stdout.strip()}
        return {"available": False, "server_version": None}
    except Exception:  # noqa: BLE001
        return {"available": False, "server_version": None}


def load_summary() -> dict:
    return json.loads((repo_root() / "docs" / "benchmark_summary.json").read_text(encoding="utf-8"))


def summary_row(case_id: str) -> dict | None:
    return next((r for r in load_summary()["runs"] if r["case_id"] == case_id), None)


# demo case -> benchmark_summary case_id(同一 run 的两种键)
CASE_TO_SUMMARY = {
    "frontmatter-v2-pass": "frontmatter-v2-agent-g72",
    "chonkie-agent-fail": "chonkie-agent-g3c",
    "bm25-agent-fail": "bm25-agent-g5",
}


def evidence_dir(case: str) -> Path:
    return repo_root() / CASES[case]["evidence"]


def load_report(case: str) -> dict:
    return json.loads((evidence_dir(case) / "report.json").read_text(encoding="utf-8"))


def load_run_manifest(case: str) -> dict:
    p = evidence_dir(case) / "run_manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def adapter_source(case: str) -> str | None:
    p = evidence_dir(case) / "agent_adapter.py"
    return p.read_text(encoding="utf-8") if p.exists() else None


def evidence_files(case: str) -> list[tuple[str, Path]]:
    """可下载的证据文件清单(存在的才列出)。"""
    labels = [
        ("运行报告 report.json", "report.json"),
        ("Run Manifest", "run_manifest.json"),
        ("Trace(JSONL,tamper-evident 链)", "trace.jsonl"),
        ("Agent 轨迹 trajectory", "trajectory.json"),
        ("Agent 轨迹 trajectory(脱敏)", "trajectory.redacted.json"),
        ("Agent Adapter 源码", "agent_adapter.py"),
        ("Adaptation Manifest", "adaptation_manifest.json"),
        ("预注册 PREREGISTRATION.md", "PREREGISTRATION.md"),
    ]
    out = []
    for label, name in labels:
        p = evidence_dir(case) / name
        if p.exists():
            out.append((label, p))
    return out


def bundle_zip_bytes(case: str) -> bytes:
    """把该案例的 Evidence Bundle 打包为 zip(内存中,只读源文件)。"""
    buf = io.BytesIO()
    root = evidence_dir(case)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                zf.write(p, arcname=f"{root.name}/{p.relative_to(root)}")
    return buf.getvalue()


def trace_preview(case: str, limit: int = 200) -> list[dict]:
    """Trace 前 N 行(解析失败的行按原文列出,不推断)。"""
    p = evidence_dir(case) / "trace.jsonl"
    if not p.exists():
        return []
    rows: list[dict] = []
    with p.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i >= limit:
                break
            try:
                ev = json.loads(line)
                rows.append({
                    "seq": ev.get("seq", i),
                    "actor": ev.get("actor", "—"),
                    "event": ev.get("event", "—"),
                    "摘要": str(ev.get("payload", ""))[:120],
                })
            except json.JSONDecodeError:
                rows.append({"seq": i, "actor": "?", "event": "unparsed", "摘要": line[:120]})
    return rows
