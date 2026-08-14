"""拓扑核验 —— A1 的地基,现场查,不靠约定。

整套主张只有一句话:**上游不在 agent 够得着的地方**。这句话若不成立,
后面的回执、四道谓词、八条负控就全都是装饰 —— agent 可以直接 import 上游
自己算,完全不必来敲门,而"它没来敲门"会被判成 U3 覆盖不足,读起来像是
它偷懒,其实是它根本不需要。

所以这里逐条查四件事,任一不成立就**拒绝出数**:

    T1  fixture 不在任何钉版 wheelhouse 里
    T2  干净解释器(不注入路径)import 不到它
    T3  fixture 住在策略拒绝表覆盖的目录里(agent 连读都发不出去)
    T4  交给 agent 的环境变量里没有任何指向 fixture 的线索

T3 是最要紧的一条,也是唯一**不能只靠本文件证明**的一条 —— 它依赖既有的
主目录硬护栏。这里做的是把 fixture 的位置与那条护栏对上,并指明护栏本身
由 `tests/test_host_guard.py` 钉死。分层说清楚,免得读的人以为这一条也是
本文件现算出来的。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO / "benchmarks" / "v2" / "upstream_fixtures" / "canary_upstream_v1"
IMPORT_MODULE = "canary_upstream"


def _wheelhouses() -> list[Path]:
    base = Path("~/RepoProofBench").expanduser()
    return sorted(p for p in base.glob("wheelhouse-offerclaw-*") if p.is_dir())


def check_topology() -> dict:
    """返回逐条结果。`ok` 为真才允许把 conformance 结论当数。"""
    findings: list[dict] = []

    # ---- T1 不在任何 wheelhouse ------------------------------------
    hits = []
    for wh in _wheelhouses():
        for f in wh.iterdir():
            name = f.name.lower().replace("_", "-")
            if name.startswith("repoproof-canary-upstream") or name.startswith("canary-upstream"):
                hits.append(str(f))
    findings.append({
        "check": "T1.not_in_wheelhouse", "ok": not hits,
        "detail": (f"扫了 {len(_wheelhouses())} 个 wheelhouse,零命中"
                   if not hits else f"fixture 竟然在 wheelhouse 里:{hits}")})

    # ---- T2 干净解释器 import 不到 ---------------------------------
    #
    # 用**子进程**而不是本进程试:本进程早就把 fixture 挂进 sys.path 了
    # (harness 侧就该挂),在这里 try/except 只能证明"我挂过了"。
    # 而且刻意清掉 PYTHONPATH —— 否则父进程的注入会顺着环境漏下去,
    # 那样查出来的是"这次没漏",不是"结构上漏不了"。
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    probe = subprocess.run(                                    # noqa: S603 固定 argv
        [sys.executable, "-c",
         f"import {IMPORT_MODULE}; print({IMPORT_MODULE}.__file__)"],
        capture_output=True, text=True, cwd=str(REPO), env=env, check=False)
    findings.append({
        "check": "T2.not_importable_cleanly", "ok": probe.returncode != 0,
        "detail": ("干净子进程 import 失败(应该的):"
                   + (probe.stderr.strip().splitlines() or ["?"])[-1]
                   if probe.returncode != 0
                   else f"竟然 import 到了:{probe.stdout.strip()}")})

    # ---- T3 住在策略拒绝表覆盖的目录里 ------------------------------
    #
    # 分层说明:这一条**不是**本文件现算出来的。它依赖既有的主目录硬护栏
    # (`harness/host_guard.py`,由 `tests/test_host_guard.py` 钉死)。
    # 这里只做"位置对不对得上"这件事 —— fixture 必须在仓内。
    inside_repo = FIXTURE_ROOT.resolve().is_relative_to(REPO.resolve())
    findings.append({
        "check": "T3.inside_policy_denied_repo", "ok": inside_repo,
        "detail": (f"fixture 在仓内({FIXTURE_ROOT.relative_to(REPO)}),"
                   "受主目录硬护栏覆盖;护栏本身由 tests/test_host_guard.py 钉死"
                   if inside_repo else f"fixture 跑到仓外去了:{FIXTURE_ROOT}")})

    # ---- T4 agent 环境里没有指向 fixture 的线索 ---------------------
    from repoproof.execution.upstream_sidecar import SidecarHandle

    fake = SidecarHandle(None, "http://127.0.0.1:1", "tok",  # type: ignore[arg-type]
                         FIXTURE_ROOT / "ledger.jsonl", "rt-sidecar-canary-v1")
    blob = json.dumps(fake.agent_env())
    leaks = [s for s in ("canary_upstream", "upstream_fixtures",
                         str(FIXTURE_ROOT), "ledger") if s in blob]
    findings.append({
        "check": "T4.no_fixture_hint_in_agent_env", "ok": not leaks,
        "detail": ("agent 只拿到端点与令牌" if not leaks
                   else f"agent 环境里漏了线索:{leaks}")})

    return {"ok": all(f["ok"] for f in findings), "findings": findings}
