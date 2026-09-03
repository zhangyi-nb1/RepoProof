"""Standalone stdlib-first runtime copied into generated workspace tools.

Keep this module free of ``repoproof`` imports: exported packages vendor this
source verbatim so clean replay never depends on an external RepoProof checkout.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import tomllib
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Literal
from xml.etree import ElementTree


class WorkspaceRuntimeError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


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


# These paths are supplied by the trusted Core after a task-owned producer has
# finished creating its application files.  Keep the list public and shared so
# drafting policy, reference repair, and runtime sealing cannot drift apart.
OFFLINE_PYTHON_RUNTIME_OWNED_PATHS = (
    "run.sh",
    "requirements.lock.txt",
    "THIRD_PARTY_NOTICES.md",
    "vendor",
)

# Runtime format validators are Core-owned code, so their dependency closure
# is also Core-owned.  A task author should not need to know that validating a
# YAML artifact requires this distribution, and a Coding Agent must never be
# asked to repair a missing Harness dependency.
_VALIDATION_PROFILE_RUNTIME_PINS = {
    "yaml_v1": "pyyaml==6.0.3",
}
_PIN_DISTRIBUTION_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==")


def close_workspace_runtime_lock(lock_text: str, contract: dict) -> str:
    """Add exact Core-owned validator pins to one workspace runtime lock."""

    lines = [
        line.strip()
        for line in str(lock_text).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    present = {
        match.group(1).lower().replace("_", "-")
        for line in lines
        if (match := _PIN_DISTRIBUTION_RE.match(line)) is not None
    }
    required_profiles = {
        str(rule.get("validation_profile") or "")
        for rule in (contract.get("rules") or [])
        if isinstance(rule, dict)
    }
    for profile in sorted(required_profiles):
        pin = _VALIDATION_PROFILE_RUNTIME_PINS.get(profile)
        if pin is None:
            continue
        match = _PIN_DISTRIBUTION_RE.match(pin)
        assert match is not None
        distribution = match.group(1).lower().replace("_", "-")
        if distribution not in present:
            lines.append(pin)
            present.add(distribution)
    return "\n".join(lines) + ("\n" if lines else "")


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



class _ProfileFormatError(Exception):
    """Internal: one public structure code from a shared profile validator."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate_ooxml(path: Path, *, part_prefix: str, code: str) -> None:
    """Office Open XML package: valid zip, content types, and parseable parts."""

    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise _ProfileFormatError(code)
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names:
                raise _ProfileFormatError(code)
            parts = sorted(
                name for name in names
                if name.startswith(part_prefix) and name.endswith(".xml") and "/_rels/" not in name
            )
            if not parts:
                raise _ProfileFormatError(code)
            for name in parts[:64]:
                ElementTree.fromstring(archive.read(name))
    except _ProfileFormatError:
        raise
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
        raise _ProfileFormatError(code) from exc


def _validate_png(payload: bytes) -> None:
    signature = b"\x89PNG\r\n\x1a\n"
    if len(payload) < 33 or not payload.startswith(signature):
        raise _ProfileFormatError("WORKSPACE_FORMAT_PNG_INVALID")
    if payload[12:16] != b"IHDR":
        raise _ProfileFormatError("WORKSPACE_FORMAT_PNG_INVALID")
    width = int.from_bytes(payload[16:20], "big")
    height = int.from_bytes(payload[20:24], "big")
    if width <= 0 or height <= 0 or not payload.rstrip(b"\x00").endswith(b"IEND\xaeB`\x82"):
        raise _ProfileFormatError("WORKSPACE_FORMAT_PNG_INVALID")


