"""Shared Product boundary for untrusted offline helper execution.

Reference implementations and task-authored semantic verifiers are different
producers, but both execute third-party-derived code.  The boundary therefore
belongs to the execution layer rather than either intake or verification:

* provider credentials and RepoProof connection settings are removed;
* network access is denied by a reviewed OS sandbox;
* writes are limited to one disposable directory.

This module deliberately contains no repository, artifact-format, or task
vocabulary.  Callers retain responsibility for classifying an unavailable
sandbox in their own public error model.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


class OfflineSandboxUnavailable(RuntimeError):
    """The host cannot enforce RepoProof's reviewed Product boundary."""


def sanitised_subprocess_env(
    home: Path,
    extra_paths: list[str],
    *,
    write_bytecode: bool = False,
) -> dict[str, str]:
    """Return the minimum environment needed by an offline helper process.

    Bytecode writing stays off by default: helper processes import from frozen,
    protected trees and a stray ``__pycache__`` there is either tampering or
    noise in a tree hash.  A process that stands in for **the user's own run**
    passes ``write_bytecode=True`` instead: measuring a producer under an
    interpreter flag the user will not have hides every defect that flag
    suppresses (incident-acceptance-env-more-permissive-*).
    """

    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "HOME": str(home),
        "TMPDIR": str(home),
    }
    if not write_bytecode:
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra_paths:
        environment["PYTHONPATH"] = os.pathsep.join(extra_paths)
    return environment


def offline_sandbox_argv(argv: list[str], writable_root: Path) -> list[str]:
    """Wrap ``argv`` in the reviewed offline/write-contained host sandbox."""

    sandbox = Path("/usr/bin/sandbox-exec")
    if sys.platform != "darwin" or not sandbox.is_file():
        raise OfflineSandboxUnavailable(
            "no reviewed offline helper sandbox is available on this host"
        )
    real_root = Path(writable_root).resolve()
    escaped_root = str(real_root).replace("\\", "\\\\").replace('"', '\\"')
    profile = (
        "(version 1)"
        "(allow default)"
        "(deny network*)"
        "(deny file-write*)"
        f'(allow file-write* (subpath "{escaped_root}") '
        '(literal "/dev/null"))'
    )
    return [str(sandbox), "-p", profile, *argv]
