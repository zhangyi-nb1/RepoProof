"""真实运行入口(Gate 9B 最小版)。

- 只能运行「已冻结」的任务包(contracts/*.package.json 存在);
- 通过 subprocess 调既有 CLI `repoproof agent-run`(后台,页面刷新不杀);
- 模型密钥只从当前进程环境读取(REPOPROOF_*),UI 不接收、不保存、
  不显示密钥;缺失时给出启动脚本指引;
- 产品模式运行:结果写入 runs/,不进入 benchmark、不触碰历史 evidence;
- 单实例锁:runs/.ui_live.lock 存活时拒绝并发第二个 run。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

LOCK = "runs/.ui_live.lock"


def frozen_tasks(root: Path) -> list[str]:
    return sorted(
        p.name.replace(".package.json", "")
        for p in (root / "contracts").glob("*.package.json")
    )


def frozen_tasks_detailed(root: Path) -> list[dict]:
    """已冻结任务,按冻结时间最新在前;label 带人话时间,最新标 🆕。

    冻结时间 = *.package.json 的 mtime(freeze --full 最后写它,重新
    装配会刷新)。用户实测:纯英文 ID 按字母序排列,无法分辨"我刚
    冻结的是哪个"。"""
    import datetime as _dt

    items = [
        {"task_id": p.name.replace(".package.json", ""), "frozen_ts": p.stat().st_mtime}
        for p in (root / "contracts").glob("*.package.json")
    ]
    items.sort(key=lambda d: d["frozen_ts"], reverse=True)
    today = _dt.date.today()
    for i, it in enumerate(items):
        t = _dt.datetime.fromtimestamp(it["frozen_ts"])
        if t.date() == today:
            when = f"今天 {t:%H:%M}"
        elif (today - t.date()).days == 1:
            when = f"昨天 {t:%H:%M}"
        else:
            when = f"{t:%m-%d %H:%M}"
        it["label"] = f"{'🆕 ' if i == 0 else ''}{it['task_id']} · {when} 冻结"
    return items


def available_models() -> list[dict]:
    """从进程环境枚举可选模型(两组具名配置);密钥永不返回。"""
    out = []
    for prov in ("openai", "deepseek"):
        base = os.environ.get(f"REPOPROOF_{prov.upper()}_BASE")
        key = os.environ.get(f"REPOPROOF_{prov.upper()}_KEY")
        models = (os.environ.get(f"REPOPROOF_{prov.upper()}_MODELS") or "").split(",")
        if base and key:
            for m in [x.strip() for x in models if x.strip()]:
                out.append({"provider": prov, "model": m, "label": f"{m}({prov})"})
    if not out and provider_ready():
        out.append({"provider": "default", "model": os.environ.get("REPOPROOF_MODEL", "?"),
                    "label": os.environ.get("REPOPROOF_MODEL", "默认")})
    return out


def _env_for(provider: str, model: str) -> dict:
    env = dict(os.environ)
    if provider in ("openai", "deepseek"):
        env["REPOPROOF_API_BASE"] = os.environ[f"REPOPROOF_{provider.upper()}_BASE"]
        env["REPOPROOF_API_KEY"] = os.environ[f"REPOPROOF_{provider.upper()}_KEY"]
        env["REPOPROOF_MODEL"] = model
    return env


def provider_ready() -> bool:
    return bool(os.environ.get("REPOPROOF_API_KEY") and os.environ.get("REPOPROOF_API_BASE"))


