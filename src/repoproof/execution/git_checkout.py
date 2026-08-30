"""Repository-agnostic identity checks for pinned executable source trees."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitCheckoutIdentityError(ValueError):
    """A checkout does not represent the exact clean frozen revision."""


def verify_clean_git_checkout(
    checkout: Path,
    *,
    expected_commit: str,
    expected_tree: str,
) -> None:
    """Require HEAD/tree identity and reject tracked or untracked drift.

    Interpreter caches are ignored because they cannot shadow source modules;
    every other untracked path fails closed.  The caller must keep its broader
    operation serialized if it needs protection from concurrent local writers.
    """

    root = Path(checkout)
    if root.is_symlink() or not root.is_dir():
        raise GitCheckoutIdentityError("pinned checkout is missing or unsafe")
    for revision, expected in (("HEAD", expected_commit), ("HEAD^{tree}", expected_tree)):
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", revision],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != expected:
            raise GitCheckoutIdentityError(
                "pinned checkout revision differs from frozen identity"
            )
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if status.returncode != 0:
        raise GitCheckoutIdentityError("pinned checkout status is unavailable")
    for line in status.stdout.splitlines():
        if not line:
            continue
        if not line.startswith("?? "):
            raise GitCheckoutIdentityError("pinned checkout has tracked drift")
        relative = line[3:].strip().strip('"')
        parts = Path(relative).parts
        cache_only = (
            "__pycache__" in parts
            or ".pytest_cache" in parts
            or relative.endswith((".pyc", ".pyo"))
        )
        if not cache_only:
            raise GitCheckoutIdentityError("pinned checkout has untracked drift")
