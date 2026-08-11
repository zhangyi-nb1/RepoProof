"""LocalWorktree 执行后端(模式 L,TESTPLAN-V2 §5,Phase 0 ②)。

与 DockerExecutionBackend **同形**(start/exec/destroy/destroy_all +
Mount/ExecResult),让 runner 侧零改动即可切换后端。

模式 L 的隔离来自策略层而非内核,因此本后端把 TESTPLAN 要求的四条
硬约束焊在执行路径上,任何调用方都绕不过:

1. **护栏**:会话根目录命中受保护的真实开发目录 → 直接拒绝(§4-1);
2. **假 HOME**(风险登记册 L2):HOME/XDG/缓存类变量一律指向会话内
   的临时目录——一举切断 `~/.openclaw`、`~/Downloads`、`~/.cache`
   等全部 `~` 读写通道;
3. **净化环境**(§4-5):不继承用户 shell,只注入白名单最小集 +
   **合成密钥**;真实 API key 永不进入 agent 轮次;
4. **cwd 钉死**:所有命令在会话根内执行,workdir 越界即拒。

不承诺的事(如实记录,与容器的差别):无内核级隔离、无 cgroup 资源
硬限(超时用进程组 kill 兜底)、无网络命名空间隔离(离线靠环境变量
与策略,见 §5 网络策略明示弱化)。
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from repoproof.execution.docker_backend import ExecResult, Mount
from repoproof.harness.host_guard import assert_writable_target

# 净化环境白名单:只放行运行 Python/git 必需的宿主变量
_ENV_PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR")

# 合成密钥:形状可用、值无效——测试若真的发起网络认证会明确失败,
# 而不是静默借用用户的真钥(风险登记册 C 类政策)
SYNTHETIC_ENV = {
    "OPENAI_API_KEY": "sk-repoproof-synthetic-do-not-use",
    "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
    "DASHSCOPE_API_KEY": "sk-repoproof-synthetic-do-not-use",
    "ANTHROPIC_API_KEY": "sk-repoproof-synthetic-do-not-use",
}

# 离线开关(L 级网络弱化的尽力而为部分)
_OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "NO_PROXY": "*",
    "no_proxy": "*",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
}


class LocalBackendError(RuntimeError):
    pass


def _seed_login_keychain(home: Path) -> bool:
    """darwin:在假 HOME 预置空密码 login 钥匙串(外部副作用治理)。

    T3 批内实证:净化 HOME 下 Chrome 的 OSCrypt 找不到可存 Safe
    Storage 密钥的钥匙串,向**用户屏幕**弹 SecurityAgent 对话框
    ("找不到用于储存 Chrome 的钥匙串"),批内曾靠有界看门狗临时
    压制。预置空密码钥匙串后 Chrome 静默入库(2026-08-11 探针:
    dump-keychain 出现 "Chrome Safe Storage" 条目,观察窗零弹窗)。
    三条 `security` 都以假 HOME 运行:钥匙串文件在会话目录内、随
    会话销毁;不动用户真钥匙串,也不写搜索列表(create-keychain
    本就不改 search list,探针以真 plist 哈希哨兵复核)。装饰性
    修复:任何失败只降级返回 False,绝不影响会话建立。
    消融:REPOPROOF_SEED_KEYCHAIN=0。
    """
    if sys.platform != "darwin" or os.environ.get(
            "REPOPROOF_SEED_KEYCHAIN", "").strip() == "0":
        return False
    security = shutil.which("security")
    if not security:
        return False
    kc = home / "Library" / "Keychains" / "login.keychain-db"
    kc.parent.mkdir(parents=True, exist_ok=True)
    env = {"HOME": str(home), "PATH": os.environ.get("PATH", "/usr/bin")}
    for argv in ([security, "create-keychain", "-p", "", str(kc)],
                 [security, "unlock-keychain", "-p", "", str(kc)],
                 [security, "set-keychain-settings", str(kc)]):
        try:
            r = subprocess.run(  # noqa: S603 — 固定 argv,假 HOME env
                argv, env=env, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if r.returncode != 0:
            return False
    return True


@dataclass
class LocalWorktreeBackend:
    """会话 = 一个隔离的执行根 + 假 HOME + 净化环境。

    sessions_root 下每个会话:
        <session>/          会话根(cwd 与写入边界)
        <session>/.rp_home/ 假 HOME(HOME/XDG/缓存全部指向这里)
    """

    sessions_root: Path
    offline: bool = True
    extra_env: dict[str, str] = field(default_factory=dict)
    _sessions: dict[str, Path] = field(default_factory=dict)

    # ---------------------------------------------------------- 生命周期
    def start(
        self,
        *,
        name_prefix: str,
        network: str = "none",
        mounts: list[Mount] | None = None,
        env: dict[str, str] | None = None,
        user: str | None = None,          # 同形占位:本地后端不切用户
        cap_drop_all: bool = True,        # 同形占位:无内核能力可丢弃
        image_ref: str | None = None,     # 同形占位:本地无镜像
    ) -> str:
        """建立会话。mounts 的 source 会被**复制**进会话根(不是挂载,
        更不是软链)——避免任何指回原目录的写通道。"""
        session = f"{name_prefix}-{uuid.uuid4().hex[:8]}"
        root = (self.sessions_root / session).resolve()
        assert_writable_target(root, purpose="建立本地执行会话根")
        (root / ".rp_home").mkdir(parents=True)
        _seed_login_keychain(root / ".rp_home")  # darwin:压 Chrome 钥匙串弹窗
        for m in mounts or []:
            src = Path(m.host).expanduser().resolve()
            dst = root / str(m.container).lstrip("/")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, symlinks=False, dirs_exist_ok=True)
            elif src.is_file():
                shutil.copy2(src, dst)
        self._sessions[session] = root
        self._session_env = dict(env or {})
        return session

    def session_root(self, session: str) -> Path:
        if session not in self._sessions:
            raise LocalBackendError(f"未知会话:{session}")
        return self._sessions[session]

    def destroy(self, session: str) -> None:
        root = self._sessions.pop(session, None)
        if root and root.is_dir():
            shutil.rmtree(root, ignore_errors=True)

    def destroy_all(self) -> None:
        for s in list(self._sessions):
            self.destroy(s)

    # ---------------------------------------------------------------- 执行
    def build_env(self, session: str, env: dict[str, str] | None = None) -> dict[str, str]:
        """净化环境:白名单 + 假 HOME + 合成密钥 + 离线开关 + 调用方 env。"""
        root = self.session_root(session)
        home = root / ".rp_home"
        out = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
        out.update({
            "HOME": str(home),
            "TMPDIR": str(home / "tmp"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local" / "share"),
            "HF_HOME": str(home / ".cache" / "huggingface"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "REPOPROOF_EXECUTION_BACKEND": "local-worktree",
        })
        out.update(SYNTHETIC_ENV)
        if self.offline:
            out.update(_OFFLINE_ENV)
        out.update(self.extra_env)
        out.update(getattr(self, "_session_env", {}) or {})
        out.update(env or {})
        for d in ("tmp", ".cache", ".config"):
            (home / d).mkdir(parents=True, exist_ok=True)
        return out

    def exec(
        self,
        session: str,
        argv: list[str],
        *,
        timeout_s: int,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """在会话根内执行 argv。cwd 越界即拒;超时杀整个进程组。"""
        root = self.session_root(session)
        cwd = root if not workdir else (root / str(workdir).lstrip("/")).resolve()
        if root != cwd and root not in cwd.parents:
            raise LocalBackendError(f"workdir 越出会话根,拒绝执行:{workdir}")
        cwd.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.Popen(  # noqa: S603 — argv 列表,无 shell
                argv, cwd=str(cwd), env=self.build_env(session, env),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            return ExecResult(argv=argv, exit_code=127, timed_out=False,
                              duration_ms=0, stdout=b"",
                              stderr=f"无法启动命令: {exc}".encode())
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:  # 杀整个进程组,避免子进程遗留
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
            out, err = proc.communicate()
        return ExecResult(
            argv=argv,
            exit_code=124 if timed_out else proc.returncode,
            timed_out=timed_out,
            duration_ms=int((time.monotonic() - t0) * 1000),
            stdout=out or b"",
            stderr=err or b"",
        )

    @staticmethod
    def available() -> tuple[bool, str]:
        """同形接口:本地后端总是可用(无守护进程依赖)。"""
        return True, "local-worktree"
