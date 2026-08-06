"""Oracle integrity: tree hashing + symlink / traversal rejection.

The oracle (contract, fixtures, capability + regression tests) is
hashed before execution and re-checked after. Symlinks inside the
oracle are rejected outright — a symlink could smuggle reads/writes
outside the read-only mount.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class OracleViolation(RuntimeError):
    pass


def hash_tree(root: Path) -> dict[str, str]:
    """Deterministic {relpath: sha256} over all regular files.

    Rejects symlinks and any path that resolves outside ``root``.
    """
    root = Path(root)
    real_root = root.resolve()
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise OracleViolation(f"symlink not allowed in guarded tree: {p}")
        if not p.is_file():
            continue
        try:
            p.resolve().relative_to(real_root)
        except ValueError as exc:  # pragma: no cover - defense in depth
            raise OracleViolation(f"path escapes guarded tree: {p}") from exc
        out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def trees_equal(before: dict[str, str], after: dict[str, str]) -> tuple[bool, list[str]]:
    diffs: list[str] = []
    for rel in sorted(set(before) | set(after)):
        if before.get(rel) != after.get(rel):
            diffs.append(rel)
    return (not diffs, diffs)


def make_read_only(root: Path) -> None:
    """Best-effort physical write protection (chmod a-w) on host."""
    for p in sorted(Path(root).rglob("*"), reverse=True):
        try:
            p.chmod(p.stat().st_mode & ~0o222)
        except OSError:
            pass
    Path(root).chmod(Path(root).stat().st_mode & ~0o222)
