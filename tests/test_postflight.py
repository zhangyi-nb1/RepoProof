"""增强①钉死:postflight 进程清扫(T3 批 1 证据,2026-08-11)。

铁律:只清 [run 后新增 ∧ 带调试标记] 的浏览器进程及其子进程;
用户自己的浏览器(先存 / 无标记)绝不触碰。
"""
from __future__ import annotations

import re
import subprocess
import time
import uuid

from repoproof.harness.postflight import (
    ProcInfo,
    browser_pids,
    enabled,
    executable_portion,
    parse_ps,
    plan_sweep,
    sweep,
)

M = ("--remote-debugging-port", "--headless")


def _p(pid, ppid, cmd):
    return ProcInfo(pid=pid, ppid=ppid, command=cmd)


def test_plan_never_touches_preexisting_browser():
    procs = [_p(100, 1, "/App/Google Chrome --remote-debugging-port=9222")]
    plan = plan_sweep({100}, procs, markers=M)
    assert plan["kill"] == [] and plan["skipped"] == []


def test_plan_kills_new_debug_browser_and_child_closure():
    procs = [
        _p(200, 1, "/App/Google Chrome --headless=new --remote-debugging-port=9333"),
        _p(201, 200, "/App/Google Chrome Helper (Renderer) --type=renderer"),
        _p(202, 201, "/App/Google Chrome Helper (GPU) --type=gpu-process"),
    ]
    plan = plan_sweep(set(), procs, markers=M)
    assert {p.pid for p in plan["kill"]} == {200, 201, 202}
    assert plan["skipped"] == []