def _validate_ics(text: str) -> None:
    lines = [line.rstrip("\r") for line in text.split("\n")]
    unfolded: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        elif line.strip():
            unfolded.append(line)
    if not unfolded or unfolded[0] != "BEGIN:VCALENDAR" or unfolded[-1] != "END:VCALENDAR":
        raise _ProfileFormatError("WORKSPACE_FORMAT_ICS_INVALID")
    stack: list[str] = []
    saw_version = False
    for line in unfolded:
        if line.startswith("BEGIN:"):
            stack.append(line[6:])
        elif line.startswith("END:"):
            if not stack or stack.pop() != line[4:]:
                raise _ProfileFormatError("WORKSPACE_FORMAT_ICS_INVALID")
        elif line.startswith("VERSION:"):
            saw_version = True
        elif ":" not in line and ";" not in line:
            raise _ProfileFormatError("WORKSPACE_FORMAT_ICS_INVALID")
    if stack or not saw_version:
        raise _ProfileFormatError("WORKSPACE_FORMAT_ICS_INVALID")


def _validate_ipynb(text: str) -> None:
    document = json.loads(text)
    if not isinstance(document, dict) or document.get("nbformat") != 4:
        raise _ProfileFormatError("WORKSPACE_FORMAT_IPYNB_INVALID")
    cells = document.get("cells")
    if not isinstance(cells, list) or not isinstance(document.get("metadata"), dict):
        raise _ProfileFormatError("WORKSPACE_FORMAT_IPYNB_INVALID")
    for cell in cells:
        if (
            not isinstance(cell, dict)
            or cell.get("cell_type") not in {"code", "markdown", "raw"}
            or not isinstance(cell.get("source"), (str, list))
            or not isinstance(cell.get("metadata"), dict)
        ):
            raise _ProfileFormatError("WORKSPACE_FORMAT_IPYNB_INVALID")
        if cell["cell_type"] == "code" and not isinstance(cell.get("outputs"), list):
            raise _ProfileFormatError("WORKSPACE_FORMAT_IPYNB_INVALID")


def _validate_mo(payload: bytes) -> None:
    if len(payload) < 28:
        raise _ProfileFormatError("WORKSPACE_FORMAT_MO_INVALID")
    magic = payload[:4]
    order: Literal["little", "big"]
    if magic == b"\xde\x12\x04\x95":
        order = "little"
    elif magic == b"\x95\x04\x12\xde":
        order = "big"
    else:
        raise _ProfileFormatError("WORKSPACE_FORMAT_MO_INVALID")
    count = int.from_bytes(payload[8:12], order)
    original_offset = int.from_bytes(payload[12:16], order)
    translation_offset = int.from_bytes(payload[16:20], order)
    needed = max(original_offset, translation_offset) + count * 8
    if count < 0 or needed > len(payload):
        raise _ProfileFormatError("WORKSPACE_FORMAT_MO_INVALID")



