"""Minimal Docker execution backend: create → argv exec → destroy.

Honest scope (SECURITY.md): containers give isolation, disposal, and
clean replay for HUMAN-ADMITTED public repos. This is NOT a hardened
sandbox for adversarial code.

Lifecycle idea referenced read-only from LocalFlow's Docker workspace
work; implementation is new (see docs/lineage.md).
"""

from __future__ import annotations

import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Mount:
    host: Path
    container: str
    read_only: bool = True

    def as_flag(self) -> str:
        suffix = ":ro" if self.read_only else ""
        return f"{Path(self.host).resolve()}:{self.container}{suffix}"


@dataclass
class ExecResult:
    argv: list[str]
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    stdout: bytes
    stderr: bytes


@dataclass
class DockerExecutionBackend:
    image: str
    cpus: float = 2.0
    memory: str = "2g"
    pids_limit: int = 256
    _containers: list[str] = field(default_factory=list)

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"docker unavailable: {exc}"
        if proc.returncode != 0:
            return False, proc.stderr.decode(errors="replace").strip()
        return True, proc.stdout.decode(errors="replace").strip()

    def pull(self, timeout_s: int = 600) -> ExecResult:
        return _run_host(["docker", "pull", self.image], timeout_s)

    def image_digest(self) -> str | None:
        proc = subprocess.run(
            ["docker", "image", "inspect", self.image, "--format", "{{index .RepoDigests 0}}"],
            capture_output=True,
        )
        if proc.returncode != 0:
            return None
        digest = proc.stdout.decode().strip()
        return digest or None

    def start(
        self,
        *,
        name_prefix: str,
        network: str,
        mounts: list[Mount],
        env: dict[str, str] | None = None,
    ) -> str:
        """Start a long-lived idle container; commands run via exec."""
        name = f"{name_prefix}-{uuid.uuid4().hex[:8]}"
        argv = [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            network,
            "--cpus",
            str(self.cpus),
            "--memory",
            self.memory,
            "--pids-limit",
            str(self.pids_limit),
            "--security-opt",
            "no-new-privileges",
        ]
        for m in mounts:
            argv += ["-v", m.as_flag()]
        for k, v in (env or {}).items():
            argv += ["-e", f"{k}={v}"]
        argv += [self.image, "sleep", "infinity"]
        res = _run_host(argv, 120)
        if res.exit_code != 0:
            raise RuntimeError(
                f"docker run failed ({res.exit_code}): {res.stderr.decode(errors='replace')[:500]}"
            )
        self._containers.append(name)
        return name

    def exec(
        self,
        container: str,
        argv: list[str],
        *,
        timeout_s: int,
        workdir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        """Run argv inside the container with an in-container timeout.

        ``timeout`` (coreutils, present in the slim image) enforces the
        limit inside the container so the process actually dies there;
        exit code 124 maps to timed_out.
        """
        cmd = ["docker", "exec"]
        if workdir:
            cmd += ["-w", workdir]
        for k, v in (env or {}).items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [container, "timeout", str(timeout_s), *argv]
        res = _run_host(cmd, timeout_s + 60)
        if res.exit_code == 124:
            res.timed_out = True
        return ExecResult(
            argv=argv,
            exit_code=res.exit_code,
            timed_out=res.timed_out,
            duration_ms=res.duration_ms,
            stdout=res.stdout,
            stderr=res.stderr,
        )

    def destroy(self, container: str) -> None:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        if container in self._containers:
            self._containers.remove(container)

    def destroy_all(self) -> None:
        for c in list(self._containers):
            self.destroy(c)


def _run_host(argv: list[str], timeout_s: int) -> ExecResult:
    t0 = time.monotonic()
    try:
        proc = subprocess.run(argv, capture_output=True, timeout=timeout_s)
        return ExecResult(
            argv=argv,
            exit_code=proc.returncode,
            timed_out=False,
            duration_ms=int((time.monotonic() - t0) * 1000),
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecResult(
            argv=argv,
            exit_code=None,
            timed_out=True,
            duration_ms=int((time.monotonic() - t0) * 1000),
            stdout=exc.stdout or b"",
            stderr=exc.stderr or b"",
        )
