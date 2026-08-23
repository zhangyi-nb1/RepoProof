"""真实运行入口(Gate 9B 最小版)。

- 只能运行「已冻结」的任务包(contracts/*.package.json 存在);
- 通过 subprocess 调既有 CLI `repoproof agent-run`(后台,页面刷新不杀);
- 模型密钥只从当前进程环境读取(REPOPROOF_*),UI 不接收、不保存、
  不显示密钥;缺失时给出启动脚本指引;
- Lab 本地采用运行:结果写入 runs/,不进入 benchmark、不触碰历史 evidence;
- 单实例锁:runs/.ui_live.lock 存活时拒绝并发第二个 run。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from repoproof.persistence.bench_records import EXPLORATORY_BATCH

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
        return {"ok": False, "error": "模型连接未配置:请用 scripts/run_lab_ui_live.sh 启动实验台"
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


# ---- 宿主级正式任务 T1–T4(TESTPLAN-V2)----
# v2(2026-08-09 用户决定):模型池内自由选择、同模型可重复;每一发
# 如实入账不挑选;fake 冒烟不计数。
# 2026-08-11:由 T1 单任务泛化为 T1–T4 注册表(用户要在 UI 里对各阶段
# 重复发以观察方差)。每项指向该阶段**当前冻结版**的契约与预注册。
MODEL_POOL = ["deepseek-v4-pro", "gpt-5.5", "gpt-5.6"]

HOST_TASKS: dict[str, dict] = {
    "T1": {
        "key": "T1", "task_id": "t1-offerclaw-fastapi-mcp-v1",
        "title": "T1 · OfferClaw × fastapi-mcp(复杂度校准)",
        "contract": "benchmarks/v2/tasks/t1_fastapi_mcp/contract.yaml",
        "prereg": "benchmarks/v2/preregistrations/T1-prereg-v2-20260809.md",
        "models": MODEL_POOL, "runnable": True,
    },
    "T2": {
        "key": "T2", "task_id": "t2-offerclaw-open-deep-research-v4",
        "title": "T2 · OfferClaw × Open Deep Research(v4 冻结版)",
        "contract": "benchmarks/v2/tasks/t2_open_deep_research_v4/contract.yaml",
        "prereg": "benchmarks/v2/preregistrations/T2v4-prereg-20260810.md",
        "models": MODEL_POOL, "runnable": True,
    },
    "T3": {
        "key": "T3", "task_id": "t3-offerclaw-browser-use-v5",
        "title": "T3 · OfferClaw × Browser Use(v5 冻结版)",
        "contract": "benchmarks/v2/tasks/t3_browser_use_v5/contract.yaml",
        "prereg": "benchmarks/v2/preregistrations/T3v5-prereg-20260811.md",
        "models": MODEL_POOL, "runnable": True,
    },
    # T4 = Sequential Feature Rollback 专项:**零模型调用的确定性工程实验**,
    # 被测对象是 RepoProof 自身,台账走 rollback_experiments.jsonl(不入
    # runs.jsonl)。真栈 R-A..R-E 是一次性作业,无参数化 runner ⇒ UI 只读。
    "T4": {
        "key": "T4", "task_id": "t4-feature-rollback-v1",
        "title": "T4 · Sequential Feature Rollback(确定性专项)",
        "contract": None,
        "prereg": "benchmarks/v2/preregistrations/T4v1-prereg-20260811.md",
        "models": [], "runnable": False,
        "ledger": "benchmarks/v2/rollback_experiments.jsonl",
        "pin_suite": "tests/test_t4_feature_stack.py",
        "why_not_runnable":
            "零模型调用的确定性实验,**没有方差可观察**;真栈 R-A..R-E 为一次性"
            "工程作业(建 S0→S3 栈后逐实验执行),未参数化为可重跑 runner。"
            "此处只读台账;可复跑 22 项机器钉死测试验证机器本身未退化。",
    },
}

# 向后兼容:旧代码/测试仍以 T1 为 HOST_PILOT
HOST_PILOT = HOST_TASKS["T1"]


def host_task(key: str) -> dict:
    if key not in HOST_TASKS:
        raise KeyError(f"未知宿主任务:{key}(可选 {sorted(HOST_TASKS)})")
    return HOST_TASKS[key]


def _real_rows(root: Path, task_id: str) -> list[dict]:
    """该任务的真实模型发次(fake 冒烟不计),已连接人工再分类。"""
    from repoproof.persistence.bench_records import adjudicated_runs

    return [r for r in adjudicated_runs(root)
            if r.get("task_id") == task_id
            and not str(r.get("model", "")).startswith("fake")]


def host_task_state(root: Path, key: str = "T1") -> dict:
    """→ {done, by_model, next_global_order}。真实模型计数;fake 不算。

    `next_global_order` 是**全台账**的下一个执行序(跨任务全局单调),与
    TESTPLAN §9 的 run_order 语义一致——不是本任务内的计数。
    """
    from repoproof.persistence.bench_records import load_runs

    t = host_task(key)
    rows = _real_rows(root, t["task_id"])
    done = [{"run_id": r.get("run_id"), "model": r.get("model"),
             "verdict": r.get("verdict"),
             "effective_verdict": r.get("effective_verdict"),
             "exploratory": r.get("batch") == EXPLORATORY_BATCH,
             "invalidated": r.get("adjudication") is not None} for r in rows]
    by_model = {m: sum(1 for r in rows if r.get("model") == m) for m in t["models"]}
    all_real = [r for r in load_runs(root)
                if not str(r.get("model", "")).startswith("fake")]
    # 本阶段更早任务版本的发次:**不进本面板**(不同 task_version 不可互比,
    # TESTPLAN §8),但必须明示条数——否则用户看到 n=1 会以为发次丢了。
    older: dict[str, int] = {}
    for r in all_real:
        tid = str(r.get("task_id", ""))
        if tid.startswith(f"{key.lower()}-") and tid != t["task_id"]:
            older[tid] = older.get(tid, 0) + 1
    return {"done": done, "by_model": by_model, "older_versions": older,
            "next_global_order": len(all_real) + 1}


def host_pilot_state(root: Path) -> dict:
    """向后兼容别名(T1)。新代码用 host_task_state(root, key)。"""
    return host_task_state(root, "T1")


def next_run_index(root: Path, key: str, model: str) -> int:
    """该 (任务, 模型) 的下一个重复序号——观察方差时的第 n 发。"""
    rows = _real_rows(root, host_task(key)["task_id"])
    return sum(1 for r in rows if r.get("model") == model) + 1


def variance_summary(root: Path, key: str) -> list[dict]:
    """按模型汇总重复发的离散度(观察方差用)。

    判决计数走 `effective_verdict`(已连接 adjudications),**已判无效的
    假 PASS 不计入通过**;数值指标给 n/min/max/均值,n<3 时明确标注
    "不足以谈方差"(项目纪律:n<3 不排名)。
    """
    from repoproof.persistence.bench_records import PASS_VERDICTS

    METRICS = (("input_tokens", "读入"), ("output_tokens", "产出"),
               ("model_calls", "调用"), ("rounds_used", "轮数"),
               ("wall_time", "墙钟秒"))
    out: list[dict] = []
    for model in host_task(key)["models"]:
        rows = [r for r in _real_rows(root, host_task(key)["task_id"])
                if r.get("model") == model]
        if not rows:
            continue
        verdicts: dict[str, int] = {}
        for r in rows:
            v = str(r.get("effective_verdict"))
            verdicts[v] = verdicts.get(v, 0) + 1
        stats = {}
        for field, label in METRICS:
            vals = [r[field] for r in rows
                    if isinstance(r.get(field), (int, float))]
            if vals:
                stats[label] = {"n": len(vals), "min": min(vals), "max": max(vals),
                                "mean": round(sum(vals) / len(vals), 1),
                                "spread": round(max(vals) - min(vals), 1)}
        out.append({
            "model": model, "n": len(rows), "verdicts": verdicts,
            "passes": sum(1 for r in rows
                          if r.get("effective_verdict") in PASS_VERDICTS),
            # 其中多少发是预注册之外的探索性加发(闸门不计,但方差要看)
            "exploratory": sum(1 for r in rows
                               if r.get("batch") == EXPLORATORY_BATCH),
            "stats": stats,
            "enough_for_variance": len(rows) >= 3,
        })
    return out


def provider_for_model(model: str) -> str | None:
    for m in available_models():
        if m["model"] == model:
            return m["provider"]
    return None


def host_run_argv(root: Path, *, run_order: int, run_index: int = 1,
                  task_key: str = "T1",
                  batch: str = EXPLORATORY_BATCH) -> list[str]:
    """host-run 的 argv(纯函数,便于钉死:密钥绝不进 argv)。

    `batch` 默认 EXPLORATORY_UNPREREGISTERED:**从 UI 发起的加发一律是预注册
    之外的探索性发次**(TESTPLAN §8 要求正式批次先冻结再发射),打标后闸门
    不计——不打标就会与预注册批次在台账里混为一谈。
    """
    t = host_task(task_key)
    if not t["runnable"]:
        raise ValueError(f"{task_key} 不可经 UI 发起:{t['why_not_runnable']}")
    return [str(root / ".venv" / "bin" / "python"), "-m", "repoproof.cli", "host-run",
            "--contract", str(root / t["contract"]),
            "--run-order", str(run_order), "--run-index", str(run_index),
            "--batch", batch]


def start_host_run(root: Path, *, model: str, run_order: int, run_index: int = 1,
                   task_key: str = "T1") -> dict:
    """启动宿主级正式 run(后台)。密钥只经进程环境,不落盘不显示。"""
    t = host_task(task_key)
    if not t["runnable"]:
        return {"ok": False, "error": f"{task_key} 不可经 UI 发起:{t['why_not_runnable']}"}
    provider = provider_for_model(model)
    if provider is None:
        return {"ok": False,
                "error": f"当前工作台环境缺少 {model} 的连接配置(REPOPROOF_*);"
                         "请用 scripts/run_lab_ui_live.sh 启动实验台。"}
    if (info := active_run(root)) and info.get("alive"):
        return {"ok": False, "error": f"已有任务在运行(task={info.get('task_id')}),同时只允许一个。"}
    log = root / "runs" / f"ui_live_host_{t['task_id']}.log"
    log.parent.mkdir(exist_ok=True)
    proc = subprocess.Popen(
        host_run_argv(root, run_order=run_order, run_index=run_index, task_key=task_key),
        stdout=log.open("w"), stderr=subprocess.STDOUT, cwd=str(root),
        env=_env_for(provider, model), start_new_session=True,
    )
    import time as _time

    (root / LOCK).write_text(json.dumps(
        {"pid": proc.pid, "task_id": t["task_id"], "log": str(log),
         "guided": True, "mode": "host-guided", "model": model,
         "task_key": task_key,
         "started_at": _time.strftime("%Y%m%d-%H%M%S")}), encoding="utf-8")
    return {"ok": True, "pid": proc.pid, "model": model, "run_order": run_order,
            "run_index": run_index, "task_key": task_key,
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
