"""宿主级任务会话装配 + 空转冒烟全链(Phase 0 ④ 完成定义载体)。

合成迷你宿主(git 仓库 + 会过的回归 + 未实现的能力)+ 迷你上游 +
会话外隐藏 oracle:验证 ①②③ 串成的链条每一环真实发生。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from repoproof.harness.host_guard import HostGuardError
from repoproof.harness.host_task import HostTaskError, HostTaskSpec, run_host_smoke

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


def test_smoke_chain_end_to_end(tmp_path: Path) -> None:
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
    assert report["main_dir_integrity"]["ok"]         # ①保护目录零改动


def test_smoke_session_contains_no_pii_or_runtime_and_oracle_stays_out(
        tmp_path: Path, monkeypatch) -> None:
    """会话内不得有真实 PII/运行态;oracle 路径不进会话也不进 agent 环境。"""
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
