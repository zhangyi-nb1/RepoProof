"""MCP 暴露(M3-c · RFC-010 [D1]:manifest 的机械转换)。

`tool.json` → `mcp_server.py`(stdio JSON-RPC 2.0,newline-delimited;
零第三方依赖):一个 MCP tool,inputSchema/outputSchema 由
manifest.interface 机械推导,tools/call = subprocess 跑 `bin/<name>`。
生成物在每次 list/call 前 fail-closed 复核 append-only release ledger；
文件可保留，但撤回后不能继续暴露工具。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from repoproof.adoption.assembly.output_contract import mcp_output_projection
from repoproof.runner.tool_paths import (
    TOOL_NAME_PATTERN,
    ToolPathError,
    canonical_tool_path,
    ensure_safe_package_tree,
    tool_install_lock,
    validate_tool_task_id,
)
from repoproof.runner.tool_release import (
    ACTIVE,
    is_historical_tool_ready,
    operational_status,
)

_SERVER_TMPL = '''#!/usr/bin/env python3
"""MCP stdio server for `{name}`(由 repoproof tool mcp 机械生成)。

挂进 Claude Code:
    claude mcp add {name} -- python3 {server_path}
协议:JSON-RPC 2.0 over stdio(newline-delimited);单 tool = {name}。
"""
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOL = ROOT / "bin" / {name!r}
OUTPUT_CONTRACT = {output_contract!r}
OUTPUT_MODE = {output_mode!r}
EXPECTED_TASK_ID = {task_id!r}
EXPECTED_PACKAGE_FILES = {expected_package_files!r}
RELEASE_LEDGER = ROOT.parent / ".repoproof-release-decisions.jsonl"
INSTALL_LOCK = ROOT.parent / ".repoproof-install.lock"
RELEASE_LOCK = ROOT.parent / ".repoproof-release.lock"
TOOL_NAME_PATTERN = {tool_name_pattern!r}

TOOL_DEF = {{
    "name": {mcp_name!r},
    "description": {description!r},
    "inputSchema": {{
        "type": "object",
        "properties": {{
            "input_path": {{"type": "string",
                            "description": "输入文件路径({in_format})"}},
            "out": {{"type": "string",
                     "description": "可选:输出文件路径(缺省返回 stdout)"}},
        }},
        "required": ["input_path"],
    }},
    {output_schema_entry}
}}


def _reject_json_constant(constant):
    raise ValueError(f"non-standard JSON constant: {{constant}}")


def _strict_json_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {{value}}")
    return parsed


def _strict_json_loads(text):
    return json.loads(
        text,
        parse_constant=_reject_json_constant,
        parse_float=_strict_json_float,
    )


def _reply(rid, result=None, error=None):
    msg = {{"jsonrpc": "2.0", "id": rid}}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False, allow_nan=False) + "\\n")
    sys.stdout.flush()


def _valid_utc(value):
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0)


def _validate_release_row(row):
    required = {{
        "schema_version", "tool", "task_id", "run_id", "decision",
        "reason_code", "reason", "evidence_sha256", "decided_at", "actor",
    }}
    if not isinstance(row, dict) or required - row.keys():
        raise RuntimeError("release ledger schema invalid")
    if type(row["schema_version"]) is not int or row["schema_version"] != 1:
        raise RuntimeError("release ledger schema invalid")
    if not isinstance(row["tool"], str) or not re.fullmatch(
            TOOL_NAME_PATTERN, row["tool"]):
        raise RuntimeError("release ledger schema invalid")
    if not isinstance(row["task_id"], str) or not re.fullmatch(
            rf"tool-{{re.escape(row['tool'])}}-v[1-9][0-9]*", row["task_id"]):
        raise RuntimeError("release ledger schema invalid")
    if row["run_id"] is not None and not isinstance(row["run_id"], str):
        raise RuntimeError("release ledger schema invalid")
    if row["decision"] not in {{"ACTIVE", "REVIEW_REQUIRED", "REVOKED"}}:
        raise RuntimeError("release ledger schema invalid")
    if not isinstance(row["reason_code"], str) or not row["reason_code"].strip():
        raise RuntimeError("release ledger schema invalid")
    if not isinstance(row["reason"], str) or not row["reason"].strip():
        raise RuntimeError("release ledger schema invalid")
    if not isinstance(row["evidence_sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{{64}}", row["evidence_sha256"]):
        raise RuntimeError("release ledger schema invalid")
    if not _valid_utc(row["decided_at"]):
        raise RuntimeError("release ledger schema invalid")
    if row["actor"] not in {{"human", "operator", "migration"}}:
        raise RuntimeError("release ledger schema invalid")


def _read_release_ledger():
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(RELEASE_LEDGER, flags)
    except FileNotFoundError as exc:
        raise RuntimeError("operational_status=REVIEW_REQUIRED") from exc
    except OSError as exc:
        raise RuntimeError("release ledger schema invalid") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise RuntimeError("release ledger schema invalid")
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1
            raw = fh.read()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("release ledger schema invalid") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    if raw and not raw.endswith("\\n"):
        raise RuntimeError("release ledger schema invalid")
    return raw


def _open_runtime_lock(path):
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError("managed lock is unsafe") from exc
    metadata = os.fstat(fd)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(fd)
        raise RuntimeError("managed lock is unsafe")
    return fd


class _RuntimeLocks:
    def __enter__(self):
        self.install_fd = _open_runtime_lock(INSTALL_LOCK)
        try:
            fcntl.flock(self.install_fd, fcntl.LOCK_EX)
            self.release_fd = _open_runtime_lock(RELEASE_LOCK)
            try:
                fcntl.flock(self.release_fd, fcntl.LOCK_EX)
            except BaseException:
                os.close(self.release_fd)
                raise
        except BaseException:
            fcntl.flock(self.install_fd, fcntl.LOCK_UN)
            os.close(self.install_fd)
            raise
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        fcntl.flock(self.release_fd, fcntl.LOCK_UN)
        os.close(self.release_fd)
        fcntl.flock(self.install_fd, fcntl.LOCK_UN)
        os.close(self.install_fd)


def _require_safe_tool():
    bin_dir = ROOT / "bin"
    if (
        bin_dir.is_symlink()
        or TOOL.is_symlink()
        or not TOOL.is_file()
        or bin_dir.resolve() != bin_dir
        or TOOL.resolve() != TOOL
    ):
        raise RuntimeError("managed tool executable is unsafe")
    actual_source_files = {{
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if path.is_file() and not path.is_symlink()
    }} if (ROOT / "src").is_dir() and not (ROOT / "src").is_symlink() else set()
    expected_source_files = {{
        relative for relative in EXPECTED_PACKAGE_FILES
        if relative.startswith("src/") and relative.endswith(".py")
    }}
    if actual_source_files != expected_source_files:
        raise RuntimeError("managed package identity changed")
    for relative, expected_sha256 in EXPECTED_PACKAGE_FILES.items():
        path = ROOT / relative
        try:
            if (
                path.is_symlink()
                or not path.is_file()
                or ROOT not in path.resolve().parents
            ):
                raise RuntimeError("managed package identity changed")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise RuntimeError("managed package identity changed")
                digest = hashlib.sha256()
                while chunk := os.read(fd, 1024 * 1024):
                    digest.update(chunk)
            finally:
                os.close(fd)
        except OSError as exc:
            raise RuntimeError("managed package identity changed") from exc
        if digest.hexdigest() != expected_sha256:
            raise RuntimeError("managed package identity changed")


def _require_active():
    raw = _read_release_ledger()
    latest = None
    for line in raw.splitlines():
        if not line.strip():
            raise RuntimeError("release ledger schema invalid")
        try:
            row = _strict_json_loads(line)
        except ValueError as exc:
            raise RuntimeError("release ledger schema invalid") from exc
        _validate_release_row(row)
        if row["tool"] == {name!r}:
            latest = row
    if latest is None or latest["task_id"] != EXPECTED_TASK_ID:
        raise RuntimeError("operational_status=REVIEW_REQUIRED")
    if latest["decision"] != "ACTIVE":
        raise RuntimeError(f"operational_status={{latest['decision']}}")
    _require_safe_tool()


def _type_ok(value, expected):
    if expected == "any":
        return True
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return False


def _check_object(value):
    if not isinstance(value, dict):
        raise ValueError("wrong_root expected=object")
    for field, expected in OUTPUT_CONTRACT.get("required", {{}}).items():
        if field not in value:
            raise ValueError(f"missing_required field={{field}}")
        if not _type_ok(value[field], expected):
            raise ValueError(f"wrong_type field={{field}} expected={{expected}}")


def _structured_content(text):
    if OUTPUT_MODE == "text":
        return {{"text": text}}
    if OUTPUT_MODE == "json_lines":
        values = [
            _strict_json_loads(line) for line in text.splitlines() if line.strip()
        ]
        if not values:
            raise ValueError("json_lines: no_nonempty_lines")
        for value in values:
            if OUTPUT_CONTRACT.get("required"):
                _check_object(value)
        return {{"lines": values}}
    value = _strict_json_loads(text)
    if OUTPUT_MODE == "object":
        _check_object(value)
        return value
    if OUTPUT_MODE == "array":
        if not isinstance(value, list):
            raise ValueError("wrong_root expected=array")
        return {{"value": value}}
    return {{"value": value}}


def _call(args):
    argv = [str(TOOL), str(args["input_path"])]
    out_path = None
    transient_out = None
    if args.get("out"):
        requested_out = Path(args["out"]).expanduser()
        out_path = requested_out.parent.resolve() / requested_out.name
        try:
            target_metadata = out_path.lstat()
        except FileNotFoundError:
            target_metadata = None
        if target_metadata is not None and (
            not stat.S_ISREG(target_metadata.st_mode)
            or target_metadata.st_nlink != 1
        ):
            raise RuntimeError("declared output target is unsafe")
        fd, transient_name = tempfile.mkstemp(
            prefix=f".{{out_path.name}}.repoproof-",
            suffix=".tmp",
            dir=out_path.parent,
        )
        os.close(fd)
        transient_out = Path(transient_name)
        transient_out.unlink()
        argv += ["--out", str(transient_out)]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        text = r.stdout if r.returncode == 0 else (r.stderr or f"exit {{r.returncode}}")
        if r.returncode == 0 and transient_out is not None:
            if transient_out.is_symlink() or not transient_out.is_file():
                return {{
                    "content": [{{"type": "text", "text":
                                 "declared output file unavailable"}}],
                    "isError": True,
                }}
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(transient_out, flags)
            try:
                metadata = os.fstat(fd)
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise OSError("fresh output is not a regular file")
                with os.fdopen(fd, "r", encoding="utf-8") as fh:
                    fd = -1
                    text = fh.read()
            finally:
                if fd >= 0:
                    os.close(fd)
        payload = {{"content": [{{"type": "text", "text": text}}],
                   "isError": r.returncode != 0}}
        if r.returncode == 0 and OUTPUT_CONTRACT is not None:
            try:
                payload["structuredContent"] = _structured_content(text)
            except (TypeError, ValueError):
                payload = {{
                    "content": [{{"type": "text", "text":
                                 "[tool-output-contract] runtime output invalid"}}],
                    "isError": True,
                }}
        if (
            r.returncode == 0
            and transient_out is not None
            and not payload["isError"]
        ):
            os.replace(transient_out, out_path)
            transient_out = None
        return payload
    finally:
        if transient_out is not None:
            transient_out.unlink(missing_ok=True)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = _strict_json_loads(line)
        except ValueError:
            continue
        method, rid = req.get("method", ""), req.get("id")
        if method == "initialize":
            _reply(rid, {{"protocolVersion": "2025-06-18",
                          "capabilities": {{"tools": {{}}}},
                          "serverInfo": {{"name": {name!r},
                                          "version": {version!r}}}}})
        elif method == "tools/list":
            try:
                with _RuntimeLocks():
                    _require_active()
                    _reply(rid, {{"tools": [TOOL_DEF]}})
            except RuntimeError as e:
                _reply(rid, error={{"code": -32001, "message": str(e)}})
        elif method == "tools/call":
            try:
                with _RuntimeLocks():
                    _require_active()
                    _reply(rid, _call(req["params"]["arguments"]))
            except (
                KeyError,
                RuntimeError,
                UnicodeError,
                subprocess.SubprocessError,
                OSError,
            ) as e:
                _reply(rid, error={{"code": -32000, "message": str(e)}})
        elif rid is not None:            # 未知带 id 请求:如实报不支持
            _reply(rid, error={{"code": -32601,
                                "message": f"method not found: {{method}}"}})
        # 通知(无 id)不回


if __name__ == "__main__":
    main()
'''


def write_mcp_server(tool_dir: Path, *, dest_root: Path | None = None) -> Path:
    """Generate MCP under the same install lock used by package upgrades."""

    requested_tool_dir = Path(tool_dir).absolute()
    if requested_tool_dir.is_symlink():
        raise RuntimeError(f"工具目录禁止 symlink:{requested_tool_dir}")
    tool_dir = requested_tool_dir.resolve()
    release_root = (
        Path(dest_root).resolve() if dest_root is not None else tool_dir.parent
    )
    with tool_install_lock(release_root):
        return _write_mcp_server_install_locked(tool_dir, release_root)


def _runtime_identity_files(tool_dir: Path, name: str) -> dict[str, str]:
    """Freeze the package files that can determine CLI/MCP behaviour."""

    candidates = [
        tool_dir / "tool.json",
        tool_dir / "evidence" / "provenance.json",
        tool_dir / "bin" / name,
    ]
    for optional in ("build.sh", "pyproject.toml", "requirements.lock.txt"):
        path = tool_dir / optional
        if path.is_file():
            candidates.append(path)
    src = tool_dir / "src"
    if src.is_dir():
        candidates.extend(sorted(src.rglob("*.py")))
    frozen: dict[str, str] = {}
    for path in candidates:
        if path.is_symlink() or not path.is_file() or tool_dir not in path.resolve().parents:
            raise RuntimeError(f"package identity file is unsafe: {path}")
        frozen[str(path.relative_to(tool_dir))] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return frozen


def _write_mcp_server_install_locked(tool_dir: Path, release_root: Path) -> Path:
    """Render and atomically replace one server while package identity is stable."""

    if tool_dir.parent != release_root:
        raise RuntimeError(f"工具目录不在受管 dest_root 内:{tool_dir}")
    try:
        ensure_safe_package_tree(tool_dir)
    except ToolPathError as exc:
        raise RuntimeError(str(exc)) from exc
    manifest = json.loads((tool_dir / "tool.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("tool manifest 必须为 JSON object")
    historical_verdict = (manifest.get("verification") or {}).get("verdict")
    if not is_historical_tool_ready(historical_verdict):
        raise RuntimeError(
            f"{manifest.get('name')}: historical_verdict={historical_verdict!r} —— "
            "MCP 暴露只服务 VERIFIED_TOOL_READY 工具")
    name = manifest["name"]
    try:
        if canonical_tool_path(release_root, name) != tool_dir:
            raise ToolPathError(f"工具目录不在受管 dest_root 内:{tool_dir}")
    except ToolPathError as exc:
        raise RuntimeError(str(exc)) from exc
    provenance_path = tool_dir / "evidence" / "provenance.json"
    if not provenance_path.is_file():
        raise RuntimeError(f"工具 provenance 不存在:{provenance_path}")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if not isinstance(provenance, dict):
        raise RuntimeError("工具 provenance 必须为 JSON object")
    task_id = provenance.get("task_id")
    verification = manifest.get("verification") or {}
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeError("工具 provenance task_id 必须为非空字符串")
    try:
        validate_tool_task_id(name, task_id)
    except ToolPathError as exc:
        raise RuntimeError(str(exc)) from exc
    if provenance.get("tool") != name:
        raise RuntimeError("provenance tool 与 manifest/canonical name 不一致")
    if (
        provenance.get("run_id") != verification.get("run_id")
        or provenance.get("tool_contract_sha256")
        != verification.get("contract_sha256")
    ):
        raise RuntimeError("manifest/provenance identity 不一致")
    status = operational_status(release_root, name, task_id=task_id)
    if status != ACTIVE:
        raise RuntimeError(
            f"{name}: operational_status={status} —— "
            "MCP 只暴露 fresh-input audit 后的 ACTIVE 工具"
        )
    output_contract = (
        ((manifest.get("interface") or {}).get("output") or {}).get("contract")
    )
    if output_contract is None:
        output_schema = None
        output_mode = None
        output_schema_entry = ""
    else:
        output_schema, output_mode = mcp_output_projection(output_contract)
        output_schema_entry = f'"outputSchema": {output_schema!r},'
    out = tool_dir / "mcp_server.py"
    encoded = _SERVER_TMPL.format(
        name=name,
        mcp_name=name.replace("-", "_"),
        description=(manifest.get("summary", "") + " "
                     + "(verified local tool; usage: "
                     + manifest.get("interface", {}).get("usage", "")).strip(),
        in_format=manifest.get("interface", {}).get("input", {}).get("format", ""),
        output_contract=output_contract,
        output_mode=output_mode,
        output_schema_entry=output_schema_entry,
        task_id=task_id,
        expected_package_files=_runtime_identity_files(tool_dir, name),
        tool_name_pattern=TOOL_NAME_PATTERN,
        version=manifest.get("version", "1.0.0"),
        server_path=str(out),
    )
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=tool_dir,
            prefix=".mcp_server.py.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            temp_name = fh.name
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
            os.fchmod(fh.fileno(), 0o755)
        os.replace(temp_name, out)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
    return out