def active_run(root: Path) -> dict | None:
    lock = root / LOCK
    if not lock.exists():
        return None
    try:
        info = json.loads(lock.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    # 完成判定优先看产物:最新 run 目录已有 report.json 即完成。
    # 竞态修复(用户实测):点击运行后、预检完成前 run 目录尚未创建,
    # "最新目录"是上一次已完成的运行——必须要求目录时间戳不早于本次
    # 启动时刻,否则并发第二次启动会被误放行。
    tid = str(info.get("task_id", ""))
    started = str(info.get("started_at", ""))
    run_dirs = sorted((root / "runs").glob(f"{tid}-2*"), reverse=True) if tid else []
    latest = run_dirs[0] if run_dirs else None
    fresh = bool(latest) and (not started or latest.name[-15:] >= started)
    info["latest_run"] = latest.name if (latest and fresh) else None
    info["report_ready"] = bool(latest and fresh and (latest / "report.json").exists())
    if info["report_ready"]:
        info["alive"] = False
        try:
            import json as _j
            info["verdict"] = _j.loads((latest / "report.json").read_text())["final_verdict"]
        except Exception:  # noqa: BLE001
            info["verdict"] = None
        return info
    # 无产物:探测进程(僵尸 defunct 一律视为已结束)
    try:
        import subprocess as _sp
        stat = _sp.run(["ps", "-p", str(int(info.get("pid", -1))), "-o", "stat="],
                       capture_output=True, text=True, timeout=5, check=False).stdout.strip()
        info["alive"] = bool(stat) and "Z" not in stat
    except Exception:  # noqa: BLE001
        info["alive"] = False
    return info


def start_run(root: Path, task_id: str, *, guided: bool = False,
              provider: str = "default", model: str | None = None) -> dict:
    """启动一次真实 agent 运行(后台)。返回状态 dict,绝不抛密钥。

    guided=True → RFC-008 §11 有界多轮修复(≤3 轮,公开测试反馈,
    最终仍走隐藏验证 + 干净复测 + 独立判定);False → 单次运行。"""
    if not provider_ready():
        return {"ok": False, "error": "模型连接未配置:请用 scripts/run_ui_live.sh 启动工作台"
                                       "(它会从你已有的本地配置注入连接信息,密钥不落盘)。"}
    if (info := active_run(root)) and info.get("alive"):
        return {"ok": False, "error": f"已有任务在运行(task={info.get('task_id')}),同时只允许一个。"}
    contract = root / "contracts" / f"{task_id}.yaml"
    if not (root / "contracts" / f"{task_id}.package.json").exists():
        return {"ok": False, "error": f"任务 {task_id} 未冻结,不能运行。"}
    log = root / "runs" / f"ui_live_{task_id}.log"
    log.parent.mkdir(exist_ok=True)
    cmd = "guided-run" if guided else "agent-run"
    proc = subprocess.Popen(
        [str(root / ".venv" / "bin" / "python"), "-m", "repoproof.cli",
         cmd, "--contract", str(contract)],
        stdout=log.open("w"), stderr=subprocess.STDOUT,
        cwd=str(root),
        env=_env_for(provider, model) if model else dict(os.environ),
        start_new_session=True,
    )
    import time as _time

    (root / LOCK).write_text(json.dumps(
        {"pid": proc.pid, "task_id": task_id, "log": str(log), "guided": guided,
         "model": model or os.environ.get("REPOPROOF_MODEL"),
         "started_at": _time.strftime("%Y%m%d-%H%M%S")}),
        encoding="utf-8")
    mode_note = "有界多轮修复(最多 3 轮,每轮按公开测试反馈改进)" if guided else "单次运行"
    return {"ok": True, "pid": proc.pid, "task_id": task_id, "guided": guided,
            "note": f"已在后台启动({mode_note}):AI 执行 → 冻结 → 独立验证 → 干净复测 → 最终判定。"
                    "页面刷新不会中断;完成后锁自动视为结束。"}


# ---- 宿主级 pilot(TESTPLAN-V2 T1;预注册 v2 规则)----
# v2(2026-08-09 用户决定):模型池内自由选择、同模型可重复;每一发
# 如实入账不挑选;fake 冒烟不计数。
HOST_PILOT = {
    "task_id": "t1-offerclaw-fastapi-mcp-v1",
    "contract": "benchmarks/v2/tasks/t1_fastapi_mcp/contract.yaml",
    "models": ["deepseek-v4-pro", "gpt-5.5", "gpt-5.6"],
    "prereg": "benchmarks/v2/preregistrations/T1-prereg-v2-20260809.md",
}


def host_pilot_state(root: Path) -> dict:
    """→ {done, by_model, next_global_order}。真实模型计数;fake 不算。"""
    from repoproof.persistence.bench_records import load_runs

    rows = [r for r in load_runs(root)
            if r.get("task_id") == HOST_PILOT["task_id"]
            and not str(r.get("model", "")).startswith("fake")]
    done = [{"run_id": r.get("run_id"), "model": r.get("model"),
             "verdict": r.get("verdict")} for r in rows]
    by_model = {m: sum(1 for r in rows if r.get("model") == m)
                for m in HOST_PILOT["models"]}
    return {"done": done, "by_model": by_model,
            "next_global_order": len(rows) + 1}


def provider_for_model(model: str) -> str | None:
    for m in available_models():
        if m["model"] == model:
            return m["provider"]
    return None


def host_run_argv(root: Path, *, run_order: int, run_index: int = 1) -> list[str]:
    """host-run 的 argv(纯函数,便于钉死:密钥绝不进 argv)。"""
    return [str(root / ".venv" / "bin" / "python"), "-m", "repoproof.cli", "host-run",
            "--contract", str(root / HOST_PILOT["contract"]),
            "--run-order", str(run_order), "--run-index", str(run_index)]


def start_host_run(root: Path, *, model: str, run_order: int, run_index: int = 1) -> dict:
    """启动宿主级正式 run(后台)。密钥只经进程环境,不落盘不显示。"""
    provider = provider_for_model(model)
    if provider is None:
        return {"ok": False,
                "error": f"当前工作台环境缺少 {model} 的连接配置(REPOPROOF_*);"
                         "请用 scripts/run_ui_live.sh 启动工作台。"}
    if (info := active_run(root)) and info.get("alive"):
        return {"ok": False, "error": f"已有任务在运行(task={info.get('task_id')}),同时只允许一个。"}
    log = root / "runs" / f"ui_live_host_{HOST_PILOT['task_id']}.log"
    log.parent.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        host_run_argv(root, run_order=run_order, run_index=run_index),
        stdout=log.open("w"), stderr=subprocess.STDOUT, cwd=str(root),
        env=_env_for(provider, model), start_new_session=True,
    )
    import time as _time

    (root / LOCK).write_text(json.dumps(
        {"pid": proc.pid, "task_id": HOST_PILOT["task_id"], "log": str(log),
         "guided": True, "mode": "host-guided", "model": model,
         "started_at": _time.strftime("%Y%m%d-%H%M%S")}), encoding="utf-8")
    return {"ok": True, "pid": proc.pid, "model": model, "run_order": run_order,
            "run_index": run_index,
            "note": "已在后台启动宿主级运行:装配 → 环境重建(约 2-3 分钟,这段安静是正常的)"
                    "→ 基线门禁 → AI 有界多轮修复(每轮额度独立)→ 独立验证 → 干净重放 "
                    "→ 最终判定。页面刷新不中断;完成后到「运行进度/结果报告」看结论。"}


def clear_lock_if_done(root: Path) -> None:
    info = active_run(root)
    if info and not info.get("alive"):
        (root / LOCK).unlink(missing_ok=True)


def export_bundle_for_run(root: Path, run_name: str) -> dict:
    """Gate C(RFC-008 §9.1):对一次已完成 run 导出 integration_bundle。

    通过 CLI 子进程执行(argv 列表、无 shell、超时、JSON 输出);
    EXPORT_ONLY——只写 runs/<id>/integration_bundle/,不碰用户项目。"""
    run_dir = (root / "runs" / run_name).resolve()
    if (root / "runs").resolve() not in run_dir.parents:
        return {"ok": False, "error": "非法 run 名称"}
    proc = subprocess.run(
        [str(root / ".venv" / "bin" / "python"), "-m", "repoproof.cli",
         "export-bundle", "--run-dir", str(run_dir), "--json"],
        capture_output=True, text=True, timeout=120, check=False, cwd=str(root),
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": (proc.stdout + proc.stderr)[-400:]}
    return out
