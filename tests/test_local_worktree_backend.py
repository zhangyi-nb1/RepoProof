"""LocalWorktree 执行后端(Phase 0 ②)——模式 L 四条硬约束钉死。

护栏 / 假 HOME(L2)/ 净化环境含合成密钥(C 类政策)/ cwd 边界,
外加同形接口与超时进程组清理。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from repoproof.execution.docker_backend import Mount
from repoproof.execution.local_worktree_backend import (
    SYNTHETIC_ENV,
    LocalBackendError,
    LocalWorktreeBackend,
)
from repoproof.harness.host_guard import HostGuardError

PY = sys.executable


@pytest.fixture()
def backend(tmp_path: Path) -> LocalWorktreeBackend:
    b = LocalWorktreeBackend(sessions_root=tmp_path / "sessions")
    yield b
    b.destroy_all()


def test_session_root_under_protected_dir_is_refused(tmp_path: Path, monkeypatch) -> None:
    """护栏(§4-1):会话根命中受保护目录 → 拒绝建立,无旁路。"""
    monkeypatch.setenv("REPOPROOF_PROTECTED_DIRS", str(tmp_path / "real_proj"))
    b = LocalWorktreeBackend(sessions_root=tmp_path / "real_proj" / "sessions")
    with pytest.raises(HostGuardError):
        b.start(name_prefix="rp")


def test_fake_home_cuts_all_tilde_access(backend: LocalWorktreeBackend) -> None:
    """L2:HOME/XDG/HF 全部指向会话内假 HOME —— `~` 通道被切断。

    真实教训:OfferClaw 有 4 处 `~` 访问(~/.openclaw、~/Downloads、
    ~/.cache/modelscope、~/.cache/docling),假 HOME 一举全封。"""
    s = backend.start(name_prefix="rp")
    root = backend.session_root(s)
    code = (
        "import os,pathlib,json;"
        "print(json.dumps({'home':os.path.expanduser('~'),"
        "'xdg':os.environ.get('XDG_CACHE_HOME',''),"
        "'hf':os.environ.get('HF_HOME','')}))"
    )
    res = backend.exec(s, [PY, "-c", code], timeout_s=30)
    assert res.exit_code == 0, res.stderr
    import json

    got = json.loads(res.stdout.decode())
    assert got["home"] == str(root / ".rp_home")
    assert got["home"] != os.path.expanduser("~")  # 绝不是用户真 HOME
    for key in ("xdg", "hf"):
        assert got[key].startswith(str(root))
    # 写 `~/x` 落在假 HOME,真 HOME 零影响
    backend.exec(s, [PY, "-c",
                     "import pathlib;pathlib.Path('~/probe.txt').expanduser().write_text('x')"],
                 timeout_s=30)
    assert (root / ".rp_home" / "probe.txt").exists()
    assert not (Path.home() / "probe.txt").exists()


def test_env_is_sanitised_with_synthetic_keys(backend: LocalWorktreeBackend,
                                              monkeypatch) -> None:
    """C 类政策:不继承用户真钥;注入的是合成值;白名单外变量不外泄。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-REAL-USER-SECRET")
    monkeypatch.setenv("MY_PRIVATE_TOKEN", "leak-me-please")
    s = backend.start(name_prefix="rp")
    env = backend.build_env(s)
    assert env["OPENAI_API_KEY"] == SYNTHETIC_ENV["OPENAI_API_KEY"]
    assert "REAL-USER-SECRET" not in "".join(env.values())
    assert "MY_PRIVATE_TOKEN" not in env  # 白名单外一律不带
    assert "PATH" in env  # 必需项仍在
    res = backend.exec(s, [PY, "-c",
                           "import os;print(os.environ.get('MY_PRIVATE_TOKEN','ABSENT'),"
                           "os.environ['OPENAI_API_KEY'])"], timeout_s=30)
    body = res.stdout.decode()
    assert body.startswith("ABSENT") and "synthetic" in body


def test_workdir_escape_refused_and_mounts_are_copies(
        backend: LocalWorktreeBackend, tmp_path: Path) -> None:
    """cwd 钉死 + mounts 复制而非软链(避免写回原目录的通道)。"""
    src = tmp_path / "srcdir"
    src.mkdir()
    (src / "a.txt").write_text("orig", encoding="utf-8")
    s = backend.start(name_prefix="rp", mounts=[Mount(src, "/host", True)])
    root = backend.session_root(s)
    copied = root / "host" / "a.txt"
    assert copied.read_text() == "orig" and not copied.is_symlink()
    # 会话内改动不回写原目录
    backend.exec(s, [PY, "-c", "open('host/a.txt','w').write('changed')"], timeout_s=30)
    assert copied.read_text() == "changed"
    assert (src / "a.txt").read_text() == "orig"
    with pytest.raises(LocalBackendError, match="越出会话根"):
        backend.exec(s, [PY, "-c", "print(1)"], timeout_s=10, workdir="../..")


def test_timeout_kills_process_group(backend: LocalWorktreeBackend) -> None:
    s = backend.start(name_prefix="rp")
    res = backend.exec(s, [PY, "-c", "import time;time.sleep(30)"], timeout_s=2)
    assert res.timed_out and res.exit_code == 124
    assert res.duration_ms < 15_000  # 真的被杀,不是等满 30s


def test_same_shape_as_docker_backend_and_destroy_cleans(
        backend: LocalWorktreeBackend) -> None:
    """同形接口(runner 侧零改动切换)+ destroy 清理会话目录。"""
    from repoproof.execution.docker_backend import DockerExecutionBackend

    for name in ("start", "exec", "destroy", "destroy_all", "available"):
        assert hasattr(LocalWorktreeBackend, name) and hasattr(DockerExecutionBackend, name)
    ok, note = LocalWorktreeBackend.available()
    assert ok and note == "local-worktree"
    s = backend.start(name_prefix="rp")
    root = backend.session_root(s)
    assert root.is_dir()
    backend.destroy(s)
    assert not root.exists()