def test_plan_skips_new_user_browser_without_markers():
    procs = [
        _p(300, 1, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        _p(301, 300, "/App/Google Chrome Helper (Renderer) --type=renderer"),
    ]
    plan = plan_sweep(set(), procs, markers=M)
    assert plan["kill"] == []
    assert {p.pid for p in plan["skipped"]} == {300, 301}


def test_plan_mixed_user_and_harness_browsers():
    """用户 Chrome 存活 + harness 残留并存:只清后者。"""
    procs = [
        _p(400, 1, "/App/Google Chrome"),                       # 用户,先存
        _p(401, 400, "/App/Google Chrome Helper --type=renderer"),   # 用户新 tab
        _p(500, 1, "/App/chromium --headless=new --user-data-dir=/tmp/rp_x"),
        _p(501, 500, "/App/chromium Helper --type=renderer"),
    ]
    plan = plan_sweep({400}, procs, markers=("--headless",))
    assert {p.pid for p in plan["kill"]} == {500, 501}
    assert {p.pid for p in plan["skipped"]} == {401}


def test_parse_ps_tolerates_garbage_lines():
    procs = parse_ps("  12  1 /bin/thing --x\nPID PPID COMMAND\n\nbad line\n")
    assert procs == [ProcInfo(12, 1, "/bin/thing --x")]


def test_browser_pids_uses_pattern():
    procs = [_p(1, 0, "chromium --a"), _p(2, 0, "vim"), _p(3, 0, "Google Chrome H")]
    assert browser_pids(procs) == {1, 3}


# ---- 判别面收窄钉死(order-34 实证:报告面被用户 Claude 会话污染)----

CLAUDE_SESSION_CMD = (
    "/Applications/Claude.app/Contents/Helpers/disclaimer "
    "/Users/u/Library/Application Support/Claude/claude-code/2.1.222"
    "/claude.app/Contents/MacOS/claude --output-format stream-json "
    "--allowedTools mcp__claude-in-chrome__request_credentials,"
    "mcp__claude-in-chrome__navigate --permission-mode bypassPermissions"
)


def test_executable_portion_splits_at_first_flag():
    assert executable_portion("/App/Google Chrome --headless=new --x") == "/App/Google Chrome"
    assert executable_portion("/App/Google Chrome") == "/App/Google Chrome"
    assert executable_portion("python3 -c import time") == "python3"


def test_claude_session_mentioning_chrome_in_args_is_not_a_browser():
    """order-34 一手实证:命令行**参数**含 mcp__claude-in-chrome__ 工具名的
    用户 Claude Code 会话被计入 skipped_new/leftover(4 枚)。判别面收窄到
    可执行体段后,此类进程完全不入候选(非 kill 非 skipped)。"""
    procs = [_p(600, 1, CLAUDE_SESSION_CMD)]
    assert browser_pids(procs) == set()
    plan = plan_sweep(set(), procs, markers=M)
    assert plan["kill"] == [] and plan["skipped"] == []


def test_real_browser_with_chrome_free_args_still_matched():
    """反向哨兵:判别只看可执行体段——浏览器带任意参数照常命中,
    非浏览器可执行体即使参数满是 chrome 字样也不命中。"""
    procs = [
        _p(700, 1, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
                   "--headless=new --user-data-dir=/tmp/rp_x"),
        _p(701, 1, "/usr/bin/tail -f /Applications/Google Chrome.app/log"),
    ]
    assert browser_pids(procs) == {700}
    plan = plan_sweep(set(), procs, markers=("--headless",))
    assert {p.pid for p in plan["kill"]} == {700}
    assert plan["skipped"] == []


def _nonce_exe(tmp_path, nonce):
    """以 nonce 命名的可执行体(sh 包装脚本)——判别面收窄后,模式须
    命中**可执行体段**,nonce 放参数里不再算浏览器(见钉死组)。
    不能用符号链接到 python:macOS framework 构建启动时 re-exec 为
    Python.app/…/MacOS/Python 并改写 argv[0],链接名进不了 ps;
    sh 脚本经 shebang 执行,ps 显示 "/bin/sh <脚本路径> <参数>",
    脚本路径(含 nonce)恰在可执行体段内,与浏览器真实形态同构。"""
    exe = tmp_path / f"{nonce}-bin"
    exe.write_text("#!/bin/sh\nwhile :; do sleep 5; done\n")
    exe.chmod(0o755)
    return str(exe)


def test_sweep_kills_real_marked_dummy_and_reports(tmp_path):
    """机制实测:清掉一个新增的带标记假进程,报告结构完整。"""
    nonce = f"rp-sweep-dummy-{uuid.uuid4().hex[:8]}"
    pat = re.compile(re.escape(nonce))
    before = browser_pids(pattern=pat)
    assert before == set()
    proc = subprocess.Popen(  # noqa: S603 — 测试内固定 argv
        [_nonce_exe(tmp_path, nonce), "--remote-debugging-port=1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if browser_pids(pattern=pat):
                break
            time.sleep(0.1)
        report = sweep(before, pattern=pat, markers=("--remote-debugging-port",),
                       grace_s=2.0)
        assert [k["pid"] for k in report["killed"]] == [proc.pid]
        assert report["leftover_new_pids"] == []
        proc.wait(timeout=10)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_sweep_skips_real_unmarked_dummy(tmp_path):
    """无标记的新进程只记 skipped,不杀。"""
    nonce = f"rp-sweep-user-{uuid.uuid4().hex[:8]}"
    pat = re.compile(re.escape(nonce))
    proc = subprocess.Popen(  # noqa: S603
        [_nonce_exe(tmp_path, nonce)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            if browser_pids(pattern=pat):
                break
            time.sleep(0.1)
        report = sweep(set(), pattern=pat, markers=M, grace_s=0.5)
        assert report["killed"] == []
        assert [s["pid"] for s in report["skipped_new"]] == [proc.pid]
        assert proc.poll() is None, "无标记进程绝不能被杀"
    finally:
        proc.kill()


def test_toggle_disables(monkeypatch):
    monkeypatch.setenv("REPOPROOF_POSTFLIGHT_SWEEP", "0")
    assert not enabled()
    monkeypatch.delenv("REPOPROOF_POSTFLIGHT_SWEEP")
    assert enabled()