def golden_file_identity(payload: bytes) -> str:
    """The acceptance identity of one delivered file (stdlib only; single ruler).

    Bytes that parse as a zip archive are identified by their sorted
    (member name, member bytes) pairs, so member ordering, compression level,
    entry timestamps and extra fields — incidentals of whichever zip writer
    produced the container — never decide a golden comparison
    (incident-artifact-identity-zip-metadata-*).  Anything else is its raw
    sha256.  Evidence manifests keep the raw tree hash for integrity; this
    identity is what *equality* means for acceptance.
    """

    if payload[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                members = sorted(
                    (info.filename, archive.read(info.filename))
                    for info in archive.infolist()
                    if not info.is_dir()
                )
        except (zipfile.BadZipFile, OSError, RuntimeError, ValueError):
            return hashlib.sha256(payload).hexdigest()
        digest = hashlib.sha256(b"REPOPROOF-ZIP-MEMBERS-V1\0")
        for name, body in members:
            encoded = name.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            digest.update(len(body).to_bytes(8, "big"))
            digest.update(hashlib.sha256(body).digest())
        return digest.hexdigest()
    return hashlib.sha256(payload).hexdigest()


def golden_tree_sha256(root: Path) -> str:
    """Tree identity for acceptance: path + executable bit + golden_file_identity per file."""

    digest = hashlib.sha256(b"REPOPROOF-WORKSPACE-GOLDEN-V2\0")
    root = Path(root)
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise WorkspaceRuntimeError("WORKSPACE_GOLDEN_NON_REGULAR_FILE", path.relative_to(root).as_posix())
        payload = path.read_bytes()
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(int(bool(stat.S_IMODE(info.st_mode) & 0o111)).to_bytes(1, "big"))
        digest.update(bytes.fromhex(golden_file_identity(payload)))
    return digest.hexdigest()


KNOWN_DIRECTORY_PROFILES = ("static_site_v1",)


def directory_profile_errors(profile: str, root: Path) -> list[tuple[str, str]]:
    """The single stdlib ruler for whole-tree profiles shared by Core and exported tools.

    ``static_site_v1``: at least one ``index.html`` exists, and every internal
    ``href``/``src``/``action`` in every HTML file resolves to a file inside the
    tree (a directory link may resolve via its ``index.html``).  External
    references stay the business of the per-file ``html_v1`` check; fragments,
    ``mailto:``/``tel:``/``data:``/``javascript:`` and query strings are not
    file references.  Rows are ``(code, detail)`` naming the file and the link.
    """

    if profile not in KNOWN_DIRECTORY_PROFILES:
        return [("WORKSPACE_DIRECTORY_PROFILE_UNKNOWN", profile)]
    root = Path(root)
    html_files = sorted(
        path for path in root.rglob("*.html") if path.is_file() and not path.is_symlink()
    )
    rows: list[tuple[str, str]] = []
    if not any(path.name == "index.html" for path in html_files):
        rows.append(("WORKSPACE_SITE_INDEX_MISSING", "no index.html anywhere in the tree"))

    class _LinkCollector(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.internal: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            del tag
            for name, value in attrs:
                if name.lower() not in {"href", "src", "action"} or value is None:
                    continue
                candidate = value.strip()
                lowered = candidate.lower()
                if not candidate or lowered.startswith(
                    ("http://", "https://", "//", "mailto:", "tel:", "data:", "javascript:", "#")
                ):
                    continue
                self.internal.append(candidate)

    existing = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    directories = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()}
    directories.add("")
    for html in html_files:
        try:
            text = html.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # encoding problems belong to the per-file profile
        collector = _LinkCollector()
        try:
            collector.feed(text)
            collector.close()
        except Exception:  # noqa: BLE001 - parse problems belong to the per-file profile
            continue
        base = html.relative_to(root).parent
        for link in collector.internal:
            reference = link.split("#", 1)[0].split("?", 1)[0]
            if not reference:
                continue
            parts: list[str] = []
            start = [] if reference.startswith("/") else list(base.parts)
            for part in start + [p for p in reference.split("/") if p]:
                if part == "..":
                    if not parts:
                        parts = ["\x00outside"]
                        break
                    parts.pop()
                elif part not in ("", "."):
                    parts.append(part)
            target = "/".join(parts)
            resolved = (
                target in existing
                or (target in directories and f"{target}/index.html".lstrip("/") in existing)
                or (target == "" and "index.html" in existing)
            )
            if not resolved:
                rows.append(
                    (
                        "WORKSPACE_SITE_LINK_BROKEN",
                        f"'{html.relative_to(root).as_posix()}' links '{link}' which resolves to no file in the tree",
                    )
                )
            if len(rows) >= 40:
                return rows
    return rows


STRUCTURE_PROFILE_CODES = {
    "xlsx_v1": "WORKSPACE_FORMAT_XLSX_INVALID",
    "pptx_v1": "WORKSPACE_FORMAT_PPTX_INVALID",
    "png_v1": "WORKSPACE_FORMAT_PNG_INVALID",
    "ics_v1": "WORKSPACE_FORMAT_ICS_INVALID",
    "ipynb_v1": "WORKSPACE_FORMAT_IPYNB_INVALID",
    "mo_v1": "WORKSPACE_FORMAT_MO_INVALID",
}


def profile_format_error(profile: str, path: Path, payload: bytes) -> str | None:
    """The single stdlib ruler for the structure profiles shared by Core and exported tools.

    Returns a public code or None.  Both ``workspace_bundle._validate_format``
    (Core) and ``_validate`` here (exported runtime) delegate to it, so the two
    validators cannot drift: a profile Core accepts, the shipped tool accepts.
    """

    if profile not in STRUCTURE_PROFILE_CODES:
        return None
    code = STRUCTURE_PROFILE_CODES[profile]
    try:
        if profile == "xlsx_v1":
            _validate_ooxml(path, part_prefix="xl/worksheets/sheet", code=code)
        elif profile == "pptx_v1":
            _validate_ooxml(path, part_prefix="ppt/slides/slide", code=code)
        elif profile == "png_v1":
            _validate_png(payload)
        elif profile == "mo_v1":
            _validate_mo(payload)
        else:
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                return code
            if profile == "ics_v1":
                _validate_ics(text)
            else:
                _validate_ipynb(text)
    except _ProfileFormatError as exc:
        return exc.code
    except Exception:  # noqa: BLE001 - parser detail is never a public fact
        return code
    return None


_TEXT_PROFILES = {
    "json_v1", "csv_v1", "tsv_v1", "toml_v1", "yaml_v1", "python_compile_v1",
    "shell_v1", "html_v1", "xml_v1", "svg_xml_v1", "text_utf8_v1",
}


def _validate(payload: bytes, profile: str, path: Path) -> None:
    structure_code = profile_format_error(profile, path, payload)
    if structure_code is not None:
        raise WorkspaceRuntimeError(structure_code, str(path))
    if profile in STRUCTURE_PROFILE_CODES:
        return
    if profile not in _TEXT_PROFILES and profile not in {"binary_v1", "wheel_v1", "zip_v1", "sqlite_v1"}:
        raise WorkspaceRuntimeError("WORKSPACE_VALIDATION_PROFILE_UNKNOWN", profile)
    if profile in {"binary_v1", "wheel_v1", "zip_v1"}:
        if not payload:
            raise WorkspaceRuntimeError("WORKSPACE_EMPTY_BINARY", str(path))
    if profile in {"zip_v1", "wheel_v1"}:
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.testzip() is not None:
                    raise WorkspaceRuntimeError("WORKSPACE_ZIP_INVALID", str(path))
        except (OSError, zipfile.BadZipFile) as exc:
            raise WorkspaceRuntimeError("WORKSPACE_ZIP_INVALID", str(path)) from exc
        return
    if profile == "sqlite_v1":
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise WorkspaceRuntimeError("WORKSPACE_SQLITE_INVALID", str(path))
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise WorkspaceRuntimeError("WORKSPACE_SQLITE_INVALID", str(path)) from exc
        return
    if profile == "binary_v1":
        return
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceRuntimeError("WORKSPACE_FORMAT_UTF8_INVALID", str(path)) from exc
    try:
        _validate_text_profile(text, profile, path)
    except WorkspaceRuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - parser detail is never a public fact
        raise WorkspaceRuntimeError("WORKSPACE_FORMAT_INVALID", str(path)) from exc


def _validate_text_profile(text: str, profile: str, path: Path) -> None:
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
    for profile in contract.get("directory_profiles") or ():
        for code, detail in directory_profile_errors(str(profile), root):
            raise WorkspaceRuntimeError(code, detail)


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
        raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_APPLICATION_MISSING", application)
    for relative in OFFLINE_PYTHON_RUNTIME_OWNED_PATHS:
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
        lock_text = lock_payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceRuntimeError("WORKSPACE_RUNTIME_LOCK_INVALID") from exc
    # One canonical lock for every sealed workspace (candidate golden, preflight
    # reference, release audit): comment/blank lines dropped and Core validator
    # pins closed — byte-identical to what the assembler freezes into
    # controls/<task>/reference/requirements.lock.txt.  Callers' raw bytes must
    # not leak into the tree identity.
    lock_payload = close_workspace_runtime_lock(lock_text, contract).encode("utf-8")

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
