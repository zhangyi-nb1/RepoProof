"""Generic M6.2 offline workspace-bundle execution and verification.

This module knows directory mechanics only.  Repository semantics remain in a
frozen task verifier; no source-repository name, field schema, or qualification
fixture belongs here.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import stat
import subprocess
import tempfile
import time
import tomllib
import zipfile
from collections.abc import Callable
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

import yaml
from pydantic import BaseModel, ConfigDict, Field

from repoproof.domain.models import (
    ArtifactManifestEntryV1,
    ArtifactManifestV1,
    WorkspaceArtifactContractV1,
    WorkspaceArtifactLimits,
    WorkspaceArtifactRule,
)
from repoproof.execution.offline_sandbox import (
    OfflineSandboxUnavailable,
    offline_sandbox_argv,
    sanitised_subprocess_env,
)

WORKSPACE_BUNDLE_PROFILE_ID = "workspace_bundle_v1"
DEFAULT_INPUT_MAX_FILES = 256
DEFAULT_INPUT_MAX_BYTES = 256 * 1024 * 1024
_READ_CHUNK = 1024 * 1024
_SMOKE_OUTPUT_CAP = 1024 * 1024


class WorkspaceBundleError(RuntimeError):
    """A stable fail-closed workspace mechanism error."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class WorkspaceValidationResultV1(BaseModel):
    """Structural/format result; domain semantics are a separate evidence line."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    ok: bool
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=128)
    manifest: ArtifactManifestV1 | None = None
    matched_paths: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class InputPathIdentityV1(BaseModel):
    """Immutable identity for one admitted local input path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    kind: Literal["file", "directory"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_count: int = Field(ge=1, le=DEFAULT_INPUT_MAX_FILES)
    total_bytes: int = Field(ge=0, le=DEFAULT_INPUT_MAX_BYTES)


class WorkspaceRuntimeEvidenceV1(BaseModel):
    """Bounded headless execution evidence for a runnable workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    command_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exit_code: int | None = None
    timed_out: bool = False
    orphan_processes_reaped: bool = False
    duration_ms: int = Field(ge=0)
    stdout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stderr_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=16)


class _OfflineHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.external_references: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del tag
        for name, value in attrs:
            if name.lower() not in {"href", "src", "action"} or value is None:
                continue
            candidate = value.strip().lower()
            if candidate.startswith(("http://", "https://", "//")):
                self.external_references.append(value)


def _frame(digest: hashlib._Hash, payload: bytes) -> None:
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _safe_read_regular(path: Path, *, max_bytes: int) -> tuple[bytes, int]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise WorkspaceBundleError("WORKSPACE_FILE_OPEN_FAILED", str(path)) from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise WorkspaceBundleError("WORKSPACE_SPECIAL_FILE", str(path))
        if before.st_nlink != 1:
            raise WorkspaceBundleError("WORKSPACE_HARDLINK_FORBIDDEN", str(path))
        if before.st_size > max_bytes:
            raise WorkspaceBundleError("WORKSPACE_FILE_TOO_LARGE", str(path))
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, _READ_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise WorkspaceBundleError("WORKSPACE_FILE_TOO_LARGE", str(path))
            chunks.append(chunk)
        after = os.fstat(fd)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_mode,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_mode,
        )
        if identity_before != identity_after or total != after.st_size:
            raise WorkspaceBundleError("WORKSPACE_FILE_CHANGED_DURING_READ", str(path))
        return b"".join(chunks), stat.S_IMODE(after.st_mode)
    finally:
        os.close(fd)


def _iter_workspace_files(
    root: Path,
    *,
    limits: WorkspaceArtifactLimits,
) -> list[tuple[str, Path]]:
    root = Path(root)
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise WorkspaceBundleError("WORKSPACE_ROOT_MISSING", str(root)) from exc
    if root.is_symlink() or not stat.S_ISDIR(root_stat.st_mode):
        raise WorkspaceBundleError("WORKSPACE_ROOT_UNSAFE", str(root))

    files: list[tuple[str, Path]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        encoded = relative.encode("utf-8")
        if len(encoded) > limits.max_path_bytes:
            raise WorkspaceBundleError("WORKSPACE_PATH_TOO_LONG", relative)
        if len(Path(relative).parts) > limits.max_depth:
            raise WorkspaceBundleError("WORKSPACE_PATH_TOO_DEEP", relative)
        try:
            info = path.lstat()
        except OSError as exc:
            raise WorkspaceBundleError("WORKSPACE_PATH_STAT_FAILED", relative) from exc
        if stat.S_ISLNK(info.st_mode):
            raise WorkspaceBundleError("WORKSPACE_SYMLINK_FORBIDDEN", relative)
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise WorkspaceBundleError("WORKSPACE_SPECIAL_FILE", relative)
        files.append((relative, path))
        if len(files) > limits.max_files:
            raise WorkspaceBundleError("WORKSPACE_FILE_COUNT_EXCEEDED")
    return files


def build_artifact_manifest(
    root: Path,
    limits: WorkspaceArtifactLimits | None = None,
) -> ArtifactManifestV1:
    """Snapshot a directory exactly once per file and compute its tree identity."""

    selected_limits = limits or WorkspaceArtifactLimits()
    entries: list[ArtifactManifestEntryV1] = []
    total = 0
    for relative, path in _iter_workspace_files(root, limits=selected_limits):
        payload, mode = _safe_read_regular(path, max_bytes=selected_limits.max_file_bytes)
        total += len(payload)
        if total > selected_limits.max_total_bytes:
            raise WorkspaceBundleError("WORKSPACE_TOTAL_BYTES_EXCEEDED")
        entries.append(
            ArtifactManifestEntryV1(
                path=relative,
                size=len(payload),
                mode=mode,
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )

    digest = hashlib.sha256(b"REPOPROOF-WORKSPACE-TREE-V1\0")
    for entry in entries:
        _frame(digest, entry.path.encode("utf-8"))
        digest.update(entry.mode.to_bytes(4, "big"))
        digest.update(entry.size.to_bytes(8, "big"))
        digest.update(bytes.fromhex(entry.sha256))
    return ArtifactManifestV1(
        file_count=len(entries),
        total_bytes=total,
        tree_sha256=digest.hexdigest(),
        entries=tuple(entries),
    )


def snapshot_admitted_path(
    source: Path,
    destination: Path,
    *,
    limits: WorkspaceArtifactLimits | None = None,
) -> InputPathIdentityV1:
    """Copy one file/directory into a private snapshot and bind its identity.

    The caller must supply a nonexistent destination.  Every source file is
    opened no-follow, hardlinks and special files are rejected, and a second
    source manifest must still match the bytes/modes copied into the snapshot.
    """

    selected_limits = limits or WorkspaceArtifactLimits(
        max_files=DEFAULT_INPUT_MAX_FILES,
        max_total_bytes=DEFAULT_INPUT_MAX_BYTES,
    )
    source = Path(source)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise WorkspaceBundleError("WORKSPACE_SNAPSHOT_DESTINATION_EXISTS")
    try:
        info = source.lstat()
    except OSError as exc:
        raise WorkspaceBundleError("WORKSPACE_INPUT_MISSING", str(source)) from exc
    if stat.S_ISLNK(info.st_mode):
        raise WorkspaceBundleError("WORKSPACE_SYMLINK_FORBIDDEN", str(source))
    if stat.S_ISREG(info.st_mode):
        payload, mode = _safe_read_regular(
            source,
            max_bytes=selected_limits.max_file_bytes,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            mode,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.fchmod(descriptor, mode)
        finally:
            os.close(descriptor)
        stable_payload, _ = _safe_read_regular(
            source,
            max_bytes=selected_limits.max_file_bytes,
        )
        if stable_payload != payload:
            destination.unlink(missing_ok=True)
            raise WorkspaceBundleError("WORKSPACE_INPUT_CHANGED_DURING_SNAPSHOT")
        return InputPathIdentityV1(
            kind="file",
            sha256=hashlib.sha256(payload).hexdigest(),
            file_count=1,
            total_bytes=len(payload),
        )
    if not stat.S_ISDIR(info.st_mode):
        raise WorkspaceBundleError("WORKSPACE_SPECIAL_FILE", str(source))

    destination.mkdir(parents=True, mode=0o700)
    try:
        for relative, path in _iter_workspace_files(source, limits=selected_limits):
            payload, mode = _safe_read_regular(
                path,
                max_bytes=selected_limits.max_file_bytes,
            )
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                target,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                mode,
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fchmod(descriptor, mode)
            finally:
                os.close(descriptor)
        copied = build_artifact_manifest(destination, selected_limits)
        stable = build_artifact_manifest(source, selected_limits)
        if copied != stable:
            raise WorkspaceBundleError("WORKSPACE_INPUT_CHANGED_DURING_SNAPSHOT")
        if copied.file_count < 1:
            raise WorkspaceBundleError("WORKSPACE_INPUT_EMPTY_DIRECTORY")
        return InputPathIdentityV1(
            kind="directory",
            sha256=copied.tree_sha256,
            file_count=copied.file_count,
            total_bytes=copied.total_bytes,
        )
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _segment_matches(pattern: str, value: str) -> bool:
    if "*" not in pattern:
        return pattern == value
    pieces = pattern.split("*")
    if not value.startswith(pieces[0]) or not value.endswith(pieces[-1]):
        return False
    cursor = len(pieces[0])
    for piece in pieces[1:-1]:
        found = value.find(piece, cursor)
        if found < 0:
            return False
        cursor = found + len(piece)
    return True


def workspace_path_matches(pattern: str, path: str) -> bool:
    """Match the restricted contract glob language deterministically."""

    pattern_parts = tuple(pattern.split("/"))
    path_parts = tuple(path.split("/"))
    memo: dict[tuple[int, int], bool] = {}

    def match(pattern_index: int, path_index: int) -> bool:
        key = (pattern_index, path_index)
        if key in memo:
            return memo[key]
        if pattern_index == len(pattern_parts):
            answer = path_index == len(path_parts)
        elif pattern_parts[pattern_index] == "**":
            answer = match(pattern_index + 1, path_index) or (
                path_index < len(path_parts) and match(pattern_index, path_index + 1)
            )
        else:
            answer = path_index < len(path_parts) and _segment_matches(
                pattern_parts[pattern_index], path_parts[path_index]
            ) and match(pattern_index + 1, path_index + 1)
        memo[key] = answer
        return answer

    return match(0, 0)


def _decode_utf8(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceBundleError("WORKSPACE_FORMAT_UTF8_INVALID") from exc


def _validate_tabular(text: str, *, delimiter: str) -> None:
    try:
        list(csv.reader(StringIO(text), delimiter=delimiter, strict=True))
    except (csv.Error, UnicodeError) as exc:
        raise WorkspaceBundleError("WORKSPACE_FORMAT_TABLE_INVALID") from exc


def _validate_html(text: str) -> None:
    parser = _OfflineHTMLParser()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - parser exceptions become one stable code
        raise WorkspaceBundleError("WORKSPACE_FORMAT_HTML_INVALID") from exc
    if parser.external_references:
        raise WorkspaceBundleError("WORKSPACE_HTML_EXTERNAL_RESOURCE")


def _validate_zip(path: Path, *, wheel: bool) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise WorkspaceBundleError("WORKSPACE_FORMAT_ZIP_CRC_INVALID")
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise WorkspaceBundleError("WORKSPACE_FORMAT_ZIP_INVALID") from exc
    if wheel and not any(name.endswith(".dist-info/WHEEL") for name in names):
        raise WorkspaceBundleError("WORKSPACE_FORMAT_WHEEL_INVALID")


def _validate_format(path: Path, rule: WorkspaceArtifactRule) -> None:
    profile = rule.validation_profile
    if profile in {"zip_v1", "wheel_v1"}:
        _validate_zip(path, wheel=profile == "wheel_v1")
        return
    if profile == "sqlite_v1":
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                result = connection.execute("PRAGMA quick_check").fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise WorkspaceBundleError("WORKSPACE_FORMAT_SQLITE_INVALID") from exc
        if not result or result[0] != "ok":
            raise WorkspaceBundleError("WORKSPACE_FORMAT_SQLITE_INVALID")
        return

    payload, _ = _safe_read_regular(path, max_bytes=64 * 1024 * 1024)
    if profile == "binary_v1":
        if not payload:
            raise WorkspaceBundleError("WORKSPACE_FORMAT_BINARY_EMPTY")
        return
    text = _decode_utf8(payload)
    try:
        if profile == "csv_v1":
            _validate_tabular(text, delimiter=",")
        elif profile == "tsv_v1":
            _validate_tabular(text, delimiter="\t")
        elif profile == "json_v1":
            json.loads(text)
        elif profile == "yaml_v1":
            yaml.safe_load(text)
        elif profile == "toml_v1":
            tomllib.loads(text)
        elif profile == "python_compile_v1":
            compile(text, path.name, "exec")
        elif profile == "html_v1":
            _validate_html(text)
        elif profile in {"xml_v1", "svg_xml_v1"}:
            root = ElementTree.fromstring(text)
            if profile == "svg_xml_v1" and not root.tag.lower().endswith("svg"):
                raise WorkspaceBundleError("WORKSPACE_FORMAT_SVG_INVALID")
        elif profile == "shell_v1":
            if not text.startswith("#!"):
                raise WorkspaceBundleError("WORKSPACE_FORMAT_SHELL_INVALID")
        elif profile != "text_utf8_v1":
            raise WorkspaceBundleError("WORKSPACE_VALIDATION_PROFILE_UNKNOWN", profile)
    except WorkspaceBundleError:
        raise
    except Exception as exc:  # noqa: BLE001 - public result exposes no parser detail
        raise WorkspaceBundleError("WORKSPACE_FORMAT_INVALID", profile) from exc


def validate_workspace(
    root: Path,
    contract: WorkspaceArtifactContractV1,
) -> WorkspaceValidationResultV1:
    """Validate structure and generic formats without interpreting domain data."""

    try:
        manifest = build_artifact_manifest(root, contract.limits)
    except WorkspaceBundleError as exc:
        return WorkspaceValidationResultV1(ok=False, reason_codes=(exc.code,))

    paths = [entry.path for entry in manifest.entries]
    matched_paths: dict[str, tuple[str, ...]] = {}
    reasons: list[str] = []
    matched_any: set[str] = set()
    rule_by_path: dict[str, WorkspaceArtifactRule] = {}
    for rule in contract.rules:
        matches = tuple(path for path in paths if workspace_path_matches(rule.path_pattern, path))
        matched_paths[rule.path_pattern] = matches
        matched_any.update(matches)
        if len(matches) < rule.min_count:
            reasons.append("WORKSPACE_REQUIRED_ENTRY_MISSING")
        if len(matches) > rule.max_count:
            reasons.append("WORKSPACE_ENTRY_CARDINALITY_EXCEEDED")
        for path in matches:
            if path in rule_by_path:
                reasons.append("WORKSPACE_RULE_OVERLAP")
            else:
                rule_by_path[path] = rule
    if not contract.allow_extra_files and set(paths) - matched_any:
        reasons.append("WORKSPACE_EXTRA_FILE_FORBIDDEN")
    for entrypoint in contract.entrypoints:
        if entrypoint not in paths:
            reasons.append("WORKSPACE_ENTRYPOINT_MISSING")
        elif not (next(item.mode for item in manifest.entries if item.path == entrypoint) & 0o111):
            reasons.append("WORKSPACE_ENTRYPOINT_NOT_EXECUTABLE")

    for entry in manifest.entries:
        entry_rule = rule_by_path.get(entry.path)
        if entry_rule is None:
            continue
        if entry_rule.executable != bool(entry.mode & 0o111):
            reasons.append("WORKSPACE_EXECUTABLE_MODE_MISMATCH")
            continue
        try:
            _validate_format(Path(root) / entry.path, entry_rule)
        except WorkspaceBundleError as exc:
            reasons.append(exc.code)
    unique_reasons = tuple(sorted(set(reasons)))
    return WorkspaceValidationResultV1(
        ok=not unique_reasons,
        reason_codes=unique_reasons,
        manifest=manifest,
        matched_paths=matched_paths,
    )


def _smoke_capture_digest(descriptor: int) -> tuple[str, bool]:
    info = os.fstat(descriptor)
    if info.st_size > _SMOKE_OUTPUT_CAP:
        marker = f"REPOPROOF-SMOKE-OUTPUT-OVERSIZE:{info.st_size}".encode()
        return hashlib.sha256(marker).hexdigest(), True
    os.lseek(descriptor, 0, os.SEEK_SET)
    payload = bytearray()
    while len(payload) <= _SMOKE_OUTPUT_CAP:
        chunk = os.read(descriptor, min(_READ_CHUNK, _SMOKE_OUTPUT_CAP + 1 - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
    oversized = len(payload) > _SMOKE_OUTPUT_CAP
    if oversized:
        marker = f"REPOPROOF-SMOKE-OUTPUT-OVERSIZE:{len(payload)}".encode()
        return hashlib.sha256(marker).hexdigest(), True
    return hashlib.sha256(payload).hexdigest(), False


def run_workspace_smoke(
    root: Path,
    contract: WorkspaceArtifactContractV1,
    *,
    isolation_required: bool = True,
) -> WorkspaceRuntimeEvidenceV1:
    """Run the frozen entrypoint against an immutable copied workspace.

    The original artifact is never executed in place.  The child receives a
    sanitised environment, no network under the reviewed OS sandbox, a bounded
    timeout, and its complete process group is reaped before evidence is read.
    Only hashes and stable reason codes leave this boundary.
    """

    if not contract.runnable or not contract.smoke_command:
        raise WorkspaceBundleError("WORKSPACE_SMOKE_NOT_CONTRACTED")
    structure = validate_workspace(root, contract)
    if not structure.ok or structure.manifest is None:
        raise WorkspaceBundleError(
            "WORKSPACE_SMOKE_STRUCTURE_INVALID",
            ",".join(structure.reason_codes),
        )
    manifest = structure.manifest
    command_payload = json.dumps(
        list(contract.smoke_command),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    command_sha256 = hashlib.sha256(command_payload).hexdigest()
    empty_sha256 = hashlib.sha256(b"").hexdigest()

    with tempfile.TemporaryDirectory(prefix="rp-workspace-smoke-") as temp:
        stage = Path(temp)
        workspace = stage / "workspace"
        snapshot_admitted_path(root, workspace, limits=contract.limits)
        entrypoint = workspace / contract.smoke_command[0].removeprefix("./")
        argv = [str(entrypoint), *contract.smoke_command[1:]]
        if isolation_required:
            try:
                argv = offline_sandbox_argv(argv, stage)
            except OfflineSandboxUnavailable:
                return WorkspaceRuntimeEvidenceV1(
                    command_sha256=command_sha256,
                    artifact_tree_sha256=manifest.tree_sha256,
                    duration_ms=0,
                    stdout_sha256=empty_sha256,
                    stderr_sha256=empty_sha256,
                    passed=False,
                    reason_codes=("WORKSPACE_SMOKE_ISOLATION_UNAVAILABLE",),
                )

        stdout_path = stage / "stdout.bin"
        stderr_path = stage / "stderr.bin"
        stdout_fd = os.open(stdout_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        stderr_fd = os.open(stderr_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        started = time.monotonic()
        exit_code: int | None = None
        timed_out = False
        orphaned = False
        reasons: list[str] = []
        try:
            try:
                process = subprocess.Popen(  # noqa: S603 - frozen argv, no shell
                    argv,
                    cwd=workspace,
                    env=sanitised_subprocess_env(stage, []),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_fd,
                    stderr=stderr_fd,
                    start_new_session=True,
                )
            except (OSError, ValueError):
                process = None
                reasons.append("WORKSPACE_SMOKE_START_FAILED")
            if process is not None:
                try:
                    exit_code = process.wait(timeout=contract.smoke_timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    reasons.append("WORKSPACE_SMOKE_TIMEOUT")
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        process.kill()
                    process.wait()
                    exit_code = 124
                if not timed_out:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        orphaned = True
                    else:
                        orphaned = True
                    if orphaned:
                        reasons.append("WORKSPACE_SMOKE_ORPHAN_PROCESS")
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass
                if exit_code != 0 and not timed_out:
                    reasons.append("WORKSPACE_SMOKE_NONZERO_EXIT")

            stdout_sha, stdout_oversized = _smoke_capture_digest(stdout_fd)
            stderr_sha, stderr_oversized = _smoke_capture_digest(stderr_fd)
            if stdout_oversized or stderr_oversized:
                reasons.append("WORKSPACE_SMOKE_OUTPUT_LIMIT")
        finally:
            os.close(stdout_fd)
            os.close(stderr_fd)

        unique_reasons = tuple(dict.fromkeys(reasons))
        return WorkspaceRuntimeEvidenceV1(
            command_sha256=command_sha256,
            artifact_tree_sha256=manifest.tree_sha256,
            exit_code=exit_code,
            timed_out=timed_out,
            orphan_processes_reaped=orphaned,
            duration_ms=int((time.monotonic() - started) * 1000),
            stdout_sha256=stdout_sha,
            stderr_sha256=stderr_sha,
            passed=not unique_reasons and exit_code == 0,
            reason_codes=unique_reasons,
        )


def materialize_workspace_atomic(
    output_dir: Path,
    builder: Callable[[Path], None],
    contract: WorkspaceArtifactContractV1,
) -> WorkspaceValidationResultV1:
    """Build in a sibling temporary directory, validate, then atomically publish."""

    output_dir = Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise WorkspaceBundleError("WORKSPACE_OUTPUT_ALREADY_EXISTS", str(output_dir))
    parent = output_dir.parent
    if parent.is_symlink() or not parent.is_dir():
        raise WorkspaceBundleError("WORKSPACE_OUTPUT_PARENT_UNSAFE", str(parent))
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.rp-", dir=parent))
    published = False
    try:
        builder(temporary)
        result = validate_workspace(temporary, contract)
        if not result.ok:
            raise WorkspaceBundleError(
                "WORKSPACE_CONTRACT_FAILED",
                ",".join(result.reason_codes),
            )
        try:
            os.rename(temporary, output_dir)
        except FileExistsError as exc:
            raise WorkspaceBundleError("WORKSPACE_OUTPUT_ALREADY_EXISTS") from exc
        published = True
        return result
    finally:
        if not published and temporary.exists():
            shutil.rmtree(temporary)


def identify_input_path(path: Path) -> InputPathIdentityV1:
    """Hash one input file or directory under the fixed workspace profile caps."""

    path = Path(path)
    if path.is_symlink():
        raise WorkspaceBundleError("WORKSPACE_INPUT_SYMLINK_FORBIDDEN", str(path))
    if path.is_file():
        payload, _ = _safe_read_regular(path, max_bytes=DEFAULT_INPUT_MAX_BYTES)
        return InputPathIdentityV1(
            kind="file",
            sha256=hashlib.sha256(payload).hexdigest(),
            file_count=1,
            total_bytes=len(payload),
        )
    if not path.is_dir():
        raise WorkspaceBundleError("WORKSPACE_INPUT_MISSING", str(path))
    limits = WorkspaceArtifactLimits(
        max_files=DEFAULT_INPUT_MAX_FILES,
        max_total_bytes=DEFAULT_INPUT_MAX_BYTES,
        max_file_bytes=64 * 1024 * 1024,
    )
    manifest = build_artifact_manifest(path, limits)
    if manifest.file_count == 0:
        raise WorkspaceBundleError("WORKSPACE_INPUT_EMPTY")
    return InputPathIdentityV1(
        kind="directory",
        sha256=manifest.tree_sha256,
        file_count=manifest.file_count,
        total_bytes=manifest.total_bytes,
    )


def write_deterministic_zip(root: Path, destination: Path) -> Path:
    """Create an on-demand transport ZIP; evidence continues to bind the tree."""

    root = Path(root)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise WorkspaceBundleError("WORKSPACE_ZIP_ALREADY_EXISTS", str(destination))
    manifest = build_artifact_manifest(root)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    os.close(fd)
    try:
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for entry in manifest.entries:
                payload, _ = _safe_read_regular(root / entry.path, max_bytes=entry.size)
                info = zipfile.ZipInfo(entry.path, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (entry.mode & 0o777) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, payload)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination
