"""宿主级任务会话装配 + 空转冒烟链(TESTPLAN-V2 Phase 0 ④,RFC-009 §二)。

把 Phase 0 前三件安全件串成一条可执行链:

    护栏(①)→ 保护目录指纹 pre(①)→ 会话建立(②,净化环境/假 HOME)
    → 宿主快照进会话(③,排除+替身+PII 扫描)→ 上游快照(只读复制)
    → 会话内执行(公开回归/探针)→ 隐藏 oracle 会话外持有、对会话执行
    → 拆除 → 保护目录指纹 post 对账(①)

会话布局(RFC-009 §二 的模式 L 落地):

    <session>/host/         宿主快照(agent 未来的工作区;含 .git 整体)
    <session>/upstream/     目标仓库固定快照(约定只读)
    <session>/adaptation/   改动台账区
    (oracle 不在会话内——隐藏验收由 harness 持有,路径不进 agent 环境)

`run_host_smoke` = 零模型、零 agent 的"空转冒烟":Phase 0 完成定义
要求的全链验证载体;Phase 1 的 Host Baseline 首测复用同一条链。
"""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from repoproof.execution.local_worktree_backend import LocalWorktreeBackend
from repoproof.harness.host_guard import (
    HostGuardError,
    SelfWriteWindow,
    is_protected,
    snapshot_protected,
    verify_protected_unchanged,
)
from repoproof.harness.host_snapshot import prepare_host_snapshot, scan_for_pii


@dataclass
class HostTaskSpec:
    """一次宿主级任务会话的最小规格(冻结版任务包是它的超集)。"""

    task_id: str
    host_copy: Path                       # 宿主副本(~/RepoProofBench/...)
    upstream_src: Path                    # 目标仓库固定快照来源
    oracle_dir: Path                      # 隐藏验收目录(会话外持有)
    regression_cmd: list[str]             # 公开回归命令(冒烟用子集)
    python_exe: str = sys.executable      # Phase 1 起换 per-run venv 的 python
    snapshot_extra_excludes: tuple[str, ...] = ()
    editable_zones: tuple[str, ...] = ("host",)  # 会话内写白名单(策略用)
    env: dict[str, str] = field(default_factory=dict)


class HostTaskError(RuntimeError):
    pass


def build_session(spec: HostTaskSpec, backend: LocalWorktreeBackend) -> str:
    """装配会话:护栏检查 → 宿主快照 → 上游复制 → 台账区。"""
    if is_protected(spec.host_copy):
        raise HostGuardError(
            f"宿主副本路径命中受保护目录({spec.host_copy})——"
            "禁止把真实开发目录当宿主,请用 ~/RepoProofBench/ 副本。")
    if not Path(spec.oracle_dir).is_dir():
        raise HostTaskError(f"隐藏验收目录不存在:{spec.oracle_dir}")
    session = backend.start(name_prefix=spec.task_id, env=spec.env)
    root = backend.session_root(session)
    prepare_host_snapshot(spec.host_copy, root / "host",
                          extra_excludes=spec.snapshot_extra_excludes)
    upstream = Path(spec.upstream_src).expanduser().resolve()
    if not upstream.is_dir():
        backend.destroy(session)
        raise HostTaskError(f"上游快照来源不存在:{upstream}")
    shutil.copytree(upstream, root / "upstream", symlinks=False)
    (root / "adaptation").mkdir()
    return session


def run_hidden_oracle(spec: HostTaskSpec, backend: LocalWorktreeBackend,
                      session: str, *, timeout_s: int = 900) -> dict:
    """隐藏验收:harness 持有 oracle 路径,对会话内宿主执行。

    oracle 目录不复制进会话;agent 的环境里没有它的路径。执行时
    cwd=host、PYTHONPATH=host,pytest 以绝对路径指向 oracle。"""
    root = backend.session_root(session)
    res = backend.exec(
        session,
        [spec.python_exe, "-m", "pytest", str(Path(spec.oracle_dir).resolve()), "-q",
         "--no-header", "-p", "no:cacheprovider"],
        timeout_s=timeout_s, workdir="host",
        env={"PYTHONPATH": str(root / "host")},
    )
    return {"exit_code": res.exit_code, "timed_out": res.timed_out,
            "tail": res.stdout.decode(errors="replace")[-800:]}


