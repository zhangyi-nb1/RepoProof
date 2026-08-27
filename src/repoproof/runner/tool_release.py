"""Operational release decisions for verified local tools (RFC-011 M5-c/d).

Historical verification stays in ``tool.json``.  This module owns the separate,
append-only operational decision ledger.  The ledger is deliberately small and
strict: a malformed line makes every consumer fail closed instead of silently
resurrecting a withdrawn tool.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from repoproof.runner.tool_paths import (
    ToolPathError,
    append_control_file,
    canonical_tool_path,
    control_file_lock,
    ensure_safe_package_tree,
    read_control_file,
    tool_install_lock,
    validate_tool_name,
    validate_tool_task_id,
)

RELEASE_LEDGER_NAME = ".repoproof-release-decisions.jsonl"
RELEASE_LOCK_NAME = ".repoproof-release.lock"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
ACTIVE = "ACTIVE"
REVOKED = "REVOKED"
VALID_RELEASE_DECISIONS = frozenset({REVIEW_REQUIRED, ACTIVE, REVOKED})
VALID_ACTORS = frozenset({"human", "operator", "migration"})
HISTORICAL_READY_VERDICTS = frozenset(
    {"VERIFIED_TOOL_READY", "VERIFIED_TOOL_READY (DIRECT)"}
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ReleaseLedgerError(RuntimeError):
    """The operational ledger cannot be trusted or safely extended."""


class ToolAuditError(RuntimeError):
    """An audit could not safely start (as distinct from an audit failure)."""


@contextmanager
def release_decision_lock(dest_root: Path):
    """Serialize compound release checks and appends across processes."""

    try:
        with control_file_lock(dest_root, RELEASE_LOCK_NAME):
            yield
    except ToolPathError as exc:
        raise ReleaseLedgerError(str(exc)) from exc


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"non-standard JSON constant: {constant}")


def _strict_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _strict_json_loads(value: str | bytes) -> Any:
    return json.loads(
        value,
        parse_constant=_reject_json_constant,
        parse_float=_strict_json_float,
    )


def is_historical_tool_ready(verdict: Any) -> bool:
    """Accept only the two Product Mode verdicts mapped from completion PASS."""

    return isinstance(verdict, str) and verdict in HISTORICAL_READY_VERDICTS


def parse_operator_audit_outcome(row: dict[str, Any], *, where: str) -> bool:
    """Parse compatible audit outcome fields and reject contradictions."""

    has_ok = "ok" in row
    ok = row.get("ok")
    if has_ok and type(ok) is not bool:
        raise ReleaseLedgerError(f"{where}: ok 必须为 boolean")

    has_verdict = "verdict" in row
    verdict = row.get("verdict")
    verdict_ok: bool | None = None
    if has_verdict:
        if not isinstance(verdict, str) or verdict.upper() not in {"PASS", "FAIL"}:
            raise ReleaseLedgerError(f"{where}: verdict 必须为 PASS 或 FAIL")
        verdict_ok = verdict.upper() == "PASS"
    if not has_ok and not has_verdict:
        raise ReleaseLedgerError(f"{where}: audit 缺 PASS/FAIL verdict 或 boolean ok")
    if has_ok and verdict_ok is not None and ok != verdict_ok:
        raise ReleaseLedgerError(f"{where}: ok 与 verdict 矛盾")
    return bool(ok if has_ok else verdict_ok)


def _validate_rfc3339_utc(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == dt.timedelta(0)


def _validate_decision(row: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ReleaseLedgerError(f"{where}: release decision 必须是 JSON object")

    required = {
        "schema_version",
        "tool",
        "task_id",
        "run_id",
        "decision",
        "reason_code",
        "reason",
        "evidence_sha256",
        "decided_at",
        "actor",
    }
    missing = sorted(required - row.keys())
    if missing:
        raise ReleaseLedgerError(f"{where}: release decision 缺字段 {missing}")
    if type(row["schema_version"]) is not int or row["schema_version"] != 1:
        raise ReleaseLedgerError(f"{where}: schema_version 必须为 1")
    try:
        validate_tool_name(row["tool"])
    except ToolPathError as exc:
        raise ReleaseLedgerError(f"{where}: {exc}") from exc
    try:
        validate_tool_task_id(row["tool"], row["task_id"])
    except ToolPathError as exc:
        raise ReleaseLedgerError(f"{where}: {exc}") from exc
    if row["run_id"] is not None and not isinstance(row["run_id"], str):
        raise ReleaseLedgerError(f"{where}: run_id 必须为字符串或 null")
    if row["decision"] not in VALID_RELEASE_DECISIONS:
        raise ReleaseLedgerError(
            f"{where}: decision={row['decision']!r}，只允许 {sorted(VALID_RELEASE_DECISIONS)}"
        )
    if not isinstance(row["reason_code"], str) or not row["reason_code"].strip():
        raise ReleaseLedgerError(f"{where}: reason_code 必须为非空字符串")
    if not isinstance(row["reason"], str) or not row["reason"].strip():
        raise ReleaseLedgerError(f"{where}: reason 必须为非空字符串")
    if not isinstance(row["evidence_sha256"], str) or not _SHA256_RE.fullmatch(row["evidence_sha256"]):
        raise ReleaseLedgerError(f"{where}: evidence_sha256 必须为 64 位小写十六进制")
    if not _validate_rfc3339_utc(row["decided_at"]):
        raise ReleaseLedgerError(f"{where}: decided_at 必须为 RFC3339 UTC 时间")
    if row["actor"] not in VALID_ACTORS:
        raise ReleaseLedgerError(f"{where}: actor 只允许 {sorted(VALID_ACTORS)}")
    return row


def load_release_decisions_file(ledger: Path) -> list[dict[str, Any]]:
    """Load one ledger path and validate every row; damage fails closed.

    Path-based consumers such as the metrics exporter use this entry point so
    release-state schema validation has one implementation across the product.
    A missing ledger is the valid pre-audit state and therefore folds to no
    decisions (``REVIEW_REQUIRED`` at the consumer boundary).
    """

    ledger = Path(ledger)
    try:
        encoded = read_control_file(ledger, missing_ok=True)
        if encoded is None:
            return []
        if encoded and not encoded.endswith(b"\n"):
            raise ReleaseLedgerError(
                f"{ledger}: 非空 append-only ledger 必须以换行结束"
            )
        raw = encoded.decode("utf-8")
    except (ToolPathError, UnicodeError) as exc:
        raise ReleaseLedgerError(f"无法读取 release ledger {ledger}: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise ReleaseLedgerError(f"{ledger}:{line_no}: 空行使 append-only ledger 不可信")
        try:
            row = _strict_json_loads(line)
        except ValueError as exc:
            raise ReleaseLedgerError(f"{ledger}:{line_no}: 损坏 JSON: {exc}") from exc
        rows.append(_validate_decision(row, where=f"{ledger}:{line_no}"))
    return rows


def load_release_decisions(dest_root: Path) -> list[dict[str, Any]]:
    """Load the standard ledger below ``dest_root``."""

    return load_release_decisions_file(Path(dest_root) / RELEASE_LEDGER_NAME)


def fold_release_decisions(dest_root: Path) -> dict[str, dict[str, Any]]:
    """Fold by tool name; the last valid append-only decision wins."""

    folded: dict[str, dict[str, Any]] = {}
    for row in load_release_decisions(dest_root):
        folded[row["tool"]] = row
    return folded


def fold_release_statuses(dest_root: Path) -> dict[str, str]:
    """Stable read-only projection used by registry, metrics, and consumers."""

    return {tool: row["decision"] for tool, row in fold_release_decisions(dest_root).items()}


def operational_status(dest_root: Path, tool: str, *, task_id: str | None = None) -> str:
    """Return current status; absence or a task-version mismatch needs review.

    A tool name is a stable local command, but an audit decision is scoped to
    the frozen task version that produced it.  Passing ``task_id`` prevents a
    newly registered version from inheriting an older version's ``ACTIVE``.
    """

    row = fold_release_decisions(dest_root).get(tool)
    if row is None:
        return REVIEW_REQUIRED
    if task_id is not None and row["task_id"] != task_id:
        return REVIEW_REQUIRED
    return row["decision"]


def _append_release_decision_unlocked(
    dest_root: Path,
    *,
    tool: str,
    task_id: str,
    run_id: str | None,
    decision: str,
    reason_code: str,
    reason: str,
    evidence_sha256: str,
    actor: str,
    decided_at: str | None = None,
) -> dict[str, Any]:
    """Validate and append while the caller holds ``release_decision_lock``."""

    dest_root = Path(dest_root)
    # Crucial fail-closed step: never append behind a damaged row.
    load_release_decisions(dest_root)
    row: dict[str, Any] = {
        "schema_version": 1,
        "tool": tool,
        "task_id": task_id,
        "run_id": run_id,
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason,
        "evidence_sha256": evidence_sha256,
        "decided_at": decided_at or _utc_now(),
        "actor": actor,
    }
    _validate_decision(row, where="new release decision")
    dest_root.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        # One O_APPEND write keeps each validated decision as one record.
        append_control_file(dest_root / RELEASE_LEDGER_NAME, encoded)
    except (OSError, ToolPathError) as exc:
        raise ReleaseLedgerError(f"无法 append release decision: {exc}") from exc
    return row


def append_release_decision(
    dest_root: Path,
    *,
    tool: str,
    task_id: str,
    run_id: str | None,
    decision: str,
    reason_code: str,
    reason: str,
    evidence_sha256: str,
    actor: str,
    decided_at: str | None = None,
) -> dict[str, Any]:
    """Atomically validate the existing ledger and append one decision."""

    with release_decision_lock(dest_root):
        return _append_release_decision_unlocked(
            dest_root,
            tool=tool,
            task_id=task_id,
            run_id=run_id,
            decision=decision,
            reason_code=reason_code,
            reason=reason,
            evidence_sha256=evidence_sha256,
            actor=actor,
            decided_at=decided_at,
        )


def ensure_initial_review_decision(
    dest_root: Path,
    *,
    tool: str,
    task_id: str,
    run_id: str | None,
    evidence_sha256: str,
) -> dict[str, Any] | None:
    """Append initial REVIEW_REQUIRED only if this tool has no prior decision.

    Re-registration must never override an existing ACTIVE or REVOKED state.
    """

    with release_decision_lock(dest_root):
        current = fold_release_decisions(dest_root).get(tool)
        if current is not None and current["task_id"] == task_id:
            return None
        return _append_release_decision_unlocked(
            dest_root,
            tool=tool,
            task_id=task_id,
            run_id=run_id,
            decision=REVIEW_REQUIRED,
            reason_code="INITIAL_EXPORT_REVIEW_REQUIRED",
            reason="Export completed; fresh-input operational audit is required before activation.",
            evidence_sha256=evidence_sha256,
            actor="operator",
        )


def _tool_context(dest_root: Path, name: str) -> tuple[Path, dict[str, Any], str, str | None]:
    try:
        tool_dir = canonical_tool_path(dest_root, name)
        ensure_safe_package_tree(tool_dir)
    except ToolPathError as exc:
        raise ToolAuditError(str(exc)) from exc
    manifest_path = tool_dir / "tool.json"
    if not manifest_path.is_file():
        raise ToolAuditError(f"工具 manifest 不存在: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ToolAuditError(f"工具 manifest 无法读取: {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ToolAuditError(f"工具 manifest 必须为 JSON object: {manifest_path}")
    manifest_name = manifest.get("name")
    if manifest_name != name:
        raise ToolAuditError(f"目录名 {name!r} 与 tool.json name={manifest_name!r} 不一致")

    provenance_path = tool_dir / "evidence" / "provenance.json"
    if not provenance_path.is_file():
        raise ToolAuditError(f"工具 provenance 不存在: {provenance_path}")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ToolAuditError(f"provenance 无法读取: {provenance_path}: {exc}") from exc
    if not isinstance(provenance, dict):
        raise ToolAuditError(f"provenance 必须为 JSON object: {provenance_path}")
    task_id = provenance.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise ToolAuditError(f"provenance task_id 必须为非空字符串: {provenance_path}")
    try:
        validate_tool_task_id(name, task_id)
    except ToolPathError as exc:
        raise ToolAuditError(str(exc)) from exc
    if provenance.get("tool") != name:
        raise ToolAuditError("provenance tool 与 manifest/canonical name 不一致")
    verification = manifest.get("verification")
    if not isinstance(verification, dict):
        raise ToolAuditError("tool.json verification 必须为 JSON object")
    run_id = verification.get("run_id")
    contract_sha256 = verification.get("contract_sha256")
    if (
        not isinstance(run_id, str)
        or not run_id
        or provenance.get("run_id") != run_id
    ):
        raise ToolAuditError("manifest/provenance run_id 不一致")
    if (
        not isinstance(contract_sha256, str)
        or not contract_sha256
        or provenance.get("tool_contract_sha256") != contract_sha256
    ):
        raise ToolAuditError("manifest/provenance contract_sha256 不一致")
    return tool_dir, manifest, task_id, run_id


def _package_control_identity(tool_dir: Path) -> str:
    """Bind audit execution to the exact manifest/provenance bytes checked."""

    try:
        manifest_raw = (tool_dir / "tool.json").read_bytes()
        provenance_raw = (tool_dir / "evidence" / "provenance.json").read_bytes()
    except OSError as exc:
        raise ToolAuditError(f"无法读取 package identity:{exc}") from exc
    return _sha256(manifest_raw + b"\0" + provenance_raw)


def withdraw_tool(dest_root: Path, name: str, *, reason: str) -> dict[str, Any]:
    """Append a human withdrawal without deleting or rewriting the tool package."""

    dest_root = Path(dest_root)
    if not reason.strip():
        raise ToolAuditError("withdraw reason 不能为空")
    with tool_install_lock(dest_root):
        with release_decision_lock(dest_root):
            load_release_decisions(dest_root)
            _tool_dir, _manifest, task_id, run_id = _tool_context(dest_root, name)
            evidence_sha256 = _canonical_sha256(
                {
                    "action": "withdraw",
                    "tool": name,
                    "task_id": task_id,
                    "run_id": run_id,
                    "reason": reason,
                }
            )
            return _append_release_decision_unlocked(
                dest_root,
                tool=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="USER_WITHDRAWAL",
                reason=reason.strip(),
                evidence_sha256=evidence_sha256,
                actor="human",
            )


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _public_fixture_hashes(tool_dir: Path) -> set[str]:
    """Hash exported public fixtures so copying one elsewhere is not "fresh"."""

    hashes: set[str] = set()
    for relative_root in ("public_examples", "public_tests"):
        root = tool_dir / relative_root
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            if candidate.is_file():
                try:
                    hashes.add(_sha256(candidate.read_bytes()))
                except OSError as exc:
                    raise ToolAuditError(f"无法读取公开 fixture {candidate}: {exc}") from exc
    return hashes


def _output_contract_errors(manifest: dict[str, Any], actual: bytes) -> list[str]:
    contract = (((manifest.get("interface") or {}).get("output") or {}).get("contract"))
    if contract is None:  # Compatible legacy frozen tools retain exact-output audit semantics.
        return []
    try:
        text = actual.decode("utf-8")
    except UnicodeDecodeError:
        return ["[tool-output-contract] stdout is not UTF-8"]

    # This is the same deterministic parser used by freeze/runtime gates.
    from repoproof.adoption.assembly.output_contract import validate_output_text

    try:
        return validate_output_text(text, contract)
    except (TypeError, ValueError):
        return ["[tool-output-contract] declared contract is invalid"]


def _norm_output(raw: bytes) -> str:
    """与**合同自己的验收测试**同一口径的输出规范化。

    2026-08-28 实录:抽查用的是裸字节比对(`result.stdout != expected`),
    而 example_compiler 生成的能力测试用的是
    `_norm(s) = "\\n".join(line.rstrip() for line in s.strip().splitlines())`
    —— 于是**抽查比合同本身还严**:金标准样例文件都不以换行结尾,工具
    stdout 却带 `\n`;工具通过了全部 6 条能力测试,却因为这一个换行被抽查
    判 MISMATCH、自动撤回。用户照着看到的输出原样粘贴,照样被撤回。

    抽查是"拿没见过的输入再验一次同一份合同",它的判据就该是**合同的
    判据**。比合同更严不是更严谨,是换了一把尺子 —— 那样"通过合同"就
    推不出"通过抽查",两个结论各说各话。
    """
    text = raw.decode("utf-8", errors="replace")
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _record_audit_decision(
    dest_root: Path,
    *,
    name: str,
    task_id: str,
    run_id: str | None,
    decision: str,
    reason_code: str,
    reason: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    evidence_sha256 = _canonical_sha256(evidence)
    row = _append_release_decision_unlocked(
        dest_root,
        tool=name,
        task_id=task_id,
        run_id=run_id,
        decision=decision,
        reason_code=reason_code,
        reason=reason,
        evidence_sha256=evidence_sha256,
        actor="operator",
    )
    return {
        "ok": decision == ACTIVE,
        "tool": name,
        "task_id": task_id,
        "historical_verdict": evidence.get("historical_verdict"),
        "operational_status": decision,
        "reason_code": reason_code,
        "evidence_sha256": evidence_sha256,
        "decision": row,
    }


def _audit_tool_locked(
    dest_root: Path,
    name: str,
    *,
    input_path: Path,
    expected_file: Path,
    run_build: bool = False,
    timeout: int = 300,
) -> dict[str, Any]:
    """Run one fresh-input audit and append ACTIVE or REVOKED.

    No input, stdout, expected output, or stderr body is persisted.  The ledger
    receives only a digest of their hashes and the deterministic outcome.
    """

    dest_root = Path(dest_root)
    all_decisions = load_release_decisions(dest_root)  # validate before executing anything
    tool_dir, manifest, task_id, run_id = _tool_context(dest_root, name)
    package_identity = _package_control_identity(tool_dir)
    historical_verdict = (manifest.get("verification") or {}).get("verdict")
    if not is_historical_tool_ready(historical_verdict):
        raise ToolAuditError(
            f"{name}: historical_verdict={historical_verdict!r} 不是已验证工具，不能运营审核"
        )

    if any(
        row["tool"] == name
        and row["decision"] == REVOKED
        and row["reason_code"] == "OUTPUT_CONTRACT_MISMATCH"
        and row["task_id"] == task_id
        for row in all_decisions
    ):
        raise ToolAuditError(f"{name}: 当前 task 因输出合同缺陷撤回；必须发布新 task version，不能原地恢复")
    current = next(
        (row for row in reversed(all_decisions) if row["tool"] == name),
        None,
    )
    if (
        current is not None
        and current["task_id"] == task_id
        and current["decision"] == REVOKED
        and current["reason_code"] == "USER_WITHDRAWAL"
    ):
        raise ToolAuditError(
            f"{name}: 当前 task 已由用户撤回；普通 audit 无权恢复，需未来显式 restore 决策"
        )

    input_path = Path(input_path)
    expected_file = Path(expected_file)
    if not input_path.is_file():
        raise ToolAuditError(f"audit input 不存在: {input_path}")
    if not expected_file.is_file():
        raise ToolAuditError(f"expected file 不存在: {expected_file}")
    if _inside(input_path, tool_dir):
        raise ToolAuditError("audit input 位于工具包内，不满足 fresh non-example 要求")
    if _inside(expected_file, tool_dir):
        raise ToolAuditError("expected file 位于工具包内，不能直接复用旧真值")
    if timeout <= 0:
        raise ToolAuditError("timeout 必须大于 0")

    expected = expected_file.read_bytes()
    input_bytes = input_path.read_bytes()
    public_hashes = _public_fixture_hashes(tool_dir)
    if _sha256(input_bytes) in public_hashes:
        raise ToolAuditError("audit input 与工具包公开 fixture 相同，不满足 fresh non-example 要求")
    if _sha256(expected) in public_hashes:
        raise ToolAuditError("expected file 与工具包公开 fixture 相同，不能复用旧真值")
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "tool": name,
        "task_id": task_id,
        "run_id": run_id,
        "historical_verdict": historical_verdict,
        "input_sha256": _sha256(input_bytes),
        "expected_sha256": _sha256(expected),
        "build_requested": run_build,
    }

    if run_build:
        build_script = tool_dir / "build.sh"
        if not build_script.is_file():
            evidence["build"] = {"status": "missing"}
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="BUILD_FAILED",
                reason="Fresh-input audit requested a rebuild, but build.sh is missing.",
                evidence=evidence,
            )
        try:
            built = subprocess.run(
                ["bash", str(build_script)], cwd=tool_dir, capture_output=True, timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            evidence["build"] = {"status": type(exc).__name__}
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="BUILD_FAILED",
                reason="Fresh-input audit rebuild did not complete successfully.",
                evidence=evidence,
            )
        evidence["build"] = {
            "returncode": built.returncode,
            "stdout_sha256": _sha256(built.stdout),
            "stderr_sha256": _sha256(built.stderr),
        }
        if built.returncode != 0:
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="BUILD_FAILED",
                reason="Fresh-input audit rebuild returned a non-zero exit code.",
                evidence=evidence,
            )

        # build.sh is allowed to reconstruct the opaque top-level .venv, but
        # it must not replace a managed launcher with a symlink/special file or
        # rewrite the package identity that this audit is about.  Revalidate
        # after the subprocess and before resolving/executing bin/<name>.
        try:
            rebuilt_dir, rebuilt_manifest, rebuilt_task_id, rebuilt_run_id = (
                _tool_context(dest_root, name)
            )
            rebuilt_identity = _package_control_identity(rebuilt_dir)
            if (
                rebuilt_dir != tool_dir
                or rebuilt_task_id != task_id
                or rebuilt_run_id != run_id
                or rebuilt_identity != package_identity
            ):
                raise ToolAuditError("build 后 package identity 发生变化")
        except (OSError, ToolAuditError, ToolPathError, UnicodeError, ValueError) as exc:
            evidence["build_postcheck"] = {
                "status": "invalid-package",
                "diagnostic_sha256": _sha256(str(exc).encode("utf-8")),
            }
            return _record_audit_decision(
                dest_root,
                name=name,
                task_id=task_id,
                run_id=run_id,
                decision=REVOKED,
                reason_code="BUILD_FAILED",
                reason="Fresh-input audit rebuild left an unsafe or changed package identity.",
                evidence=evidence,
            )
        tool_dir = rebuilt_dir
        manifest = rebuilt_manifest

    executable = tool_dir / "bin" / name
    executable_problem = "missing-executable"
    try:
        executable_metadata = executable.lstat()
    except FileNotFoundError:
        executable_metadata = None
    except OSError as exc:
        executable_problem = type(exc).__name__
        executable_metadata = None
    if executable_metadata is not None and not stat.S_ISREG(executable_metadata.st_mode):
        executable_problem = "unsafe-executable"
    if executable_metadata is None or executable_problem == "unsafe-executable":
        evidence["execution"] = {"status": executable_problem}
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="FRESH_INPUT_EXECUTION_FAILED",
            reason="Tool executable is missing.",
            evidence=evidence,
        )
    try:
        result = subprocess.run(
            [str(executable), str(input_path.resolve())],
            cwd=tool_dir,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        evidence["execution"] = {"status": type(exc).__name__}
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="FRESH_INPUT_EXECUTION_FAILED",
            reason="Tool did not complete the fresh-input audit.",
            evidence=evidence,
        )

    evidence["execution"] = {
        "returncode": result.returncode,
        "stdout_sha256": _sha256(result.stdout),
        "stderr_sha256": _sha256(result.stderr),
    }
    if result.returncode != 0:
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="FRESH_INPUT_EXECUTION_FAILED",
            reason="Tool returned a non-zero exit code for the fresh input.",
            evidence=evidence,
        )
    stdout_matches = (result.stdout == expected
                      or _norm_output(result.stdout) == _norm_output(expected))
    evidence["execution"]["comparison"] = (
        "exact" if result.stdout == expected else "contract_normalized")
    if not stdout_matches:
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="FRESH_INPUT_MISMATCH",
            reason="Tool stdout did not exactly match the operator-provided expected file.",
            evidence=evidence,
        )

    contract_errors = _output_contract_errors(manifest, result.stdout)
    if contract_errors:
        # Error strings are stable structural diagnostics and never contain stdout.
        evidence["output_contract_errors"] = contract_errors
        return _record_audit_decision(
            dest_root,
            name=name,
            task_id=task_id,
            run_id=run_id,
            decision=REVOKED,
            reason_code="OUTPUT_CONTRACT_MISMATCH",
            reason="Fresh output matched the expected file but violated the declared output contract.",
            evidence=evidence,
        )

    return _record_audit_decision(
        dest_root,
        name=name,
        task_id=task_id,
        run_id=run_id,
        decision=ACTIVE,
        reason_code="FRESH_INPUT_PASS",
        reason="Fresh-input execution matched the expected file and declared output contract.",
        evidence=evidence,
    )


def audit_tool(
    dest_root: Path,
    name: str,
    *,
    input_path: Path,
    expected_file: Path,
    run_build: bool = False,
    timeout: int = 300,
) -> dict[str, Any]:
    """Serialize the whole audit so a concurrent withdrawal always wins last."""

    with tool_install_lock(dest_root):
        with release_decision_lock(dest_root):
            return _audit_tool_locked(
                dest_root,
                name,
                input_path=input_path,
                expected_file=expected_file,
                run_build=run_build,
                timeout=timeout,
            )


def _migration_time(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return _utc_now()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            dt.date.fromisoformat(value)
        except ValueError as exc:
            raise ReleaseLedgerError(f"audit audited_at 非法: {value!r}") from exc
        return f"{value}T00:00:00Z"
    if not _validate_rfc3339_utc(value):
        raise ReleaseLedgerError(f"audit audited_at 非 RFC3339 UTC: {value!r}")
    return value


def import_audit_decisions(
    audits_path: Path,
    dest_root: Path,
    *,
    actor: str = "migration",
) -> dict[str, int]:
    """Import audits while preventing concurrent package replacement."""

    with tool_install_lock(dest_root):
        return _import_audit_decisions_install_locked(
            audits_path,
            dest_root,
            actor=actor,
        )


def _import_audit_decisions_install_locked(
    audits_path: Path,
    dest_root: Path,
    *,
    actor: str = "migration",
) -> dict[str, int]:
    """Import append-only M4 operator audits as idempotent release decisions.

    The evidence digest is the SHA-256 of the exact JSON record bytes (without
    its line ending).  The source file is fully validated before any append.
    """

    if actor not in VALID_ACTORS:
        raise ReleaseLedgerError(f"actor 只允许 {sorted(VALID_ACTORS)}")
    audits_path = Path(audits_path)
    try:
        raw_lines = audits_path.read_bytes().splitlines()
    except OSError as exc:
        raise ReleaseLedgerError(f"无法读取 audit ledger {audits_path}: {exc}") from exc
    if not raw_lines:
        raise ReleaseLedgerError(f"audit ledger 为空: {audits_path}")

    prepared: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(raw_lines, start=1):
        if not raw_line.strip():
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 空行")
        try:
            audit = _strict_json_loads(raw_line)
        except (UnicodeError, ValueError) as exc:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: 损坏 JSON: {exc}") from exc
        if not isinstance(audit, dict):
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: audit 必须为 JSON object")
        tool = audit.get("tool")
        task_id = audit.get("task_id")
        if not isinstance(tool, str) or not tool or not isinstance(task_id, str):
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: audit 缺 tool/task_id")

        outcome = parse_operator_audit_outcome(
            audit, where=f"{audits_path}:{line_no}"
        )
        decision = ACTIVE if outcome else REVOKED
        verdict = audit.get("verdict")
        ok = audit.get("ok")

        if audit.get("mode") != "fresh-input-cli":
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: mode 必须为 fresh-input-cli"
            )
        if audit.get("input_is_example") is not False:
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: input_is_example 必须显式为 false"
            )

        raw_note = audit.get("note")
        note = raw_note if isinstance(raw_note, str) else ""
        mismatch = decision == REVOKED and any(
            marker in note.lower() for marker in ("contract", "oracle", "合同", "题面")
        )
        reason_code = (
            "OUTPUT_CONTRACT_MISMATCH"
            if mismatch
            else ("MIGRATED_FRESH_INPUT_PASS" if decision == ACTIVE else "MIGRATED_AUDIT_FAIL")
        )
        try:
            tool_dir = canonical_tool_path(dest_root, tool)
            ensure_safe_package_tree(tool_dir)
        except ToolPathError as exc:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: {exc}") from exc
        manifest_path = tool_dir / "tool.json"
        if not manifest_path.is_file():
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: 迁移目标 manifest 不存在 {manifest_path}"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReleaseLedgerError(
                f"无法读取迁移目标 manifest {manifest_path}: {exc}"
            ) from exc
        if not isinstance(manifest, dict):
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: 迁移目标 manifest 必须为 JSON object"
            )
        if manifest.get("name") != tool:
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: audit tool 与 manifest name 不一致"
            )
        historical_verdict = (manifest.get("verification") or {}).get("verdict")
        if not is_historical_tool_ready(historical_verdict):
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: 迁移目标不是历史 VERIFIED_TOOL_READY"
            )
        provenance_path = tool_dir / "evidence" / "provenance.json"
        if not provenance_path.is_file():
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: 迁移目标缺 provenance {provenance_path}"
            )
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReleaseLedgerError(
                f"无法读取迁移目标 provenance {provenance_path}: {exc}"
            ) from exc
        if not isinstance(provenance, dict):
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: 迁移目标 provenance 必须为 JSON object"
            )
        if provenance.get("task_id") != task_id:
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: audit task_id 与 provenance 不一致"
            )
        try:
            validate_tool_task_id(tool, task_id)
        except ToolPathError as exc:
            raise ReleaseLedgerError(f"{audits_path}:{line_no}: {exc}") from exc
        if provenance.get("tool") != tool:
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: provenance tool 与 manifest name 不一致"
            )
        verification = manifest.get("verification") or {}
        run_id = verification.get("run_id")
        if (
            not isinstance(run_id, str)
            or not run_id
            or provenance.get("run_id") != run_id
            or provenance.get("tool_contract_sha256")
            != verification.get("contract_sha256")
        ):
            raise ReleaseLedgerError(
                f"{audits_path}:{line_no}: manifest/provenance identity 不一致"
            )
        prepared.append(
            {
                "tool": tool,
                "task_id": task_id,
                "run_id": run_id,
                "decision": decision,
                "reason_code": reason_code,
                "reason": f"Migrated operator fresh-input audit: {verdict or ('PASS' if ok else 'FAIL')}.",
                "evidence_sha256": _sha256(raw_line),
                "decided_at": _migration_time(audit.get("audited_at")),
                "actor": actor,
            }
        )

    # Validate every derived row before the first append so a malformed later
    # source record cannot leave a partially migrated decision ledger.
    for line_no, row in enumerate(prepared, start=1):
        _validate_decision(
            {"schema_version": 1, **row},
            where=f"{audits_path}:{line_no} derived release decision",
        )

    with release_decision_lock(dest_root):
        existing = load_release_decisions(dest_root)
        seen = {
            (row["evidence_sha256"], row["tool"], row["decision"])
            for row in existing
        }
        latest_by_tool: dict[str, dict[str, Any]] = {}
        contract_defect_tasks: set[tuple[str, str]] = set()
        for existing_row in existing:
            latest_by_tool[existing_row["tool"]] = existing_row
            if existing_row["reason_code"] == "OUTPUT_CONTRACT_MISMATCH":
                contract_defect_tasks.add(
                    (existing_row["tool"], existing_row["task_id"])
                )
        counts = {"imported": 0, "skipped": 0, "active": 0, "revoked": 0}
        for row in prepared:
            key = (row["evidence_sha256"], row["tool"], row["decision"])
            if key in seen:
                counts["skipped"] += 1
                continue
            current = latest_by_tool.get(row["tool"])
            if (
                row["decision"] == ACTIVE
                and (row["tool"], row["task_id"]) in contract_defect_tasks
            ) or (
                current is not None
                and (
                    current["task_id"] != row["task_id"]
                    or (
                        current["actor"] != "migration"
                        and current["reason_code"]
                        != "INITIAL_EXPORT_REVIEW_REQUIRED"
                    )
                )
            ):
                # A historical migration may seed an unreviewed export, but
                # it must never supersede a newer task or explicit human /
                # operator decision merely because its line appends later.
                counts["skipped"] += 1
                continue
            _append_release_decision_unlocked(dest_root, **row)
            seen.add(key)
            latest_by_tool[row["tool"]] = {"schema_version": 1, **row}
            if row["reason_code"] == "OUTPUT_CONTRACT_MISMATCH":
                contract_defect_tasks.add((row["tool"], row["task_id"]))
            counts["imported"] += 1
            counts["active" if row["decision"] == ACTIVE else "revoked"] += 1
        return counts
