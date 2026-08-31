"""Standalone stdlib-first runtime copied into generated workspace tools.

Keep this module free of ``repoproof`` imports: exported packages vendor this
source verbatim so clean replay never depends on an external RepoProof checkout.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import tomllib
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree


class WorkspaceRuntimeError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


_OFFLINE_PYTHON_LAUNCHER = '''#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
RUNTIME=$(mktemp -d "${TMPDIR:-/tmp}/repoproof-python-runtime.XXXXXX")
cleanup() {
  rm -rf -- "$RUNTIME"
}
trap cleanup EXIT HUP INT TERM
python3 -m venv "$RUNTIME/venv"
"$RUNTIME/venv/bin/python" -m pip install \
  --disable-pip-version-check --no-input --no-compile --no-index \
  --find-links "$ROOT/vendor/wheels" \
  -r "$ROOT/requirements.lock.txt" >/dev/null
"$RUNTIME/venv/bin/python" "$ROOT/__REPOPROOF_APPLICATION__" "$@"
'''


class _HTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.external: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        del tag
        for name, value in attrs:
            if name.lower() in {"href", "src", "action"} and value:
                candidate = value.strip().lower()
                if candidate.startswith(("http://", "https://", "//")):
                    self.external.append(value)


def _match(path: str, pattern: str) -> bool:
    path_parts = PurePosixPath(path).parts
    pattern_parts = PurePosixPath(pattern).parts

    def visit(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        current = pattern_parts[pattern_index]
        if current == "**":
            return visit(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and visit(path_index + 1, pattern_index)
            )
        if path_index >= len(path_parts):
            return False
        if current == "*" or current == path_parts[path_index]:
            return visit(path_index + 1, pattern_index + 1)
        if "*" in current:
            prefix, suffix = current.split("*", 1)
            value = path_parts[path_index]
            if value.startswith(prefix) and value.endswith(suffix):
                return visit(path_index + 1, pattern_index + 1)
        return False

    return visit(0, 0)


def _read_regular(path: Path, maximum: int) -> tuple[bytes, int]:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise WorkspaceRuntimeError("WORKSPACE_SPECIAL_FILE", str(path))
        if before.st_nlink != 1:
            raise WorkspaceRuntimeError("WORKSPACE_HARDLINK_FORBIDDEN", str(path))
        if before.st_size > maximum:
            raise WorkspaceRuntimeError("WORKSPACE_FILE_TOO_LARGE", str(path))
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            total += len(chunk)
            if total > maximum:
                raise WorkspaceRuntimeError("WORKSPACE_FILE_TOO_LARGE", str(path))
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_mode,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_mode,
        ):
            raise WorkspaceRuntimeError("WORKSPACE_FILE_CHANGED_DURING_READ")
        return b"".join(chunks), stat.S_IMODE(after.st_mode)
    finally:
        os.close(descriptor)


def _walk(root: Path, limits: dict) -> list[tuple[str, Path]]:
    if root.is_symlink() or not root.is_dir():
        raise WorkspaceRuntimeError("WORKSPACE_ROOT_UNSAFE")
    rows: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if len(relative.encode("utf-8")) > limits["max_path_bytes"]:
            raise WorkspaceRuntimeError("WORKSPACE_PATH_TOO_LONG", relative)
        if len(PurePosixPath(relative).parts) > limits["max_depth"]:
            raise WorkspaceRuntimeError("WORKSPACE_PATH_TOO_DEEP", relative)
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise WorkspaceRuntimeError("WORKSPACE_SYMLINK_FORBIDDEN", relative)
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceRuntimeError("WORKSPACE_SPECIAL_FILE", relative)
        rows.append((relative, path))
        if len(rows) > limits["max_files"]:
            raise WorkspaceRuntimeError("WORKSPACE_FILE_COUNT_EXCEEDED")
    return rows


def _validate(payload: bytes, profile: str, path: Path) -> None:
    if profile in {"binary_v1", "wheel_v1", "zip_v1"}:
        if not payload:
            raise WorkspaceRuntimeError("WORKSPACE_EMPTY_BINARY", str(path))
    if profile in {"zip_v1", "wheel_v1"}:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise WorkspaceRuntimeError("WORKSPACE_ZIP_INVALID", str(path))
        return
    if profile == "sqlite_v1":
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise WorkspaceRuntimeError("WORKSPACE_SQLITE_INVALID", str(path))
        finally:
            connection.close()
        return
    if profile == "binary_v1":
        return
    text = payload.decode("utf-8")
    if profile == "json_v1":
        json.loads(text)
    elif profile in {"csv_v1", "tsv_v1"}:
        rows = list(csv.reader(text.splitlines(), delimiter="\t" if profile == "tsv_v1" else ","))
        if not rows or any(len(row) != len(rows[0]) for row in rows):
            raise WorkspaceRuntimeError("WORKSPACE_TABLE_INVALID", str(path))
    elif profile == "toml_v1":
        tomllib.loads(text)
    elif profile == "yaml_v1":
        import yaml  # optional package is contract-bound in the lock

        yaml.safe_load(text)
    elif profile == "python_compile_v1":
        compile(text, str(path), "exec")
    elif profile == "shell_v1" and not text.startswith("#!"):
        raise WorkspaceRuntimeError("WORKSPACE_SHELL_SHEBANG_MISSING", str(path))
    elif profile == "html_v1":
        parser = _HTML()
        parser.feed(text)
        if parser.external:
            raise WorkspaceRuntimeError("WORKSPACE_HTML_EXTERNAL_RESOURCE", str(path))
    elif profile in {"xml_v1", "svg_xml_v1"}:
        root = ElementTree.fromstring(text)
        if profile == "svg_xml_v1" and not root.tag.lower().endswith("svg"):
            raise WorkspaceRuntimeError("WORKSPACE_SVG_INVALID", str(path))


def validate_workspace(root: Path, contract: dict) -> None:
    limits = contract["limits"]
    rows = _walk(root, limits)
    total = 0
    matched: set[str] = set()
    for relative, path in rows:
        payload, mode = _read_regular(path, limits["max_file_bytes"])
        total += len(payload)
        if total > limits["max_total_bytes"]:
            raise WorkspaceRuntimeError("WORKSPACE_TOTAL_BYTES_EXCEEDED")
        rules = [rule for rule in contract["rules"] if _match(relative, rule["path_pattern"])]
        if len(rules) > 1:
            raise WorkspaceRuntimeError("WORKSPACE_RULE_OVERLAP", relative)
        if not rules:
            if not contract["allow_extra_files"]:
                raise WorkspaceRuntimeError("WORKSPACE_EXTRA_FILE", relative)
            continue
        rule = rules[0]
        matched.add(relative)
        if bool(mode & 0o111) != rule["executable"]:
            raise WorkspaceRuntimeError("WORKSPACE_EXECUTABLE_MODE_MISMATCH", relative)
        _validate(payload, rule["validation_profile"], path)
    for rule in contract["rules"]:
        count = sum(1 for relative, _ in rows if _match(relative, rule["path_pattern"]))
        if count < rule["min_count"] or count > rule["max_count"]:
            raise WorkspaceRuntimeError("WORKSPACE_RULE_CARDINALITY", rule["path_pattern"])
    for entrypoint in contract["entrypoints"]:
        path = root / entrypoint
        if entrypoint not in matched or not path.is_file() or not os.access(path, os.X_OK):
            raise WorkspaceRuntimeError("WORKSPACE_ENTRYPOINT_INVALID", entrypoint)


def seal_offline_python_runtime(
    root: Path,
    contract: dict,
    *,
    wheelhouse: Path,
    requirements_lock: Path,
) -> None:
    """Add the Core-owned runtime closure to a generated Python workspace.

    Builders own product files; they never own dependency bytes or the launcher.
    This function accepts only regular wheels from a previously admitted
    wheelhouse and fails on every path collision.  Both expected and actual
    workspaces therefore contain the same independently supplied runtime.
    """

    if not contract.get("require_offline_wheelhouse"):
        return
    output = Path(root)
    source = Path(wheelhouse)
    lock = Path(requirements_lock)
    application = str(contract.get("runtime_python_entrypoint") or "")
    if not application:
        raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_ENTRYPOINT_MISSING")
    application_path = output / application
    if application_path.is_symlink() or not application_path.is_file():
        raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_APPLICATION_MISSING")
    for relative in (
        "run.sh",
        "requirements.lock.txt",
        "THIRD_PARTY_NOTICES.md",
        "vendor",
    ):
        candidate = output / relative
        if candidate.exists() or candidate.is_symlink():
            raise WorkspaceRuntimeError(
                "WORKSPACE_RUNTIME_OWNED_PATH_COLLISION", relative
            )
    if source.is_symlink() or not source.is_dir():
        raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_WHEELHOUSE_UNSAFE")
    if lock.is_symlink() or not lock.is_file() or lock.stat().st_size > 1024 * 1024:
        raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_LOCK_UNSAFE")
    lock_payload = lock.read_bytes()
    try:
        lock_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_LOCK_INVALID") from exc

    wheels = sorted(source.glob("*.whl"), key=lambda item: item.name)
    if not wheels or len(wheels) > 256:
        raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_WHEEL_SET_INVALID")
    wheel_destination = output / "vendor" / "wheels"
    wheel_destination.mkdir(parents=True, mode=0o755)
    inventory: list[tuple[str, str]] = []
    for wheel in wheels:
        if (
            wheel.is_symlink()
            or not wheel.is_file()
            or wheel.name != Path(wheel.name).name
            or wheel.stat().st_nlink != 1
        ):
            raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_WHEEL_UNSAFE", wheel.name)
        payload = wheel.read_bytes()
        if not payload:
            raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_WHEEL_EMPTY", wheel.name)
        target = wheel_destination / wheel.name
        target.write_bytes(payload)
        target.chmod(0o644)
        inventory.append((wheel.name, hashlib.sha256(payload).hexdigest()))

    (output / "requirements.lock.txt").write_bytes(lock_payload)
    (output / "requirements.lock.txt").chmod(0o644)
    notices = [
        "# Third-party runtime inventory",
        "",
        "This offline runtime is sealed by RepoProof from the frozen wheel closure.",
        "Consult each wheel's bundled metadata for its authoritative license terms.",
        "",
        "| Wheel | SHA-256 |",
        "|---|---|",
        *(f"| `{name}` | `{digest}` |" for name, digest in inventory),
        "",
    ]
    (output / "THIRD_PARTY_NOTICES.md").write_text(
        "\n".join(notices), encoding="utf-8"
    )
    application_path.chmod(application_path.stat().st_mode & 0o666)
    launcher = output / "run.sh"
    launcher.write_text(
        _OFFLINE_PYTHON_LAUNCHER.replace(
            "__REPOPROOF_APPLICATION__", application
        ),
        encoding="utf-8",
    )
    launcher.chmod(0o755)


def _validate_input(path: Path) -> None:
    if path.is_symlink() or not (path.is_file() or path.is_dir()):
        raise WorkspaceRuntimeError("WORKSPACE_INPUT_UNSAFE")
    if path.is_file():
        _read_regular(path, 64 * 1024 * 1024)
        return
    limits = {
        "max_files": 256,
        "max_total_bytes": 256 * 1024 * 1024,
        "max_file_bytes": 64 * 1024 * 1024,
        "max_depth": 12,
        "max_path_bytes": 240,
    }
    total = 0
    for _, item in _walk(path, limits):
        payload, _ = _read_regular(item, limits["max_file_bytes"])
        total += len(payload)
        if total > limits["max_total_bytes"]:
            raise WorkspaceRuntimeError("WORKSPACE_INPUT_TOO_LARGE")


def materialize_workspace(
    builder,
    input_path: Path,
    output_dir: Path,
    contract: dict,
    *,
    runtime_source_root: Path | None = None,
) -> None:
    """Atomically build and validate a new directory, cleaning every failure."""

    input_path = Path(input_path)
    output_dir = Path(output_dir)
    _validate_input(input_path)
    if output_dir.exists() or output_dir.is_symlink():
        raise WorkspaceRuntimeError("WORKSPACE_OUTPUT_ALREADY_EXISTS")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.parent.is_symlink():
        raise WorkspaceRuntimeError("WORKSPACE_OUTPUT_PARENT_UNSAFE")
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.rp-", dir=output_dir.parent)
    )
    try:
        builder(input_path, temporary)
        if contract.get("require_offline_wheelhouse"):
            if runtime_source_root is None:
                raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_SOURCE_MISSING")
            runtime_root = Path(runtime_source_root)
            seal_offline_python_runtime(
                temporary,
                contract,
                wheelhouse=runtime_root / "vendor" / "wheels",
                requirements_lock=runtime_root / "requirements.lock.txt",
            )
        validate_workspace(temporary, contract)
        os.replace(temporary, output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
