"""postflight 进程清扫(T3 批 1 增强①,2026-08-11 用户批准)。

证据(§38.2 重复证据满足):T3 首轮四发,**每发 run 结束后残留
agent 启动的 Chrome 5-8 枚**,由操作员在 run 间人工清扫——会话销毁
只删工作树,不回收会话内进程拉起的浏览器;属"外部副作用治理",与
T3 任务主题同源。

设计约束(按批准时议定):
1. **时序**:只在 run 收尾(_finish,独立验证与 clean replay 全部
   完成之后)执行——绝不干扰 oracle 的 PID 差集测量(h6 在验证阶段
   会话内自测,先于本清扫);
2. **保守判别**:只杀 [run 开始后新增] ∧ [命令行带浏览器调试标记
   (--remote-debugging-port / --headless / 临时 user-data-dir)] 的
   进程,及其子进程(单次 ps 快照上闭包);用户自己的 Chrome(先于
   run 存在,或无调试标记)永不触碰,如实记入 skipped;
3. 消融/关闭:REPOPROOF_POSTFLIGHT_SWEEP=0;
4. 结果入 trace 事件与 report(不静默)。
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass

BROWSER_PATTERN = re.compile(r"chrome|chromium", re.IGNORECASE)


def executable_portion(command: str) -> str:
    """命令行的可执行体段(到第一个 ` -` 参数边界为止)。

    浏览器判别只看这一段:Claude Code 会话的**参数**里含
    ``mcp__claude-in-chrome__…`` 工具名,按全命令行匹配会把用户会话
    误计入浏览器族(order-34 实证:skipped_new/leftover 报告面被 4 个
    用户进程污染;杀伤决策由标记门保住,零误杀)。macOS 浏览器路径
    含空格(``Google Chrome.app``),故按参数边界而非空格切;路径
    本身含 " -" 的极端情形只会把匹配段截短——宁漏报不误报,与
    "绝不触碰用户进程"同向保守。
    """
    return command.split(" -", 1)[0]

# 调试标记 = 本项目 cdp_url 外接架构(及一切自动化启动)的命令行特征;
# 用户手开的 Chrome 不带这些参数。
DEBUG_MARKERS = (
    "--remote-debugging-port",
    "--headless",
    "--user-data-dir=/tmp",
    "--user-data-dir=/var/folders",
)


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    ppid: int
    command: str


def enabled() -> bool:
    return os.environ.get("REPOPROOF_POSTFLIGHT_SWEEP", "").strip() != "0"


def list_procs() -> list[ProcInfo]:
    # ww 必须给:procps(Linux)的 ps 尊重 COLUMNS 环境变量,而 pytest
    # 会设 COLUMNS=80 —— 长命令行被截到 80 列,nonce/调试标记全落在
    # 截断区外,清扫就"看不见"目标进程(CI Linux 预演实测;macOS 的
    # BSD ps 不理 COLUMNS,本机侥幸全绿)。写成 BSD 风格 `axww`:
    # macOS 对 `-ww ax` 报 illegal argument,`axww` 两家都认、无限宽。
    out = subprocess.run(  # noqa: S603 — 固定 argv,只读查询
        ["ps", "axww", "-o", "pid=,ppid=,command="],
        capture_output=True, text=True, check=False).stdout
    return parse_ps(out)


def parse_ps(text: str) -> list[ProcInfo]:
    procs: list[ProcInfo] = []
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        procs.append(ProcInfo(pid=int(parts[0]), ppid=int(parts[1]), command=parts[2]))
    return procs


def browser_pids(procs: list[ProcInfo] | None = None,
                 pattern: re.Pattern = BROWSER_PATTERN) -> set[int]:
    """浏览器族 PID 集:模式只对**可执行体段**判别(实现无关)。"""
    return {p.pid for p in (procs if procs is not None else list_procs())
            if pattern.search(executable_portion(p.command))}


def plan_sweep(
    before: set[int],
    procs: list[ProcInfo],
    *,
    pattern: re.Pattern = BROWSER_PATTERN,
    markers: tuple[str, ...] = DEBUG_MARKERS,
) -> dict:
    """纯函数:从单次进程快照算出 kill/skip 集合(可测试,无副作用)。

    kill = 新增(∉before)且命中调试标记的浏览器进程,加上其子进程闭包
    (Chrome Helper 是主进程的直接子进程,ppid 链在同一快照内可达);
    skip = 新增但无标记且父进程不在 kill 集(多半是用户自己刚开的浏览器)。
    """
    me = os.getpid()
    candidates = [p for p in procs
                  if pattern.search(executable_portion(p.command))
                  and p.pid not in before and p.pid > 1 and p.pid != me]
    kill_ids = {p.pid for p in candidates
                if any(m in p.command for m in markers)}
    changed = True
    while changed:  # 子进程闭包(helper 的 helper)
        changed = False
        for p in candidates:
            if p.pid not in kill_ids and p.ppid in kill_ids:
                kill_ids.add(p.pid)
                changed = True
    kill = [p for p in candidates if p.pid in kill_ids]
    skipped = [p for p in candidates if p.pid not in kill_ids]
    return {"kill": kill, "skipped": skipped}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep(
    before: set[int],
    *,
    pattern: re.Pattern = BROWSER_PATTERN,
    markers: tuple[str, ...] = DEBUG_MARKERS,
    grace_s: float = 3.0,
) -> dict:
    """执行清扫:SIGTERM → 宽限 → SIGKILL;返回可入账的结构化报告。

    报告只含 pid 与命令行前 160 字符(临时 profile 路径,无个人数据)。
    """
    plan = plan_sweep(before, list_procs(), pattern=pattern, markers=markers)
    for p in plan["kill"]:
        try:
            os.kill(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline and any(_alive(p.pid) for p in plan["kill"]):
        time.sleep(0.2)
    forced = []
    for p in plan["kill"]:
        if _alive(p.pid):
            try:
                os.kill(p.pid, signal.SIGKILL)
                forced.append(p.pid)
            except (ProcessLookupError, PermissionError):
                pass
    leftover = sorted(browser_pids(pattern=pattern)
                      - before - {p.pid for p in plan["kill"]})
    return {
        "killed": [{"pid": p.pid, "command": p.command[:160]} for p in plan["kill"]],
        "sigkill_forced": forced,
        "skipped_new": [{"pid": p.pid, "command": p.command[:160]}
                        for p in plan["skipped"]],
        "leftover_new_pids": leftover,
    }
