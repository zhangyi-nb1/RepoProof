"""Immutable payload identity for installed Product tools.

The installed package contains both frozen delivery bytes and intentionally
mutable runtime material.  Core must bind the former without pretending that a
rebuilt virtualenv or append-only audit evidence is immutable.  This module
defines that boundary once for registration, listing, release audit and future
runtime guards.

No repository, capability or artifact-format vocabulary belongs here.  The
identity is a canonical tree of regular files, modes and SHA-256 digests.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path


class ToolPackageIdentityError(ValueError):
    """The package tree cannot be given a trustworthy payload identity."""


_VOLATILE_DIR_NAMES = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
})
_VOLATILE_DIR_SUFFIXES = frozenset({".egg-info"})
_VOLATILE_FILE_SUFFIXES = frozenset({".pyc", ".pyo"})


def _excluded(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return False
    # The tool environment is rebuilt from the frozen lock.  Independent
    # semantic verification must never use it as a trusted interpreter.
    if parts[0] == ".venv":
        return True
    # Generated only after activation and guarded independently by the MCP
    # runtime.  It is not part of the verified CLI payload.
    if relative == Path("mcp_server.py"):
        return True
    # Fresh audits append immutable evidence records by design.
    if parts[:2] in {
        ("evidence", "release-audits"),
        ("evidence", "semantic-audits"),
    }:
        return True
    if any(part in _VOLATILE_DIR_NAMES for part in parts):
        return True
    # Editable installs recreate ``<distribution>.egg-info`` beside the
    # verified source tree.  It is generated installation metadata (and is
    # already excluded from the verified git payload by the tool skeleton's
    # ``*.egg-info/`` ignore rule), not an authored delivery byte.  Counting it
    # here makes a clean ``build.sh`` change package identity merely by adding
    # its first egg-info directory.  The resulting installed environment is
    # still bound independently by ``runtime_environment_sha256``.
    if any(
        any(part.endswith(suffix) for suffix in _VOLATILE_DIR_SUFFIXES)
        for part in parts
    ):
        return True
    return relative.suffix in _VOLATILE_FILE_SUFFIXES


def package_payload_sha256(tool_dir: Path) -> str:
    """Hash every immutable package file and its executable mode.

    Symlinks and special files fail closed even when their resolved target would
    look harmless.  Empty directories are not execution inputs and therefore do
    not enter the identity.
    """

    root = Path(tool_dir)
    if root.is_symlink() or not root.is_dir():
        raise ToolPackageIdentityError("tool package must be a regular directory")
    entries: dict[str, dict[str, str | int]] = {}
    for candidate in sorted(root.rglob("*")):
        relative = candidate.relative_to(root)
        if _excluded(relative):
            continue
        try:
            metadata = candidate.lstat()
        except OSError as exc:
            raise ToolPackageIdentityError(
                f"cannot inspect package payload path: {relative}"
            ) from exc
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ToolPackageIdentityError(
                f"package payload contains non-regular path: {relative}"
            )
        try:
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError as exc:
            raise ToolPackageIdentityError(
                f"cannot read package payload path: {relative}"
            ) from exc
        entries[relative.as_posix()] = {
            "sha256": digest,
            "mode": stat.S_IMODE(metadata.st_mode),
        }
    if not entries:
        raise ToolPackageIdentityError("tool package has no immutable payload files")
    canonical = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def runtime_environment_sha256(tool_dir: Path) -> str:
    """Hash the runtime environment separately from immutable package truth.

    ``.venv`` is rebuildable and therefore excluded from
    :func:`package_payload_sha256`.  An ACTIVE audit still binds the exact
    environment it ran.  File symlinks include both link text and resolved
    bytes; directory aliases may only point inside the environment.
    """

    environment = Path(tool_dir) / ".venv"
    if not environment.exists() and not environment.is_symlink():
        payload: dict[str, object] = {
            "schema_version": 1,
            "state": "absent",
            "entries": {},
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
    if environment.is_symlink() or not environment.is_dir():
        raise ToolPackageIdentityError(
            "runtime environment must be a regular directory"
        )

    entries: dict[str, dict[str, str | int]] = {}
    for candidate in sorted(environment.rglob("*")):
        relative = candidate.relative_to(environment)
        if any(part in _VOLATILE_DIR_NAMES for part in relative.parts):
            continue
        if relative.suffix in _VOLATILE_FILE_SUFFIXES:
            continue
        try:
            metadata = candidate.lstat()
        except OSError as exc:
            raise ToolPackageIdentityError(
                f"cannot inspect runtime environment path: {relative}"
            ) from exc
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if stat.S_ISREG(metadata.st_mode):
            try:
                digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            except OSError as exc:
                raise ToolPackageIdentityError(
                    f"cannot read runtime environment path: {relative}"
                ) from exc
            entries[relative.as_posix()] = {
                "kind": "file",
                "mode": stat.S_IMODE(metadata.st_mode),
                "sha256": digest,
            }
            continue
        if stat.S_ISLNK(metadata.st_mode):
            try:
                link_text = os.readlink(candidate)
                resolved = candidate.resolve(strict=True)
                resolved_metadata = resolved.stat()
            except OSError as exc:
                raise ToolPackageIdentityError(
                    f"cannot resolve runtime environment symlink: {relative}"
                ) from exc
            if stat.S_ISDIR(resolved_metadata.st_mode):
                try:
                    resolved.relative_to(environment.resolve())
                except ValueError as exc:
                    raise ToolPackageIdentityError(
                        f"runtime environment directory symlink escapes: {relative}"
                    ) from exc
                entries[relative.as_posix()] = {
                    "kind": "directory-symlink",
                    "mode": stat.S_IMODE(metadata.st_mode),
                    "target": link_text,
                }
                continue
            if not stat.S_ISREG(resolved_metadata.st_mode):
                raise ToolPackageIdentityError(
                    f"runtime environment symlink target is special: {relative}"
                )
            try:
                digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            except OSError as exc:
                raise ToolPackageIdentityError(
                    f"cannot read runtime environment symlink target: {relative}"
                ) from exc
            entries[relative.as_posix()] = {
                "kind": "file-symlink",
                "mode": stat.S_IMODE(metadata.st_mode),
                "target": link_text,
                "target_mode": stat.S_IMODE(resolved_metadata.st_mode),
                "target_sha256": digest,
            }
            continue
        raise ToolPackageIdentityError(
            f"runtime environment contains special path: {relative}"
        )
    payload = {"schema_version": 1, "state": "present", "entries": entries}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
