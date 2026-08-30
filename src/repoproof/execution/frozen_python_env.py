"""Disposable Python environments derived only from frozen wheel evidence.

Semantic verification must not execute with the candidate tool's own virtual
environment: that environment is part of the untrusted deliverable and may
shadow imports or alter interpreter startup.  This module creates a fresh
interpreter from the task package's exact, hash-bound wheel set.

The mechanism deliberately has no knowledge of repositories, capabilities or
artifact formats.  It admits a wheel tree by identity, installs every admitted
wheel explicitly with dependency resolution and network access disabled, and
then destroys the environment after the caller finishes.
"""

from __future__ import annotations

import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from repoproof.execution.offline_sandbox import sanitised_subprocess_env
from repoproof.harness.wheelhouse import verify_wheelhouse


class FrozenPythonEnvironmentError(RuntimeError):
    """A trusted interpreter cannot be reconstructed from frozen evidence."""


def _python_in_venv(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _admitted_wheel_paths(
    wheelhouse: Path,
    expected_wheels: Mapping[str, str],
) -> list[Path]:
    paths: list[Path] = []
    for name in sorted(expected_wheels):
        relative = Path(name)
        if (
            relative.name != name
            or relative.is_absolute()
            or relative.suffix.lower() != ".whl"
        ):
            raise FrozenPythonEnvironmentError(
                "frozen wheel identity contains an unsafe filename"
            )
        candidate = wheelhouse / name
        try:
            metadata = candidate.lstat()
        except OSError as exc:
            raise FrozenPythonEnvironmentError(
                "frozen wheel is missing or unreadable"
            ) from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise FrozenPythonEnvironmentError(
                "frozen wheel must be a regular non-symlink file"
            )
        paths.append(candidate)
    if not paths:
        raise FrozenPythonEnvironmentError("frozen wheel identity is empty")
    return paths


@contextmanager
def frozen_python_environment(
    *,
    wheelhouse: Path,
    expected_wheels: Mapping[str, str] | None,
    expected_root: str | None,
    timeout_s: int = 300,
) -> Iterator[str]:
    """Yield a disposable interpreter reconstructed from exact frozen wheels.

    Package installation is an infrastructure operation, not task code
    execution.  It uses a scrubbed environment, an isolated temporary home,
    explicit wheel paths, ``--no-index`` and ``--no-deps``.  Task-authored code
    remains subject to the separate offline OS sandbox at execution time.
    """

    wheelhouse = Path(wheelhouse)
    if (
        expected_wheels is None
        or expected_root is None
        or wheelhouse.is_symlink()
        or not wheelhouse.is_dir()
    ):
        raise FrozenPythonEnvironmentError(
            "ToolSpec v3 requires a regular hash-bound wheelhouse"
        )
    try:
        verify_wheelhouse(
            wheelhouse,
            expected_wheels=dict(expected_wheels),
            expected_root=expected_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise FrozenPythonEnvironmentError(
            "wheelhouse differs from the frozen task-package identity"
        ) from exc
    wheels = _admitted_wheel_paths(wheelhouse, expected_wheels)

    with tempfile.TemporaryDirectory(prefix="rp-frozen-python-") as temp:
        root = Path(temp)
        venv = root / "venv"
        environment = sanitised_subprocess_env(root, [])
        try:
            created = subprocess.run(  # noqa: S603 - fixed local interpreter
                [sys.executable, "-m", "venv", str(venv)],
                capture_output=True,
                timeout=min(timeout_s, 120),
                env=environment,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FrozenPythonEnvironmentError(
                "disposable verifier interpreter could not be created"
            ) from exc
        if created.returncode != 0:
            raise FrozenPythonEnvironmentError(
                "disposable verifier interpreter could not be created"
            )

        python = _python_in_venv(venv)
        try:
            installed = subprocess.run(  # noqa: S603 - exact admitted wheel argv
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-index",
                    "--no-deps",
                    "--no-cache-dir",
                    *[str(path) for path in wheels],
                ],
                capture_output=True,
                timeout=timeout_s,
                env=environment,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise FrozenPythonEnvironmentError(
                "frozen verifier dependencies could not be installed"
            ) from exc
        if installed.returncode != 0:
            raise FrozenPythonEnvironmentError(
                "frozen verifier dependencies could not be installed"
            )
        yield str(python)
