"""Shared containment rules for one installed local-tool command."""

from __future__ import annotations

import fcntl
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

TOOL_NAME_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
_TOOL_NAME = re.compile(TOOL_NAME_PATTERN)
INSTALL_LOCK_NAME = ".repoproof-install.lock"


class ToolPathError(ValueError):
    """A tool name or installation path escapes the managed destination."""


def validate_tool_name(name: object) -> str:
    if not isinstance(name, str) or not _TOOL_NAME.fullmatch(name):
        raise ToolPathError(f"非法 tool.name={name!r};必须是小写 CLI slug")
    return name


def validate_tool_task_id(name: object, task_id: object) -> str:
    """Bind a frozen task version to its stable local command slug."""

    valid_name = validate_tool_name(name)
    if not isinstance(task_id, str) or not re.fullmatch(
        rf"tool-{re.escape(valid_name)}-v[1-9][0-9]*", task_id
    ):
        raise ToolPathError(
            f"task_id={task_id!r} 未绑定 tool.name={valid_name!r} 的版本谱系"
        )
    return task_id


def canonical_tool_path(dest_root: Path, name: object) -> Path:
    """Return ``<dest_root>/<name>`` after slug and parent containment checks."""

    valid_name = validate_tool_name(name)
    root = Path(dest_root).resolve()
    path = root / valid_name
    if path.parent != root or path.is_symlink():
        raise ToolPathError(f"tool.name 逃逸 dest_root:{valid_name!r}")
    resolved = path.resolve()
    if resolved != path or resolved.parent != root:
        raise ToolPathError(f"tool.name 逃逸 dest_root:{valid_name!r}")
    return path


def ensure_safe_package_tree(root: Path) -> Path:
    """Reject package symlinks outside the reproducible top-level ``.venv``.

    Existing verified tools use the standard virtualenv interpreter links, so
    that generated environment remains opaque.  The package source, manifests,
    evidence, public fixtures, launchers, build script, and MCP target must all
    be ordinary in-tree entries.
    """

    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ToolPathError(f"受管工具包不是普通目录:{root}")

    def walk(directory: Path) -> None:
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = directory / entry.name
                    if entry.is_symlink():
                        raise ToolPathError(f"受管工具包禁止 symlink:{path}")
                    if directory == root and entry.name == ".venv":
                        if not entry.is_dir(follow_symlinks=False):
                            raise ToolPathError(f"工具包 .venv 必须为普通目录:{path}")
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        walk(path)
                    elif not entry.is_file(follow_symlinks=False):
                        raise ToolPathError(f"受管工具包禁止特殊文件:{path}")
        except OSError as exc:
            raise ToolPathError(f"无法安全遍历受管工具包 {directory}:{exc}") from exc

    walk(root)
    return root


def ensure_managed_directory(dest_root: Path, *components: str) -> Path:
    """Create a root-owned directory chain without following symlink components."""

    root = Path(dest_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    current = root
    for component in components:
        if (
            not isinstance(component, str)
            or not component
            or component in {".", ".."}
            or Path(component).name != component
        ):
            raise ToolPathError(f"非法受管目录组件:{component!r}")
        current = current / component
        try:
            current.mkdir()
        except FileExistsError:
            pass
        if current.is_symlink() or not current.is_dir():
            raise ToolPathError(f"受管目录禁止 symlink/非目录:{current}")
        if current.resolve().parent != current.parent.resolve():
            raise ToolPathError(f"受管目录逃逸 dest_root:{current}")
    return current


def _open_regular_nofollow(path: Path, flags: int, mode: int = 0o600) -> int:
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode) or existing.st_nlink != 1
    ):
        raise ToolPathError(f"受管控制文件必须是单链接普通文件:{path}")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags | nofollow | cloexec, mode)
    except OSError as exc:
        raise ToolPathError(f"受管控制文件无法安全打开:{path}:{exc}") from exc
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(fd)
        raise ToolPathError(f"受管控制文件必须是单链接普通文件:{path}")
    return fd


def read_control_file(path: Path, *, missing_ok: bool = False) -> bytes | None:
    """Read a root-owned regular file without following a symlink/hardlink."""

    path = Path(path)
    if missing_ok and not path.exists() and not path.is_symlink():
        return None
    fd = _open_regular_nofollow(path, os.O_RDONLY)
    with os.fdopen(fd, "rb") as fh:
        return fh.read()


def append_control_file(path: Path, data: bytes) -> None:
    """Append one already-encoded record without following links."""

    path = Path(path)
    fd = _open_regular_nofollow(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    try:
        written = os.write(fd, data)
        if written != len(data):
            raise ToolPathError(
                f"受管控制文件 append 不完整:{path}:{written}/{len(data)}"
            )
    finally:
        os.close(fd)


def validate_control_target(path: Path, *, missing_ok: bool = False) -> None:
    """Validate a control-file target before an atomic replacement."""

    path = Path(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return
        raise ToolPathError(f"受管控制文件不存在:{path}") from None
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ToolPathError(f"受管控制文件必须是单链接普通文件:{path}")


@contextmanager
def control_file_lock(dest_root: Path, filename: str) -> Iterator[None]:
    """Take an exclusive flock on a no-follow root-owned control file."""

    root = Path(dest_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if Path(filename).name != filename:
        raise ToolPathError(f"非法 lock 文件名:{filename!r}")
    lock_path = root / filename
    fd = _open_regular_nofollow(lock_path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextmanager
def tool_install_lock(dest_root: Path) -> Iterator[None]:
    """Return the shared package/registry/MCP/audit serialization context."""

    with control_file_lock(dest_root, INSTALL_LOCK_NAME):
        yield
