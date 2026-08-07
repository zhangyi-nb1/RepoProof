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
    # 完成判定优先看产物:最新 run 目录已有 report.json 即完成
    tid = str(info.get("task_id", ""))
    run_dirs = sorted((root / "runs").glob(f"{tid}-2*"), reverse=True) if tid else []
    latest = run_dirs[0] if run_dirs else None
    info["latest_run"] = latest.name if latest else None
    info["report_ready"] = bool(latest and (latest / "report.json").exists())
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


def start_run(root: Path, task_id: str) -> dict:
    """启动一次真实 agent 运行(后台)。返回状态 dict,绝不抛密钥。"""
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
    proc = subprocess.Popen(
        [str(root / ".venv" / "bin" / "python"), "-m", "repoproof.cli",
         "agent-run", "--contract", str(contract)],
        stdout=log.open("w"), stderr=subprocess.STDOUT,
        cwd=str(root), env=dict(os.environ), start_new_session=True,
    )
    (root / LOCK).write_text(json.dumps(
        {"pid": proc.pid, "task_id": task_id, "log": str(log)}), encoding="utf-8")
    return {"ok": True, "pid": proc.pid, "task_id": task_id,
            "note": "已在后台启动:AI 执行 → 冻结 → 独立验证 → 干净复测 → 最终判定。"
                    "页面刷新不会中断;完成后锁自动视为结束。"}


def clear_lock_if_done(root: Path) -> None:
    info = active_run(root)
    if info and not info.get("alive"):
        (root / LOCK).unlink(missing_ok=True)
