"""宿主级任务会话装配 + 空转冒烟全链(Phase 0 ④ 完成定义载体)。

合成迷你宿主(git 仓库 + 会过的回归 + 未实现的能力)+ 迷你上游 +
会话外隐藏 oracle:验证 ①②③ 串成的链条每一环真实发生。
"""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from repoproof.harness.host_guard import EXTERNAL, SELF, HostGuardError
from repoproof.harness.host_task import HostTaskError, HostTaskSpec, run_host_smoke
from tests.conftest import isolate_protected_dirs

PY = sys.executable


def _mini_world(tmp_path: Path) -> HostTaskSpec:
    """迷你宿主:回归绿、能力未实现(隐藏 oracle 预期挂=直连基线语义)。"""
    host = tmp_path / "bench" / "mini-host"
    (host / "app").mkdir(parents=True)
    (host / "app" / "__init__.py").write_text("", encoding="utf-8")
    (host / "app" / "core.py").write_text(
        "def health():\n    return 'ok'\n\n\n"
        "def capability(x):\n    raise NotImplementedError\n", encoding="utf-8")
    (host / "tests").mkdir()
    (host / "tests" / "test_regression.py").write_text(
        "import sys, pathlib\n"
        "sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))\n"
        "from app.core import health\n\n\n"
        "def test_health():\n    assert health() == 'ok'\n", encoding="utf-8")
    # 真实 PII 文件(应被合成替身顶替)+ 运行态文件(应被排除)
    (host / "user_profile.md").write_text("手机 13800138000\n", encoding="utf-8")
    (host / "gap_store.json").write_text("{}", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1"]):
        subprocess.run(["git", "-C", str(host), *args], check=True)

    upstream = tmp_path / "cache" / "upstream-mini"
    upstream.mkdir(parents=True)
    (upstream / "lib.py").write_text("def solve(x):\n    return x * 2\n", encoding="utf-8")

    oracle = tmp_path / "oracle" / "mini-task"
    oracle.mkdir(parents=True)
    (oracle / "test_capability.py").write_text(
        "from app.core import capability\n\n\n"
        "def test_capability():\n    assert capability(2) == 4\n", encoding="utf-8")

    return HostTaskSpec(
        task_id="mini-task",
        host_copy=host,
        upstream_src=upstream,
        oracle_dir=oracle,
        regression_cmd=[PY, "-m", "pytest", "tests/", "-q",
                        "--no-header", "-p", "no:cacheprovider"],
    )


def test_smoke_chain_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """全链跑通 + 保护目录**逐位零改动**。

    保护清单换成可控假邻仓(`_fake_neighbour`,定义见下方归因控制组)——
    2026-08-27 修:此前这条读**真实环境**的保护集,于是它的红绿取决于
    「你此刻有没有在跑 OfferClaw」:邻仓 logs 每 7–28 秒落盘一次,撞进
    会话存在的那 ~2.5 秒(约 15% 概率)、而拆除后的 6 秒探针又赶不上它
    下一次写(周期 ≥7 秒)→ 归因判 SELF → 整条链红。守卫没错,是这条
    测试把**别的项目在不在运行**当成了判据。

    换成受控主体后判据反而**更严**:不再退让到 `self_ok`,直接要求严判
    `ok`(逐位零改动)。降级语义没有丢 —— 外部活写手免罪与本链写穿必杀
    各有一条专控在下面,都用同一条真链、同一个 verify,不走捷径。
    """
    _fake_neighbour(tmp_path, monkeypatch)
    spec = _mini_world(tmp_path)
    report = run_host_smoke(spec, tmp_path / "sessions")

    assert report["ok"], report                       # 链条完整
    s = report["steps"]
    assert s["pii_scan"]["hits"] == 0                 # ③替身+排除后零 PII
    assert s["sanitised_env"]["fake_home"]            # ②假 HOME 生效
    assert s["regression"]["exit_code"] == 0          # 宿主回归绿
    assert s["hidden_oracle"]["exit_code"] != 0       # 未适配→隐藏验收挂(直连基线语义)
    assert "NotImplementedError" in s["hidden_oracle"]["tail"] \
        or "failed" in s["hidden_oracle"]["tail"]
    assert s["teardown"]["session_removed"]           # 会话拆净
    # ①保护目录严判:受控主体下不许有任何改动,也不许有任何降级警告。
    # 一旦这里红,说明是**本链**碰了保护目录 —— 没有"邻仓在忙"可推诿。
    integrity = report["main_dir_integrity"]
    assert integrity["ok"], integrity
    assert integrity["self_ok"], integrity
    assert not integrity["mismatches"], integrity
    assert not report["warnings"], report["warnings"]


def test_smoke_session_contains_no_pii_or_runtime_and_oracle_stays_out(
        tmp_path: Path, monkeypatch) -> None:
    """会话内不得有真实 PII/运行态;oracle 路径不进会话也不进 agent 环境。

    同样用可控假邻仓:本条断的是会话内容,与真实保护集无关 —— 拿真目录
    当主体只会白扫几十秒,还把「别的项目在不在跑」引进判据(同上一条)。
    """
    _fake_neighbour(tmp_path, monkeypatch)
    spec = _mini_world(tmp_path)
    captured: dict = {}

    from repoproof.execution.local_worktree_backend import LocalWorktreeBackend

    orig = LocalWorktreeBackend.destroy

    def spy_destroy(self, session):
        root = self._sessions.get(session)
        if root and not captured:
            captured["host_files"] = sorted(
                str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
            captured["profile"] = (root / "host" / "user_profile.md").read_text(
                encoding="utf-8")
            captured["env"] = self.build_env(session)
        return orig(self, session)

    monkeypatch.setattr(LocalWorktreeBackend, "destroy", spy_destroy)
    run_host_smoke(spec, tmp_path / "sessions")

    assert captured, "spy 未捕获会话"
    assert not any("gap_store" in f for f in captured["host_files"])   # 运行态被排除
    assert "13800138000" not in captured["profile"]                    # 真 PII 被替身顶替
    assert not any("oracle" in f for f in captured["host_files"])      # oracle 不在会话内
    env_blob = "\n".join(f"{k}={v}" for k, v in captured["env"].items())
    assert "oracle" not in env_blob                                    # 路径不进环境
    assert any(f.startswith("upstream/") for f in captured["host_files"])  # 上游已就位


# ---------- 归因正负控:外部并发写不拖累本测,本链写穿必须照样红 ----------
# 现场实证(2026-08-17):邻仓 offerclaw 的 logs/llm_usage.jsonl 每 7–28 秒
# 落盘一次,而冒烟链 83 秒里会话只存在 1.24 秒 —— 外部写压倒性落在"会话
# 根本不存在"的时段。下面两条把这两类各钉一次,用**同一条真链**,
# 不走任何绕过 verify 的捷径。


def _fake_neighbour(tmp_path: Path, monkeypatch) -> Path:
    """把保护清单换成一个可控的假邻仓 —— 别对真目录做实验,也别扫 43 秒。"""
    neighbour = tmp_path / "neighbour-repo"
    (neighbour / "logs").mkdir(parents=True)
    (neighbour / "logs" / "usage.jsonl").write_text("{}\n", encoding="utf-8")
    isolate_protected_dirs(monkeypatch, neighbour)
    return neighbour


def test_session_writing_into_protected_dir_stays_red(tmp_path: Path,
                                                      monkeypatch) -> None:
    """**负控**:会话子进程写穿到保护目录 —— 归因必须判 SELF,整条链判红。

    这正是护栏存在的理由(模式 L:拦写),去 flake 不许把它掏空。写入由
    真实的会话内命令发起、落在会话存在期内、拆除后不再动 —— 三条全中,
    没有任何免罪的正面证据。"""
    neighbour = _fake_neighbour(tmp_path, monkeypatch)
    spec = _mini_world(tmp_path)
    breach = neighbour / "logs" / "breached_by_session.txt"
    spec.regression_cmd = [PY, "-c",
                           f"open({str(breach)!r}, 'w').write('escaped\\n')"]

    report = run_host_smoke(spec, tmp_path / "sessions")

    assert report["steps"]["regression"]["exit_code"] == 0   # 红不是因为回归挂了
    integrity = report["main_dir_integrity"]
    assert not integrity["ok"] and not integrity["self_ok"], integrity
    assert not report["ok"]                                  # 整条链判红
    assert not report["warnings"]                            # 更不许降级成警告
    selfies = [c["path"] for m in integrity["mismatches"]
               for c in m["attribution"]["self_changes"]]
    assert "logs/breached_by_session.txt" in selfies, integrity
    assert any(m["attribution"]["verdict"] == SELF for m in integrity["mismatches"])


def test_external_live_writer_does_not_drag_the_smoke_red(tmp_path: Path,
                                                          monkeypatch) -> None:
    """**正控**:邻仓有活写手时,守卫照样抓到,但不算在本链头上。

    严判读数 `main_dir_integrity["ok"]` 仍为 False —— 变化确实发生过,
    这条不许粉饰;降级只体现在 `self_ok` 与 report 的 warnings 上。"""
    neighbour = _fake_neighbour(tmp_path, monkeypatch)
    spec = _mini_world(tmp_path)

    stop = threading.Event()
    busy = neighbour / "logs" / "usage.jsonl"

    def churn() -> None:
        i = 0
        while not stop.is_set():
            i += 1
            busy.write_text("{}\n" * i, encoding="utf-8")
            time.sleep(0.02)

    threading.Thread(target=churn, daemon=True).start()
    try:
        report = run_host_smoke(spec, tmp_path / "sessions")
    finally:
        stop.set()

    integrity = report["main_dir_integrity"]
    assert not integrity["ok"], integrity                    # 守卫如实抓到了
    assert integrity["self_ok"], integrity                   # 但不是本链写的
    assert report["ok"], report                              # 因此不拖累本测
    assert all(m["attribution"]["verdict"] == EXTERNAL for m in integrity["mismatches"])
    warn = report["warnings"]
    assert warn and warn[0]["code"] == "PROTECTED_DIR_EXTERNAL_WRITE"
    assert "logs/usage.jsonl" in warn[0]["paths"], warn      # 降级也要指名道姓


def test_protected_host_copy_refused_and_missing_dirs_typed(tmp_path: Path,
                                                            monkeypatch) -> None:
    spec = _mini_world(tmp_path)
    monkeypatch.setenv("REPOPROOF_PROTECTED_DIRS", str(spec.host_copy))
    with pytest.raises(HostGuardError, match="受保护"):
        run_host_smoke(spec, tmp_path / "sessions")
    monkeypatch.delenv("REPOPROOF_PROTECTED_DIRS")

    bad = _mini_world(tmp_path / "w2")
    bad.oracle_dir = tmp_path / "nope"
    with pytest.raises(HostTaskError, match="隐藏验收目录不存在"):
        run_host_smoke(bad, tmp_path / "sessions2")