def run_host_smoke(spec: HostTaskSpec, sessions_root: Path,
                   *, timeout_s: int = 900) -> dict:
    """空转冒烟(零模型零 agent):全链跑通性验证。

    返回逐步结果;ok = 链条完整走完且保护目录**没有一条改动归到本链
    名下**(隐藏 oracle 在未适配宿主上失败属预期,不影响 ok——那是
    "直连基线"语义)。

    **为什么 ok 不再要求逐位零改动**:保护清单含 XIANGMU 下全部邻仓,
    邻仓有各自的活写手(实测 offerclaw `logs/llm_usage.jsonl` 每 7–28
    秒落盘一次)。而本链 83 秒里会话只存在 1.24 秒,两头是纯只读扫描
    ——外部写手压倒性地落在"会话根本不存在"的时段里,把这种红算到本
    测头上,红的是环境不是被测件。`SelfWriteWindow` 把作案时刻交给
    对账去判:**窗内的照杀,窗外的降级为警告且逐条留痕**。
    严判读数仍在 `main_dir_integrity["ok"]` 里原样保留,一位不改。"""
    report: dict = {"task_id": spec.task_id, "steps": {}, "warnings": []}
    integrity_before = snapshot_protected()                      # ①指纹 pre
    backend = LocalWorktreeBackend(sessions_root=Path(sessions_root))
    session = None
    # 自写窗口起点:此刻之前本链只做过只读的指纹遍历,一个字节没写。
    session_start = time.time()
    try:
        session = build_session(spec, backend)                   # ②③装配
        root = backend.session_root(session)
        report["steps"]["session"] = {"root": str(root)}

        pii = scan_for_pii(root / "host")                        # ③出口扫描
        report["steps"]["pii_scan"] = {"hits": len(pii), "detail": pii[:5]}

        probe = backend.exec(session, [spec.python_exe, "-c",
                                       "import os;print(os.environ['HOME'])"],
                             timeout_s=60, workdir="host")
        fake_home_ok = (probe.exit_code == 0
                        and probe.stdout.decode().strip().startswith(str(root)))
        report["steps"]["sanitised_env"] = {"fake_home": fake_home_ok}  # ②净化验证

        reg = backend.exec(session, spec.regression_cmd,
                           timeout_s=timeout_s, workdir="host")   # 公开回归
        report["steps"]["regression"] = {
            "exit_code": reg.exit_code, "timed_out": reg.timed_out,
            "tail": reg.stdout.decode(errors="replace")[-400:]}

        report["steps"]["hidden_oracle"] = run_hidden_oracle(     # 隐藏验收
            spec, backend, session, timeout_s=timeout_s)
    finally:
        if session is not None:
            backend.destroy(session)                              # 拆除
        # 自写窗口终点:会话没了,后面只剩只读对账(含活写手探针)。
        teardown_end = time.time()
        report["steps"]["teardown"] = {
            "session_removed": session is None
            or not (Path(sessions_root) / session).exists()}

    integrity = verify_protected_unchanged(                       # ①指纹 post
        integrity_before,
        self_window=SelfWriteWindow(start=session_start, end=teardown_end))
    report["main_dir_integrity"] = integrity
    if not integrity["ok"] and integrity["self_ok"]:
        # 降级但不噤声:哪个目录、哪几条路径、凭什么判外部,全落进 report。
        report["warnings"].append({
            "code": "PROTECTED_DIR_EXTERNAL_WRITE",
            "note": "保护目录在窗口外被外部进程写入;守卫已如实抓到,"
                    "归因证明与本链无关,故不判红。严判读数见 main_dir_integrity.ok。",
            "dirs": sorted({m["dir"] for m in integrity["mismatches"]}),
            "paths": sorted({c["path"] for m in integrity["mismatches"]
                             for c in m["attribution"]["external_changes"]})[:20],
        })
    report["ok"] = bool(
        integrity["self_ok"]
        and report["steps"].get("pii_scan", {}).get("hits") == 0
        and report["steps"].get("sanitised_env", {}).get("fake_home")
        and report["steps"].get("regression", {}).get("exit_code") == 0
        and report["steps"].get("teardown", {}).get("session_removed")
        and "hidden_oracle" in report["steps"])
    return report
