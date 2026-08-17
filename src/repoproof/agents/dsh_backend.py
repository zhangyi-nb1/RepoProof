"""DSH worker 的父侧执行壳:预算 watchdog + 进程组强杀 + 归因(DSH 阶段 4)。

**这是执行语义面**:预算在这里长牙 —— SDK 的 max_tokens 只是每请求出口
上限,总额(请求数/tokens/墙钟)由本模块对宿主侧 events.jsonl 增量对账、
超限即 SIGKILL 整个进程组(worker + runtime 一起死,"超限后无后台继续调用
模型"是拓扑保证,不是文本约定)。

归因优先级:强杀原因(wall_overrun / budget_overrun:轴)> worker 自报
(exit 0/2/3/4)> 协议破(stdout 不是恰好一行 result)。杀了就是杀了 ——
被杀发次的 trace 允许带 problems(终态丢失是杀的后果,不是 runtime 的罪)。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from repoproof.agents.dsh_events import DshTrace, normalize, selfcheck

WORKER = Path(__file__).with_name("dsh_worker.py")

# ---- 拓扑闸(阶段 5)。不可信平面的一切落点必须离开裁决面与封存池:
# 仓树(oracle 判据、验证器源码、台账、证据都在里面)与 d5-hunt 封存池。
# cwd 不是沙箱(ADR §4),但**我们递出去的路径**是我们的责任 —— 这道闸
# 拦的是"配置手滑把 workspace 指进仓里"这一最近的失效方向。
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _forbidden_roots() -> tuple[Path, ...]:
    return (_REPO_ROOT, Path.home() / "RepoProofArchive")


def _assert_job_topology(job: dict) -> None:
    for key in ("workspace", "events_path", "session_root"):
        p = Path(job[key]).resolve()
        for root in _forbidden_roots():
            if p == root or root in p.parents:
                raise ValueError(
                    f"{key} 指进受保护根 {root} —— 不可信执行平面不得落在"
                    f"裁决面/封存池里:{p}")


# 环境 allowlist(阶段 5,N5):worker(及其子孙 runtime、模型驱动的 bash)
# 继承的环境**只有**这三枚 + 调用方显式传入的(如 DEEPSEEK_API_KEY,由
# 用户注入、AI 不经手)。父进程的其余环境 —— 别家 provider 的 key、token、
# 仓路径 —— 一律不过闸。
_ENV_ALLOWLIST = ("PATH", "HOME", "TMPDIR")


def worker_env(extra: dict | None = None) -> dict:
    env = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}
    env.update(extra or {})
    return env


@dataclass
class DshBudget:
    """总额预算(逐批在预注册里冻结;None = 该轴不设限)。"""
    max_wall_seconds: float | None = None
    max_logical_requests: int | None = None
    max_llm_attempts: int | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None


@dataclass
class DshRunReport:
    exit_code: int | None
    attribution: str          # ok | wall_overrun | budget_overrun:<轴> |
                              # worker_error:<kind> | worker_unexpected |
                              # worker_protocol_breach
    result: dict | None       # worker 单行 result(解析成功时)
    trace: DshTrace
    selfcheck_problems: list = field(default_factory=list)
    stderr_tail: str = ""
    killed: bool = False
    orphan_count: int = 0     # 收尾清点(应为 0;>0 本身就是发现)


def _kill_group(pid: int) -> None:
    """SIGKILL 整组。macOS 对含特定状态成员的组会整体抛 EPERM(2026-08-17
    C10 实测:墙钟刀首次砍真 runtime-bin 就撞上)—— 落不下的刀等于没有刀,
    回退为 pgrep -g 列组员逐个点杀,组长再补一刀。"""
    try:
        os.killpg(pid, signal.SIGKILL)
        return
    except ProcessLookupError:
        return
    except PermissionError:
        pass
    got = subprocess.run(["pgrep", "-g", str(pid)], capture_output=True, text=True)
    members = [int(x) for x in got.stdout.split()] if got.returncode == 0 else []
    for member in {*members, pid}:
        try:
            os.kill(member, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _read_new_lines(path: Path, offset: int, buf: str) -> tuple[list[str], int, str]:
    """增量读:只取完整行,半行留在 buf(逐条 flush 也可能被读在行中间)。"""
    if not path.exists():
        return [], offset, buf
    with path.open("r", encoding="utf-8") as f:
        f.seek(offset)
        chunk = f.read()
        offset = f.tell()
    buf += chunk
    lines = buf.split("\n")
    return [ln for ln in lines[:-1] if ln.strip()], offset, lines[-1]


def _over_budget(trace: DshTrace, b: DshBudget) -> str | None:
    c, u = trace.counters, trace.usage_totals
    axes = (
        ("logical_requests", b.max_logical_requests, c.get("logical_requests", 0)),
        ("llm_attempts", b.max_llm_attempts, c.get("llm_attempts", 0)),
        ("input_tokens", b.max_input_tokens, u.get("input_tokens", 0)),
        ("output_tokens", b.max_output_tokens, u.get("output_tokens", 0)),
    )
    for name, cap, got in axes:
        if cap is not None and got > cap:
            return name
    return None


def run_dsh_worker(job: dict, *, worker_python: str | Path,
                   budget: DshBudget | None = None,
                   extra_env: dict | None = None,
                   poll_interval: float = 0.25,
                   worker_argv: list | None = None) -> DshRunReport:
    """spawn worker(独立进程组)→ 增量对账 → 超限强杀 → 归因。

    `worker_argv` 只给测试注入假 worker 用(watchdog 的行为钉不该吃真
    runtime);生产路径一律缺省 = 封存 venv python + dsh_worker.py。
    """
    budget = budget or DshBudget()
    assert "api_key" not in job, "key 只经进程环境注入,不进 job spec(铁律)"
    _assert_job_topology(job)
    events_path = Path(job["events_path"])
    events_path.parent.mkdir(parents=True, exist_ok=True)

    env = worker_env(extra_env)
    argv = worker_argv or [str(worker_python), str(WORKER)]
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True, env=env)
    try:
        proc.stdin.write(json.dumps(job))
        proc.stdin.flush()
    except BrokenPipeError:
        pass
    finally:
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        # 真 worker 靠 stdin EOF 才开工,必须现在关;关完置 None,
        # 否则 communicate() 会去 flush 已关句柄(ValueError)。
        proc.stdin = None

    t0 = time.monotonic()
    raw: list[str] = []
    offset, buf = 0, ""
    killed_for: str | None = None
    while proc.poll() is None:
        time.sleep(poll_interval)
        new, offset, buf = _read_new_lines(events_path, offset, buf)
        raw.extend(new)
        wall = time.monotonic() - t0
        if budget.max_wall_seconds is not None and wall > budget.max_wall_seconds:
            killed_for = "wall_overrun"
        else:
            axis = _over_budget(normalize(raw), budget)
            if axis is not None:
                killed_for = f"budget_overrun:{axis}"
        if killed_for is not None:
            _kill_group(proc.pid)
            break

    out, err = proc.communicate()
    new, offset, buf = _read_new_lines(events_path, offset, buf)
    raw.extend(new)
    if buf.strip():
        raw.append(buf)
    trace = normalize(raw)

    result: dict | None = None
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    if len(lines) == 1:
        try:
            parsed = json.loads(lines[0])
            if parsed.get("protocol") == "dsh-worker-v1":
                result = parsed
        except json.JSONDecodeError:
            pass

    if killed_for is not None:
        attribution = killed_for
    elif result is None:
        attribution = "worker_protocol_breach"
    elif proc.returncode == 0:
        attribution = "ok"
    elif proc.returncode == 4:
        attribution = "worker_unexpected"
    else:
        attribution = f"worker_error:{result.get('error_kind')}"

    # 收尾:再补一刀防僵尸,留 0.2s 沉降窗再清点(SIGKILL 送达与 pgrep
    # 之间存在竞态,不留窗会把正在死的进程数成孤儿)
    _kill_group(proc.pid)
    time.sleep(0.2)
    marker = str(events_path.parent)
    sweep = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
    orphans = [p for p in sweep.stdout.split() if p.strip()]

    return DshRunReport(
        exit_code=proc.returncode,
        attribution=attribution,
        result=result,
        trace=trace,
        selfcheck_problems=selfcheck(trace),
        stderr_tail=(err or "")[-2000:],
        killed=killed_for is not None,
        orphan_count=len(orphans),
    )
