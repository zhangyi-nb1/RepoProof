"""Durable, fail-closed execution for RepoProof Core mutations.

Studio and Benchmark Lab are separate products, but both can launch commands
that mutate the repository's Core state.  This module owns their one shared
mutex and a detached worker that records a durable outcome.  Command
environments are inherited by the worker and are never serialized to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CORE_EXECUTION_LOCK = Path("runs/.core-execution.lock")
LEGACY_LAB_STATE = Path("runs/.ui_live.lock")
STATE_SCHEMA_VERSION = 2
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
INTERRUPTED = "INTERRUPTED"
TERMINAL_STATUSES = frozenset({SUCCEEDED, FAILED, INTERRUPTED})
NONZERO_EXIT = "NONZERO_EXIT"
EXPECTED_ARTIFACT_MISSING = "EXPECTED_ARTIFACT_MISSING"
WORKER_INTERRUPTED = "WORKER_INTERRUPTED"
STATE_INVALID = "STATE_INVALID"
WORKER_START_FAILED = "WORKER_START_FAILED"
EXECUTION_ERROR = "EXECUTION_ERROR"


class CoreExecutionConflictError(RuntimeError):
    """A Core mutation could not obtain or safely release the shared lease."""


def _start_process_reaper(proc: subprocess.Popen[str]) -> None:
    """Reap a detached worker when its long-lived launcher stays alive.

    ``start_new_session`` separates signal/session ownership, but it does not
    re-parent the worker.  Studio's Streamlit process can therefore outlive a
    completed worker and retain it as a zombie unless somebody calls
    ``wait()``.  A daemon thread keeps the durable worker independent from UI
    reruns while still collecting its process-table entry.  The durable state
    file remains the outcome authority; this thread does not interpret it.
    """

    def _reap() -> None:
        try:
            proc.wait()
        except (OSError, subprocess.SubprocessError):
            # State validation remains fail-closed even if the platform can no
            # longer expose the child to this launcher.
            return

    reaper = threading.Thread(
        target=_reap,
        name=f"repoproof-worker-reaper-{proc.pid}",
        daemon=True,
    )
    try:
        reaper.start()
    except RuntimeError:
        # A worker that cannot be reaped must not be handed a real command.
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
        raise

_SENSITIVE_OPTION = re.compile(
    r"(?:api[-_]?key|token|secret|password|passwd|credential|authorization)",
    re.IGNORECASE,
)
_REDACTED = "[REDACTED]"
_SAFE_OPTION = re.compile(r"--?[a-z][a-z0-9-]*", re.IGNORECASE)
_SAFE_COMMAND_TOKEN = frozenset(
    {
        "repoproof.cli",
        "tool",
        "add",
        "build",
        "mcp",
        "audit",
        "withdraw",
        "agent-run",
        "guided-run",
        "host-run",
    }
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _stamp_now() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Replace *path* with one complete JSON object on the same filesystem."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        tmp.unlink(missing_ok=True)


def _read_json_object(path: Path) -> dict[str, Any]:
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise OSError(f"control file is not a regular file: {path}")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > 1024 * 1024:
            raise OSError(f"control file type/size is invalid: {path}")
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
            value = json.load(stream)
    finally:
        os.close(fd)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def sanitize_argv(argv: Sequence[str]) -> list[str]:
    """Persist only command structure; every free-form value is redacted."""
    safe: list[str] = []
    for index, raw in enumerate(argv):
        arg = str(raw)
        if index == 0:
            safe.append(Path(arg).name or _REDACTED)
        elif arg in _SAFE_COMMAND_TOKEN:
            safe.append(arg)
        elif _SAFE_OPTION.fullmatch(arg) and not _SENSITIVE_OPTION.search(arg):
            safe.append(arg)
        else:
            safe.append(_REDACTED)
    return safe


def _process_state(pid: int) -> str | None:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    state = result.stdout.strip()
    return state if result.returncode == 0 and state else None


def process_identity(pid: int | None) -> dict[str, Any] | None:
    """Return a start-time identity; PID alone is never accepted as ownership."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        raw = proc_stat.read_text(encoding="utf-8")
        fields_after_name = raw.rsplit(")", 1)[1].split()
        start_ticks = fields_after_name[19]
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        ).strip()
        token = f"linux:{boot_id}:{start_ticks}"
        command_hash = hashlib.sha256(
            Path(f"/proc/{pid}/cmdline").read_bytes()
        ).hexdigest()
    except (OSError, IndexError):
        try:
            started_result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "lstart="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            command_result = subprocess.run(
                # -ww:procps 的 ps 尊重 COLUMNS(pytest 设 80),长命令行
                # 会被截——身份哈希对截断串就是换个人(postflight 同病)。
                ["ps", "-ww", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        started = " ".join(started_result.stdout.split())
        command = " ".join(command_result.stdout.split())
        if (
            started_result.returncode != 0
            or command_result.returncode != 0
            or not started
            or not command
        ):
            return None
        token = f"ps:{started}"
        marker = re.search(r"(?:^|\s)--identity\s+(\S+)", command)
        command_material = f"identity:{marker.group(1)}" if marker else command
        command_hash = hashlib.sha256(command_material.encode("utf-8")).hexdigest()
    return {"pid": pid, "start_token": token, "command_sha256": command_hash}


def process_matches(pid: int | None, expected: object) -> bool:
    """Check both liveness and process birth identity (PID-reuse safe)."""
    # pid=None 时 process_identity 恒返回 None ≠ dict,原本也在此返回 False;
    # 前置显式判掉只是让类型收窄可证。
    if pid is None or not isinstance(expected, dict) or process_identity(pid) != expected:
        return False
    state = _process_state(pid)
    if not state:
        return False
    return "Z" not in state


def pid_is_running(pid: object) -> bool:
    """Legacy fail-closed probe; never treats PID liveness as ownership."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    state = _process_state(pid)
    if not state:
        return False
    return "Z" not in state


def legacy_state_blocker(path: Path) -> str | None:
    """Block an unowned legacy execution unless its PID is proven stopped."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        state = _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return f"旧执行状态损坏，无法证明任务已结束：{path} ({exc})"
    if state.get("schema_version") == STATE_SCHEMA_VERSION:
        durable = read_durable_job_state(path)
        if durable.get("status") == RUNNING:
            return f"V2 执行状态仍指向存活任务，拒绝并发：{path}"
        if durable.get("error_code") == STATE_INVALID:
            return f"V2 执行状态无法验证，拒绝并发：{path}"
        return None
    pid = state.get("pid")
    if pid_is_running(pid):
        return (
            "已有任务在运行：旧执行状态仍指向存活进程，"
            f"拒绝与 V2 并发：{path} (pid={pid})"
        )
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return f"旧执行状态缺少可核验 PID，无法证明任务已结束：{path}"
    return None


def _stop_owned_child(state: Mapping[str, Any]) -> str:
    pid = state.get("child_pid")
    identity = state.get("child_process_identity")
    if not isinstance(pid, int) or not isinstance(identity, dict):
        return "NOT_RECORDED"
    if not process_matches(pid, identity):
        return "NOT_RUNNING_OR_IDENTITY_CHANGED"
    try:
        os.killpg(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    deadline = time.monotonic() + 2
    while process_matches(pid, identity) and time.monotonic() < deadline:
        time.sleep(0.02)
    return "TERMINATED" if not process_matches(pid, identity) else "UNCONFIRMED"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_signature(path: Path) -> dict[str, Any] | None:
    try:
        stat = path.lstat()
        if path.is_symlink():
            return {
                "kind": "symlink",
                "target": os.readlink(path),
                "mtime_ns": stat.st_mtime_ns,
            }
        if path.is_file():
            return {
                "kind": "file",
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": _hash_file(path),
            }
        if path.is_dir():
            return {
                "kind": "directory",
                "mtime_ns": stat.st_mtime_ns,
            }
    except OSError:
        return None
    return None


def artifact_snapshot(expectation: object) -> dict[str, Any] | None:
    """Capture an exact path or glob set without interpreting command output."""
    if not isinstance(expectation, dict):
        return None
    kind = expectation.get("kind")
    if kind == "path" and isinstance(expectation.get("path"), str):
        return _path_signature(Path(expectation["path"]))
    if (
        kind == "glob"
        and isinstance(expectation.get("root"), str)
        and isinstance(expectation.get("pattern"), str)
    ):
        root = Path(expectation["root"])
        matches = []
        try:
            candidates = sorted(root.glob(expectation["pattern"]))
        except (OSError, ValueError):
            candidates = []
        for candidate in candidates:
            signature = _path_signature(candidate)
            if signature is not None:
                matches.append({"path": str(candidate), "signature": signature})
        return {"kind": "glob", "matches": matches}
    return None


def _artifact_changed(
    expectation: object,
    before: object,
    after: object,
) -> bool:
    if not isinstance(expectation, dict) or after is None or after == before:
        return False
    if expectation.get("kind") == "glob":
        return bool(
            isinstance(after, dict)
            and isinstance(after.get("matches"), list)
            and any(
                isinstance(match, dict)
                and isinstance(match.get("signature"), dict)
                and match["signature"].get("kind") == "file"
                for match in after["matches"]
            )
        )
    return bool(
        expectation.get("kind") == "path"
        and isinstance(after, dict)
        and after.get("kind") == "file"
    )


def core_lock_path(root: Path) -> Path:
    return Path(root) / CORE_EXECUTION_LOCK


def inspect_core_lock(root: Path) -> dict[str, Any] | None:
    """Inspect without healing: malformed/dead owners are STALE and still block."""
    path = core_lock_path(root)
    if not path.exists():
        return None
    try:
        lock = _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "state": "STALE",
            "path": str(path),
            "reason": f"锁文件损坏：{exc}",
        }
    active = process_matches(lock.get("pid"), lock.get("process_identity"))
    return {
        **lock,
        "state": "ACTIVE" if active else "STALE",
        "path": str(path),
        "reason": None if active else "锁持有进程已结束或进程身份不匹配",
    }


def _acquire_core_lock(
    root: Path,
    *,
    job_id: str,
    lease_id: str,
    kind: str,
    label: str,
) -> tuple[Path | None, dict[str, Any] | None]:
    path = core_lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    identity = process_identity(os.getpid())
    if identity is None:
        return None, {"state": "STALE", "reason": "无法确认启动进程身份"}
    payload = {
        "schema_version": 1,
        "job_id": job_id,
        "lease_id": lease_id,
        "kind": kind,
        "label": label,
        "pid": os.getpid(),
        "process_identity": identity,
        "acquired_at": _utc_now(),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return None, inspect_core_lock(root)
    except OSError as exc:
        return None, {"state": "STALE", "reason": f"无法创建 Core 锁：{exc}"}
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, None


def _replace_core_lock_owner(
    path: Path,
    *,
    job_id: str,
    lease_id: str,
    pid: int,
    identity: Mapping[str, Any],
) -> bool:
    try:
        lock = _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if lock.get("job_id") != job_id or lock.get("lease_id") != lease_id:
        return False
    lock["pid"] = pid
    lock["process_identity"] = dict(identity)
    lock["worker_claimed_at"] = _utc_now()
    atomic_write_json(path, lock)
    return True


def _release_core_lock(path: Path, *, job_id: str, lease_id: str) -> bool:
    try:
        lock = _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    if lock.get("job_id") != job_id or lock.get("lease_id") != lease_id:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def _state_expectation(state: Mapping[str, Any]) -> dict[str, Any] | None:
    expectation = state.get("artifact_expectation")
    return dict(expectation) if isinstance(expectation, dict) else None


def _note_for(state: Mapping[str, Any]) -> str:
    label = str(state.get("label") or "后台任务")
    status = state.get("status")
    if status == RUNNING:
        return f"{label} 正在后台运行。"
    if status == SUCCEEDED:
        return f"{label} 已成功结束，并形成本次预期产物。"
    if status == INTERRUPTED:
        return f"{label} 的监督 worker 已中断；结果未被猜测为成功。"
    if state.get("error"):
        return f"{label} 失败：{state['error']}；请查看日志。"
    exit_code = state.get("exit_code")
    if exit_code not in (None, 0):
        return f"{label} 失败（退出码 {exit_code}）；请查看日志。"
    return f"{label} 失败：退出码为 0，但未形成本次预期产物。"


def _compat_projection(state: dict[str, Any]) -> dict[str, Any]:
    status = state.get("status")
    state["alive"] = status == RUNNING
    state["finished"] = status in TERMINAL_STATUSES
    state["ok"] = status == SUCCEEDED
    state["note"] = _note_for(state)
    return state


def _invalid_state(note: str) -> dict[str, Any]:
    return _compat_projection(
        {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": INTERRUPTED,
            "pid": None,
            "process_identity": None,
            "exit_code": None,
            "artifact_before": None,
            "artifact_after": None,
            "error": note,
            "error_code": STATE_INVALID,
            "label": "后台任务",
        }
    )


def _state_validation_error(state: Mapping[str, Any]) -> str | None:
    """Validate the persisted ProductJobStateV2 envelope and its outcome.

    The state file is an observation, not an authority.  In particular, a
    hand-written ``SUCCEEDED`` token cannot override the worker invariant that
    success requires both exit code zero and a newly produced/changed expected
    artifact.
    """

    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        return f"不受支持的后台任务状态版本：{state.get('schema_version')!r}"
    status = state.get("status")
    if status not in {RUNNING, *TERMINAL_STATUSES}:
        return f"未知后台任务状态：{status!r}"

    required = {
        "job_id",
        "kind",
        "action",
        "label",
        "pid",
        "process_identity",
        "exit_code",
        "argv",
        "argv_projection_sha256",
        "started_at",
        "started_at_utc",
        "finished_at",
        "artifact_expectation",
        "artifact_before",
        "artifact_after",
        "error",
        "error_code",
    }
    missing = sorted(required.difference(state))
    if missing:
        return f"后台任务状态缺少字段：{', '.join(missing)}"
    for field in ("job_id", "kind", "action", "label", "started_at", "started_at_utc"):
        if not isinstance(state.get(field), str) or not state[field]:
            return f"后台任务状态字段 {field} 无效"
    if not isinstance(state.get("argv"), list) or not all(
        isinstance(value, str) for value in state["argv"]
    ):
        return "后台任务状态字段 argv 无效"
    projection_hash = state.get("argv_projection_sha256")
    if not isinstance(projection_hash, str) or re.fullmatch(
        r"[0-9a-f]{64}", projection_hash
    ) is None:
        return "后台任务状态字段 argv_projection_sha256 无效"
    pid = state.get("pid")
    identity = state.get("process_identity")
    start_failed_without_pid = (
        status == FAILED
        and state.get("error_code") == WORKER_START_FAILED
        and pid is None
        and identity is None
    )
    if not start_failed_without_pid:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return "后台任务状态字段 pid 无效"
        if not isinstance(identity, dict):
            return "后台任务状态字段 process_identity 无效"
    if state.get("artifact_expectation") is not None and not isinstance(
        state.get("artifact_expectation"), dict
    ):
        return "后台任务状态字段 artifact_expectation 无效"
    for field in ("artifact_before", "artifact_after"):
        if state.get(field) is not None and not isinstance(state.get(field), dict):
            return f"后台任务状态字段 {field} 无效"
    result_json_sha256 = state.get("result_json_sha256")
    if result_json_sha256 is not None and (
        not isinstance(result_json_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", result_json_sha256) is None
    ):
        return "后台任务状态字段 result_json_sha256 无效"

    if status == RUNNING:
        if state.get("finished_at") is not None or state.get("exit_code") is not None:
            return "RUNNING 状态不能包含终态时间或退出码"
        return None

    if not isinstance(state.get("finished_at"), str) or not state["finished_at"]:
        return "终态缺少 finished_at"
    exit_code = state.get("exit_code")
    if exit_code is not None and (
        not isinstance(exit_code, int) or isinstance(exit_code, bool)
    ):
        return "终态 exit_code 无效"
    if status == SUCCEEDED:
        expectation = state.get("artifact_expectation")
        if exit_code != 0:
            return "SUCCEEDED 状态的退出码不是 0"
        if state.get("error") is not None or state.get("error_code") is not None:
            return "SUCCEEDED 状态不能包含错误"
        if not _artifact_changed(
            expectation,
            state.get("artifact_before"),
            state.get("artifact_after"),
        ):
            return "SUCCEEDED 状态没有可核验的新产物或产物变化"
    elif not isinstance(state.get("error_code"), str) or not state["error_code"]:
        return f"{status} 终态缺少 error_code"
    return None


def _update_running_state(
    path: Path,
    *,
    job_id: str,
    changes: Mapping[str, Any],
) -> dict[str, Any] | None:
    try:
        current = _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if current.get("job_id") != job_id or current.get("status") != RUNNING:
        return None
    updated = {**current, **dict(changes)}
    atomic_write_json(path, updated)
    return updated


def read_durable_job_state(path: Path) -> dict[str, Any]:
    """Read V2 state and durably mark a missing/reused worker INTERRUPTED."""
    path = Path(path)
    try:
        state = _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _invalid_state(f"后台任务状态文件损坏：{exc}")
    if validation_error := _state_validation_error(state):
        return _invalid_state(validation_error)
    if state.get("status") == RUNNING and not process_matches(
        state.get("pid"), state.get("process_identity")
    ):
        expectation = _state_expectation(state)
        child_cleanup = _stop_owned_child(state)
        interrupted = _update_running_state(
            path,
            job_id=str(state.get("job_id")),
            changes={
                "status": INTERRUPTED,
                "finished_at": _utc_now(),
                "exit_code": None,
                "artifact_after": artifact_snapshot(expectation),
                "error": "监督 worker 已结束或进程身份不匹配",
                "error_code": WORKER_INTERRUPTED,
                "child_cleanup": child_cleanup,
            },
        )
        if interrupted is not None:
            state = interrupted
        else:
            try:
                state = _read_json_object(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                return _invalid_state(f"后台任务状态并发更新失败：{exc}")
    return _compat_projection(state)


def _conflict_message(conflict: Mapping[str, Any] | None) -> str:
    if not conflict:
        return "Core execution 锁不可用。"
    if conflict.get("state") == "STALE":
        return (
            "Core execution 锁已陈旧或损坏；系统按 fail-closed 拒绝自动清理。"
            f" {conflict.get('reason') or ''}"
        ).strip()
    return f"已有 Core 任务在运行：{conflict.get('label') or conflict.get('kind') or '未知任务'}"


@contextmanager
def core_execution_lease(
    root: Path,
    *,
    kind: str,
    label: str,
) -> Iterator[None]:
    """Serialize one synchronous Core mutation with Studio/Lab workers.

    Some Lab operations are intentionally synchronous because Streamlit needs
    their structured return value.  They still participate in the exact same
    repository mutex as detached Product jobs.  Stale locks are never healed
    here: an operator must inspect them first.
    """

    legacy_paths = (
        Path(root) / LEGACY_LAB_STATE,
        Path(
            os.environ.get("REPOPROOF_UI_STATE_ROOT", "~/.repoproof")
        ).expanduser()
        / "product-job.json",
    )
    for legacy_path in legacy_paths:
        if reason := legacy_state_blocker(legacy_path):
            raise CoreExecutionConflictError(reason)

    job_id = uuid.uuid4().hex
    lease_id = secrets.token_hex(24)
    path, conflict = _acquire_core_lock(
        Path(root),
        job_id=job_id,
        lease_id=lease_id,
        kind=kind,
        label=label,
    )
    if path is None:
        raise CoreExecutionConflictError(_conflict_message(conflict))
    body_failed = False
    try:
        yield
    except BaseException:
        body_failed = True
        raise
    finally:
        released = _release_core_lock(path, job_id=job_id, lease_id=lease_id)
        if not released and not body_failed:
            raise CoreExecutionConflictError(
                "Core execution 锁的所有权在同步任务结束前发生变化；结果按 fail-closed 处理。"
            )


def start_durable_job(
    *,
    root: Path,
    state_path: Path,
    worker_python: str,
    argv: Sequence[str],
    cwd: Path,
    log_path: Path,
    kind: str,
    label: str,
    expected_artifact: Path | None = None,
    expected_artifact_glob: str | None = None,
    env: Mapping[str, str] | None = None,
    metadata: Mapping[str, Any] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Acquire the repo mutex and launch one detached durable worker."""
    root = Path(root)
    state_path = Path(state_path)
    log_path = Path(log_path)
    job_id = job_id or uuid.uuid4().hex
    if re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
        return {"ok": False, "error": "job_id 必须是 32 位小写十六进制标识。"}
    lease_id = secrets.token_hex(24)
    lock_path, conflict = _acquire_core_lock(
        root,
        job_id=job_id,
        lease_id=lease_id,
        kind=kind,
        label=label,
    )
    if lock_path is None:
        return {
            "ok": False,
            "error": _conflict_message(conflict),
            "core_lock": conflict,
        }

    expectation: dict[str, Any] | None = None
    if expected_artifact is not None and expected_artifact_glob is None:
        expectation = {"kind": "path", "path": str(Path(expected_artifact))}
    elif expected_artifact is None and expected_artifact_glob is not None:
        expectation = {
            "kind": "glob",
            "root": str(root),
            "pattern": expected_artifact_glob,
        }
    elif expected_artifact is not None and expected_artifact_glob is not None:
        _release_core_lock(lock_path, job_id=job_id, lease_id=lease_id)
        return {"ok": False, "error": "预期产物只能配置 exact path 或 glob 之一。"}

    started_at = _stamp_now()
    argv_projection = sanitize_argv(argv)
    state: dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "job_id": job_id,
        "status": RUNNING,
        "pid": None,
        "process_identity": None,
        "child_pid": None,
        "child_process_identity": None,
        "exit_code": None,
        "kind": kind,
        "action": kind,
        "label": label,
        "log": str(log_path),
        "cwd": str(Path(cwd)),
        "argv": argv_projection,
        "argv_projection_sha256": hashlib.sha256(
            json.dumps(
                argv_projection,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "started_at": started_at,
        "started_at_utc": _utc_now(),
        "finished_at": None,
        "artifact_expectation": expectation,
        "expected_artifact": (
            str(expected_artifact) if expected_artifact is not None else None
        ),
        "expected_artifact_glob": expected_artifact_glob,
        "artifact_before": artifact_snapshot(expectation),
        "artifact_after": None,
        "core_lock": str(lock_path),
        "error": None,
        "error_code": None,
    }
    reserved = set(state)
    if metadata:
        state.update({key: value for key, value in metadata.items() if key not in reserved})
    # Product jobs bind their semantic result path through metadata.  The
    # worker fills the hash only after the child has stopped, so JobState stays
    # a process observation while still making result replacement detectable.
    if isinstance(state.get("result_json"), str):
        state.setdefault("result_json_sha256", None)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(
            [
                worker_python,
                "-m",
                "repoproof.execution.core_execution",
                "--worker",
                "--identity",
                job_id,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(root),
            env=dict(env) if env is not None else dict(os.environ),
            start_new_session=True,
            text=True,
        )
        _start_process_reaper(proc)
        identity = process_identity(proc.pid)
        if identity is None or proc.stdin is None:
            proc.terminate()
            raise RuntimeError("无法确认 durable worker 的进程身份")
        state["pid"] = proc.pid
        state["process_identity"] = identity
        atomic_write_json(state_path, state)
        if not _replace_core_lock_owner(
            lock_path,
            job_id=job_id,
            lease_id=lease_id,
            pid=proc.pid,
            identity=identity,
        ):
            proc.terminate()
            raise RuntimeError("Core execution 锁在 worker 接管前发生变化")
        request = {
            "job_id": job_id,
            "lease_id": lease_id,
            "state_path": str(state_path),
            "core_lock_path": str(lock_path),
            "argv": [str(value) for value in argv],
            "cwd": str(Path(cwd)),
            "log_path": str(log_path),
        }
        proc.stdin.write(json.dumps(request, ensure_ascii=False))
        proc.stdin.close()
    except (OSError, RuntimeError, ValueError) as exc:
        state.update(
            {
                "status": FAILED,
                "finished_at": _utc_now(),
                "error": f"durable worker 启动失败：{exc}",
                "error_code": WORKER_START_FAILED,
            }
        )
        atomic_write_json(state_path, state)
        _release_core_lock(lock_path, job_id=job_id, lease_id=lease_id)
        return {"ok": False, "error": state["error"]}
    return {
        "ok": True,
        "pid": proc.pid,
        "job_id": job_id,
        "status": RUNNING,
        "note": f"已在后台启动：{label}",
    }


def _worker(request: Mapping[str, Any]) -> int:
    job_id = str(request["job_id"])
    lease_id = str(request["lease_id"])
    state_path = Path(str(request["state_path"]))
    lock_path = Path(str(request["core_lock_path"]))
    argv = request.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) for v in argv):
        raise ValueError("worker argv must be a non-empty string list")
    cwd = Path(str(request["cwd"]))
    log_path = Path(str(request["log_path"]))
    interrupted_by: list[int] = []
    child: subprocess.Popen[bytes] | None = None

    def _kill_child_group() -> None:
        if child is None:
            return
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            child.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass

    def _interrupt(signum: int, _frame: object) -> None:
        interrupted_by.append(signum)
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass

    signal.signal(signal.SIGTERM, _interrupt)
    signal.signal(signal.SIGINT, _interrupt)
    exit_code: int | None = None
    error: str | None = None
    try:
        if interrupted_by:
            raise InterruptedError("worker interrupted before child launch")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as stream:
            child = subprocess.Popen(
                argv,
                cwd=str(cwd),
                stdout=stream,
                stderr=subprocess.STDOUT,
                env=dict(os.environ),
                start_new_session=True,
            )
            child_identity = process_identity(child.pid)
            if child_identity is None:
                _kill_child_group()
                error = "无法确认子进程身份；已终止子进程组"
                exit_code = child.returncode
            elif _update_running_state(
                state_path,
                job_id=job_id,
                changes={
                    "child_pid": child.pid,
                    "child_process_identity": child_identity,
                },
            ) is None:
                # The state is missing/tampered, so there is no safe owner that
                # can later reap the child.  Kill now and deliberately retain
                # the Core lock as a stale fail-closed inspection marker.
                _kill_child_group()
                return 2
            else:
                exit_code = child.wait()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        error = f"执行失败：{exc}"

    try:
        state = _read_json_object(state_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return 2
    expectation = _state_expectation(state)
    after = artifact_snapshot(expectation)
    result_signature = None
    if isinstance(state.get("result_json"), str):
        result_signature = _path_signature(Path(state["result_json"]))
    result_json_sha256 = (
        result_signature.get("sha256")
        if isinstance(result_signature, dict)
        and result_signature.get("kind") == "file"
        else None
    )
    if interrupted_by:
        status = INTERRUPTED
        error = f"worker 收到信号 {interrupted_by[-1]}"
        error_code = WORKER_INTERRUPTED
    elif error is not None or exit_code not in (0,):
        status = FAILED
        if error is not None:
            error_code = EXECUTION_ERROR
        else:
            error = f"命令退出码为 {exit_code}"
            error_code = NONZERO_EXIT
    elif not _artifact_changed(expectation, state.get("artifact_before"), after):
        status = FAILED
        error = "命令退出码为 0，但未形成本次预期产物"
        error_code = EXPECTED_ARTIFACT_MISSING
    else:
        status = SUCCEEDED
        error_code = None
    finalized = _update_running_state(
        state_path,
        job_id=job_id,
        changes={
            "status": status,
            "finished_at": _utc_now(),
            "exit_code": exit_code,
            "artifact_after": after,
            "result_json_sha256": result_json_sha256,
            "error": error,
            "error_code": error_code,
        },
    )
    if finalized is None:
        # A missing/tampered state cannot be called durable.  Keep the mutex;
        # once this worker exits it is a stale fail-closed lock for inspection.
        return 2
    _release_core_lock(lock_path, job_id=job_id, lease_id=lease_id)
    return 0


def _main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--identity")
    args = parser.parse_args()
    if not args.worker:
        return 2
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            return 2
        if args.identity != request.get("job_id"):
            return 2
        return _worker(request)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess
    raise SystemExit(_main())
