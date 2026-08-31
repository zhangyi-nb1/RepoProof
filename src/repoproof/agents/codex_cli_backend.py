"""Product Mode connector for the official Codex CLI.

The connector deliberately imports Codex's native agent loop instead of
pretending it is another raw model provider.  RepoProof still owns task
contracts, bounded repair rounds, independent verification, clean replay and
release state.  This backend is not eligible for Benchmark Lab measurements:
its internal model-call count and full tool policy are not RepoProof-owned.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repoproof.agents.backend import AgentRunResult
from repoproof.agents.codex_hook_guard import HOOK_POLICY_VERSION
from repoproof.agents.provider_gate import PreflightResult
from repoproof.domain.models import sha256_bytes

BACKEND_ID = "codex-cli"
PROVIDER_TYPE = "chatgpt-subscription-codex"
ACTION_PROTOCOL = "codex-exec-jsonl-v1"
DEFAULT_BUNDLED_CODEX = Path("/Applications/ChatGPT.app/Contents/Resources/codex")

_REMOVED_PROVIDER_ENV = {
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "OPENAI_BASE_URL",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_API_BASE",
    "LITELLM_API_KEY",
    "REPOPROOF_API_BASE",
    "REPOPROOF_API_KEY",
    "REPOPROOF_MODEL",
    "REPOPROOF_CODEX_MODEL",
}
_SENSITIVE_ENV_MARKERS = (
    "ACCESS_KEY",
    "API_KEY",
    "CREDENTIAL",
    "PASSWORD",
    "PRIVATE_KEY",
    "SECRET",
    "TOKEN",
)


@dataclass(frozen=True)
class CodexSubscriptionConfig:
    executable: Path
    executable_version: str
    model_name: str = "chatgpt-subscription-default"

    PROVIDER_TYPE = PROVIDER_TYPE

    def normalized(self) -> dict[str, str]:
        return {
            "provider_type": self.PROVIDER_TYPE,
            "model_name": self.model_name,
            "backend": BACKEND_ID,
            "action_protocol": ACTION_PROTOCOL,
            "sandbox": "workspace-write",
            "hook_policy": HOOK_POLICY_VERSION,
            "codex_version": self.executable_version,
        }

    @property
    def config_sha256(self) -> str:
        return sha256_bytes(json.dumps(self.normalized(), sort_keys=True).encode())


def _candidate_executable() -> Path | None:
    override = os.environ.get("REPOPROOF_CODEX_CLI", "").strip()
    if override:
        path = Path(override).expanduser()
        return path if path.is_absolute() else None
    # Prefer the executable bundled with the signed ChatGPT app.  PATH remains
    # a supported fallback for machines that installed the official CLI
    # separately; an explicit absolute override always wins.
    if DEFAULT_BUNDLED_CODEX.is_file():
        return DEFAULT_BUNDLED_CODEX
    found = shutil.which("codex")
    return Path(found) if found else None


def subscription_config() -> CodexSubscriptionConfig | None:
    candidate = _candidate_executable()
    if candidate is None or not candidate.is_file() or not os.access(candidate, os.X_OK):
        return None
    executable = candidate.resolve()
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    version = (result.stdout or result.stderr).strip().splitlines()[0][:120]
    model = os.environ.get("REPOPROOF_CODEX_MODEL", "").strip()
    return CodexSubscriptionConfig(
        executable=executable,
        executable_version=version or "UNKNOWN",
        model_name=model or "chatgpt-subscription-default",
    )


def run_subscription_preflight(
    config: CodexSubscriptionConfig | None,
) -> PreflightResult:
    started = time.monotonic()
    if config is None:
        return PreflightResult(
            status="CODEX_CLI_NOT_FOUND",
            provider_config_sha256="UNKNOWN",
            model_name="UNKNOWN",
            api_base_summary="chatgpt-subscription-oauth",
            action_protocol=None,
            temperature="provider_default",
            calls=0,
            input_tokens=0,
            output_tokens=0,
            cost="UNKNOWN",
            wall_time_s=time.monotonic() - started,
            evidence=["official Codex CLI executable was not found"],
        )
    try:
        check = subprocess.run(
            [str(config.executable), "login", "status"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
        ready = check.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        ready = False
    return PreflightResult(
        status="PROVIDER_READY" if ready else "CODEX_LOGIN_REQUIRED",
        provider_config_sha256=config.config_sha256,
        model_name=config.model_name,
        api_base_summary="chatgpt-subscription-oauth",
        action_protocol=ACTION_PROTOCOL if ready else None,
        temperature="provider_default",
        calls=0,
        input_tokens=0,
        output_tokens=0,
        cost="INCLUDED_USAGE_UNMETERED",
        wall_time_s=time.monotonic() - started,
        evidence=[
            f"{config.executable_version}; login status exit={'0' if ready else 'nonzero'}",
            "preflight performs no model request and never reads auth material",
        ],
    )


def clean_codex_environment(
    *,
    allowed_root: Path,
    policy_log: Path,
    no_tools: bool = False,
) -> dict[str, str]:
    env = dict(os.environ)
    for name in _REMOVED_PROVIDER_ENV:
        env.pop(name, None)
    # The child needs HOME/CODEX_HOME so the official CLI can use its own OAuth
    # login, but public-repository adaptation never needs unrelated credentials
    # inherited from the Studio shell.
    for name in list(env):
        upper = name.upper()
        if any(marker in upper for marker in _SENSITIVE_ENV_MARKERS):
            env.pop(name, None)
    env.pop("SSH_AUTH_SOCK", None)
    env["REPOPROOF_CODEX_ALLOWED_ROOT"] = str(allowed_root)
    env["REPOPROOF_CODEX_POLICY_LOG"] = str(policy_log)
    if no_tools:
        env["REPOPROOF_CODEX_NO_TOOLS"] = "1"
    else:
        env.pop("REPOPROOF_CODEX_NO_TOOLS", None)
    return env


def codex_hook_override(*, all_tools: bool = False) -> str:
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).with_name('codex_hook_guard.py')))}"
    matcher = ".*" if all_tools else "^(Bash|apply_patch)$"
    return (
        f"hooks.PreToolUse=[{{matcher={json.dumps(matcher)},hooks=["
        f"{{type=\"command\",command={json.dumps(command)},timeout=5}}]}}]"
    )


def _stop_process_group(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass


def _load_policy_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


class CodexCLIBackend:
    """One bounded ``codex exec`` invocation for one RepoProof repair round."""

    def __init__(
        self,
        *,
        config: CodexSubscriptionConfig,
        workspace: Path,
        allowed_root: Path,
        output_path: Path,
        policy_log_path: Path,
        command_limit: int,
        timeout_s: float,
    ) -> None:
        self._config = config
        self._workspace = Path(workspace).resolve()
        self._allowed_root = Path(allowed_root).resolve()
        self._output_path = Path(output_path)
        self._policy_log_path = Path(policy_log_path)
        self._command_limit = max(1, int(command_limit))
        self._timeout_s = max(1.0, float(timeout_s))
        self.run_count = 0
        self.policy_records: list[dict[str, Any]] = []

        if not self._workspace.is_dir():
            raise ValueError(f"Codex workspace does not exist:{self._workspace}")
        try:
            self._workspace.relative_to(self._allowed_root)
        except ValueError as exc:
            raise ValueError("Codex workspace is outside the disposable session root") from exc

    def run_task(self, task: str) -> AgentRunResult:
        if self.run_count:
            raise AssertionError("CodexCLIBackend.run_task may be called exactly once")
        self.run_count += 1
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._policy_log_path.parent.mkdir(parents=True, exist_ok=True)
        # The record count below must describe this invocation only.  A stale
        # append-only-looking file would otherwise make a missing hook appear
        # healthy.
        self._policy_log_path.unlink(missing_ok=True)

        argv = [
            str(self._config.executable),
            "exec",
            "--ephemeral",
            "--json",
            "--color",
            "never",
            "--sandbox",
            "workspace-write",
            "--ignore-user-config",
            "--ignore-rules",
            "--dangerously-bypass-hook-trust",
            "-c",
            codex_hook_override(),
            "--cd",
            str(self._workspace),
        ]
        if self._config.model_name != "chatgpt-subscription-default":
            argv += ["--model", self._config.model_name]
        argv.append("-")

        proc = subprocess.Popen(  # noqa: S603 - fixed executable and structured argv
            argv,
            cwd=self._workspace,
            env=clean_codex_environment(
                allowed_root=self._allowed_root,
                policy_log=self._policy_log_path,
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        agent_messages: list[str] = []
        usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
        turn_started = False
        commands_started = 0
        limit_hit = threading.Event()
        state_lock = threading.Lock()

        def read_stdout() -> None:
            nonlocal commands_started, turn_started
            assert proc.stdout is not None
            for line in proc.stdout:
                stdout_lines.append(line)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = event.get("type")
                if etype == "turn.started":
                    turn_started = True
                if etype == "turn.completed" and isinstance(event.get("usage"), dict):
                    raw_usage = event["usage"]
                    for key in usage:
                        value = raw_usage.get(key)
                        if isinstance(value, int):
                            usage[key] += value
                item = event.get("item")
                if not isinstance(item, dict):
                    continue
                if etype == "item.started" and item.get("type") == "command_execution":
                    with state_lock:
                        commands_started += 1
                        over = commands_started > self._command_limit
                    if over:
                        limit_hit.set()
                        _stop_process_group(proc)
                if etype == "item.completed" and item.get("type") == "agent_message":
                    text = item.get("text")
                    if isinstance(text, str):
                        agent_messages.append(text)

        def read_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line)

        out_thread = threading.Thread(target=read_stdout, daemon=True)
        err_thread = threading.Thread(target=read_stderr, daemon=True)
        out_thread.start()
        err_thread.start()
        assert proc.stdin is not None
        try:
            proc.stdin.write(task)
            proc.stdin.close()
            proc.wait(timeout=self._timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_process_group(proc)
        finally:
            out_thread.join(timeout=5)
            err_thread.join(timeout=5)

        self._output_path.write_text("".join(stdout_lines), encoding="utf-8")
        stderr_path = self._output_path.with_suffix(self._output_path.suffix + ".stderr.txt")
        stderr_path.write_text("".join(stderr_lines)[-20000:], encoding="utf-8")
        self.policy_records = _load_policy_records(self._policy_log_path)
        denied = [r for r in self.policy_records if r.get("allowed") is False]
        policy_audit_complete = len(self.policy_records) >= commands_started
        denial_reasons = tuple(
            str(reason)
            for record in denied
            for reason in (record.get("reasons") or [])
        )

        if timed_out:
            status = "CodexTimeout"
        elif limit_hit.is_set():
            status = "LimitsExceeded"
        elif proc.returncode != 0:
            status = f"CodexExit:{proc.returncode}"
        elif not policy_audit_complete:
            status = "CodexPolicyAuditMissing"
        else:
            status = "Submitted"
        return AgentRunResult(
            exit_status=status,
            submission=agent_messages[-1] if agent_messages else "",
            # One means one RepoProof-visible codex-exec invocation.  Codex's
            # internal model-call count is not exposed and is separately marked.
            n_model_calls=1 if turn_started else 0,
            cost="INCLUDED_USAGE_UNMETERED",
            trajectory_path=self._output_path,
            commands_used=min(commands_started, self._command_limit),
            denied_count=len(denied),
            input_tokens=usage["input_tokens"] if turn_started else None,
            output_tokens=usage["output_tokens"] if turn_started else None,
            cached_input_tokens=usage["cached_input_tokens"] if turn_started else None,
            model_calls_observed=False,
            policy_denials=denial_reasons,
            policy_audit_complete=policy_audit_complete,
        )


def policy_log_digest(path: Path) -> str | None:
    if not Path(path).is_file():
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
