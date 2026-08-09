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
        ("结果报告(report.json)", "report.json"),
        ("运行清单(run_manifest.json)", "run_manifest.json"),
        ("执行记录(trace.jsonl)", "trace.jsonl"),
        ("AI 对话轨迹(trajectory.json)", "trajectory.json"),
        ("AI 对话轨迹·脱敏(trajectory.redacted.json)", "trajectory.redacted.json"),
        ("适配代码(agent_adapter.py)", "agent_adapter.py"),
        ("产物清单(adaptation_manifest.json)", "adaptation_manifest.json"),
        ("预注册说明(PREREGISTRATION.md)", "PREREGISTRATION.md"),
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


def run_ts(name: str) -> str:
    """运行目录名的尾缀时间戳(YYYYMMDD-HHMMSS,字典序=时间序)。"""
    return name[-15:]


def run_ts_human(name: str) -> str:
    s = run_ts(name)
    return f"{s[4:6]}-{s[6:8]} {s[9:11]}:{s[11:13]}" if len(s) == 15 else s


def local_runs() -> list[str]:
    """本地真实运行目录(有 report.json 的,最新在前)——持久事实,刷新不丢。

    按尾缀时间戳排序,不按目录名字母序:用户实测里 thefuzz(t)把
    刚跑完的 inflection(i)压到列表深处,新运行被"埋没"。"""
    root = repo_root() / "runs"
    # 不按任务前缀过滤:曾经的 "adopt-*" 硬编码让宿主级运行(t1-*)在
    # 运行进度/历史/结果报告三页集体隐身(用户实测 2026-08-09)——
    # 判据只有两条:目录名带时间戳 + 有 report.json。
    dirs = [d for d in root.glob("*-2*")
            if d.is_dir() and (d / "report.json").exists()]
    return [d.name for d in sorted(dirs, key=lambda x: run_ts(x.name), reverse=True)]


def local_run_verdict(name: str) -> str | None:
    try:
        return json.loads((repo_root() / "runs" / name / "report.json")
                          .read_text(encoding="utf-8")).get("final_verdict")
    except (OSError, json.JSONDecodeError):
        return None


def run_mode_zh(mode: str | None) -> str:
    """report.json 的 mode → 人话运行类型。用户实测:装配基线(无 AI、
    预期失败)混在「你的运行」里与真实运行无法区分,被误读成
    "gpt-5.5 失败了"。"""
    m = str(mode or "")
    if "no agent" in m or m.startswith("direct-adoption-baseline") or "baseline" in m and "real" not in m:
        return "装配基线·无AI(预期失败)"
    if m == "guided-repair":
        return "多轮修复"
    if m == "host-guided-repair":
        return "宿主级多轮修复"
    if m == "real-agent-baseline":
        return "单次运行"
    return m or "—"


def local_run_meta(name: str, root: Path | None = None) -> dict:
    """一次本地运行的轻量元信息(verdict/mode/model),供列表标注。

    model 取自 preflight 记录(装配基线/崩溃报告无预检 → None)——
    用户要求每条运行记录直观可见调用的具体模型型号。"""
    try:
        r = json.loads((((root or repo_root()) / "runs" / name / "report.json"))
                       .read_text(encoding="utf-8"))
        model = (r.get("preflight") or {}).get("model_name") or r.get("model")
        if not model:
            # 宿主级运行的 report 不含 preflight → 从 benchmarks/v2
            # runs.jsonl 按 run_id 反查(记录器是这类运行的事实源)
            from repoproof.persistence.bench_records import load_runs

            model = next((row.get("model") for row in load_runs(root or repo_root())
                          if row.get("run_id") == name), None)
        return {"verdict": r.get("final_verdict"), "mode": r.get("mode"),
                "model": model}
    except (OSError, json.JSONDecodeError):
        return {"verdict": None, "mode": None, "model": None}


def load_local_run(run_name: str) -> dict:
    root = repo_root() / "runs" / run_name
    rep = json.loads((root / "report.json").read_text(encoding="utf-8"))
    man = {}
    mp = root / "run_manifest.json"
    if mp.exists():
        man = json.loads(mp.read_text(encoding="utf-8"))
    if not man:
        # 宿主级运行只写 report.json(其字段是 manifest 的超集来源):
        # 缺 manifest 时用 report 顶替,agent 用量等区块不再显示"—"
        man = rep
    return {"report": rep, "manifest": man, "dir": str(root)}
