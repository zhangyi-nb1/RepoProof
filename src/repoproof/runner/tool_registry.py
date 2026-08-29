"""本地工具注册表(M3-b · RFC-010 §六 M3)。

一个 append-friendly 的 JSON 索引(`<dest_root>/.repoproof-registry.json`),
记录"这台机器上有哪些已验证工具、证据在哪"。纪律:
  - 注册表是**索引不是事实源** —— verdict/哈希以工具包内 tool.json 与
    evidence/ 为准;list 时逐项复核 manifest 是否仍在、verification 是否
    仍非空,漂移如实标注(MISSING/UNVERIFIED),不静默剔除;
  - `--scan` 可补录目录下未经注册的工具包(exported_at 记 null,
    provenance 标 scan —— 不伪造导出时间)。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

from repoproof.runner.tool_paths import (
    INSTALL_LOCK_NAME,
    ToolPathError,
    canonical_tool_path,
    ensure_safe_package_tree,
    read_control_file,
    tool_install_lock,
    validate_control_target,
    validate_tool_name,
    validate_tool_task_id,
)
from repoproof.runner.tool_release import (
    REVIEW_REQUIRED,
    ensure_initial_review_decision,
    fold_release_decisions,
    is_historical_tool_ready,
)

REGISTRY_NAME = ".repoproof-registry.json"
REGISTRY_LOCK_NAME = INSTALL_LOCK_NAME
registry_install_lock = tool_install_lock

_REFERENCE_IDENTITY_KEYS = {"impl_sha256", "lock_sha256"}
_LOWER_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_reference_identity(
    value: object,
    *,
    required: bool = False,
) -> dict[str, str] | None:
    """Validate the immutable identity of a task's frozen reference pair.

    Legacy exported packages do not carry this optional field.  Once present,
    however, it is deliberately exact: accepting additional keys or permissive
    hash spellings would create two identity dialects at the trust boundary.
    """

    if value is None:
        if required:
            raise ValueError("reference_identity 缺失")
        return None
    if not isinstance(value, dict) or set(value) != _REFERENCE_IDENTITY_KEYS:
        raise ValueError(
            "reference_identity 必须且只能包含 impl_sha256/lock_sha256"
        )
    identity: dict[str, str] = {}
    for key in sorted(_REFERENCE_IDENTITY_KEYS):
        digest = value.get(key)
        if not isinstance(digest, str) or _LOWER_SHA256.fullmatch(digest) is None:
            raise ValueError(f"reference_identity.{key} 必须是 64 位小写 SHA-256")
        identity[key] = digest
    return identity


def _load(dest_root: Path) -> dict:
    p = Path(dest_root) / REGISTRY_NAME
    raw = read_control_file(p, missing_ok=True)
    if raw is None:
        return {"schema_version": 1, "tools": {}}
    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-standard JSON constant: {constant}")

    def strict_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"non-finite JSON number: {value}")
        return parsed

    doc = json.loads(
        raw.decode("utf-8"),
        parse_constant=reject_constant,
        parse_float=strict_float,
    )
    if (
        not isinstance(doc, dict)
        or doc.get("schema_version") != 1
        or not isinstance(doc.get("tools"), dict)
        or any(
            not isinstance(name, str) or not isinstance(entry, dict)
            for name, entry in doc["tools"].items()
        )
    ):
        raise ValueError("registry schema invalid")
    return doc


def load_registry(dest_root: Path) -> dict:
    """Load and validate the complete registry for cross-module preflights.

    Upgrade preflight runs before real-model budget is spent, so it must use
    the same whole-document validation as registration settlement rather than
    validating only the target tool entry.
    """

    return _load(dest_root)


def _save(dest_root: Path, doc: dict) -> None:
    """Atomically replace the registry; a failed write leaves the old JSON intact."""

    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    target = dest_root / REGISTRY_NAME
    validate_control_target(target, missing_ok=True)
    encoded = json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dest_root,
            prefix=f".{REGISTRY_NAME}.",
            suffix=".tmp",
            delete=False,
        ) as fh:
            temp_name = fh.name
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_name, target)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def _load_package_provenance(
    tool_dir: Path, manifest: dict, *, require_verification_binding: bool = True
) -> tuple[str, dict]:
    if not isinstance(manifest, dict):
        raise ValueError("tool manifest 必须为 JSON object")
    name = manifest.get("name")
    prov_p = tool_dir / "evidence" / "provenance.json"
    if not prov_p.is_file():
        raise ValueError(f"{name}: provenance 不存在")
    provenance = json.loads(prov_p.read_text(encoding="utf-8"))
    if not isinstance(provenance, dict):
        raise ValueError(f"{name}: provenance 必须为 JSON object")
    task_id = provenance.get("task_id")
    verification = manifest.get("verification") or {}
    if not isinstance(task_id, str) or not task_id:
        raise ValueError(f"{name}: provenance task_id 必须非空")
    validate_tool_task_id(name, task_id)
    if provenance.get("tool") != name:
        raise ValueError(f"{name}: provenance tool 与 manifest name 不一致")
    if require_verification_binding and (
        provenance.get("run_id") != verification.get("run_id")
        or provenance.get("tool_contract_sha256")
        != verification.get("contract_sha256")
    ):
        raise ValueError(f"{name}: manifest/provenance identity 不一致")
    if "reference_identity" in provenance:
        # Keep legacy packages readable when the field is absent, but a package
        # that claims the new identity must use the one exact representation.
        provenance["reference_identity"] = validate_reference_identity(
            provenance.get("reference_identity"), required=True
        )
    return task_id, provenance


def _validate_upgrade_archive(
    dest_root: Path,
    name: str,
    replaces: dict,
    expected: dict,
) -> None:
    """Prove that an installer settlement preserved the indexed old package."""

    archive_value = replaces.get("archive_path")
    if not isinstance(archive_value, str):
        raise ValueError(f"{name}: replaces.archive_path 缺失")
    relative = Path(archive_value)
    if (
        relative.is_absolute()
        or len(relative.parts) != 3
        or relative.parts[:2] != (".repoproof-versions", name)
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"{name}: archive_path 不在受管版本目录")
    archive = dest_root.resolve() / relative
    expected_parent = dest_root.resolve() / ".repoproof-versions" / name
    if archive.parent.resolve() != expected_parent or archive.is_symlink():
        raise ValueError(f"{name}: archive_path 逃逸受管版本目录")
    ensure_safe_package_tree(archive)
    manifest_path = archive / "tool.json"
    provenance_path = archive / "evidence" / "provenance.json"
    manifest_raw = manifest_path.read_bytes()
    provenance_raw = provenance_path.read_bytes()
    manifest = json.loads(manifest_raw.decode("utf-8"))
    task_id, provenance = _load_package_provenance(archive, manifest)
    verification = manifest.get("verification") or {}
    identity = hashlib.sha256(manifest_raw + b"\0" + provenance_raw).hexdigest()
    if (
        manifest.get("name") != name
        or task_id != expected.get("task_id")
        or verification.get("run_id") != expected.get("run_id")
        or verification.get("contract_sha256") != expected.get("contract_sha256")
        or identity != expected.get("package_identity")
        or replaces.get("task_id") != task_id
        or replaces.get("run_id") != verification.get("run_id")
        or replaces.get("contract_sha256") != verification.get("contract_sha256")
        or provenance.get("task_id") != task_id
    ):
        raise ValueError(f"{name}: archived previous package identity 不一致")


def register_tool(dest_root: Path, tool_dir: Path, *,
                  run_id: str | None, exported_at: str | None,
                  _lock_held: bool = False,
                  _upgrade_previous: dict | None = None) -> dict:
    """导出后登记(pipeline 显式调用;export 本身保持纯函数)。"""
    if not _lock_held:
        with registry_install_lock(dest_root):
            return register_tool(
                dest_root,
                tool_dir,
                run_id=run_id,
                exported_at=exported_at,
                _lock_held=True,
                _upgrade_previous=_upgrade_previous,
            )
    dest_root = Path(dest_root)
    tool_dir = Path(tool_dir)
    directory_name = validate_tool_name(tool_dir.name)
    if tool_dir.resolve() != canonical_tool_path(dest_root, directory_name):
        raise ValueError(f"工具目录必须直接位于 dest_root 内:{tool_dir}")
    ensure_safe_package_tree(tool_dir)
    manifest_path = tool_dir / "tool.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    manifest_name = manifest.get("name")
    validate_tool_name(manifest_name)
    if manifest_name != directory_name:
        raise ValueError(
            f"工具目录名 {directory_name!r} 与 manifest name={manifest_name!r} 不一致"
        )
    historical_verdict = (manifest.get("verification") or {}).get("verdict")
    if not is_historical_tool_ready(historical_verdict):
        raise ValueError(
            f"{manifest.get('name')}: historical_verdict={historical_verdict!r}; "
            "registry 只接收 VERIFIED_TOOL_READY 工具"
        )
    task_id, provenance = _load_package_provenance(tool_dir, manifest)
    verification = manifest.get("verification") or {}
    if run_id is not None and run_id != verification.get("run_id"):
        raise ValueError(f"{manifest_name}: 调用 run_id 与 package identity 不一致")
    entry: dict = {
        "path": str(tool_dir),
        "task_id": task_id,
        "run_id": run_id or (manifest.get("verification") or {}).get("run_id"),
        # Keep verdict for old registry readers; historical_verdict is explicit
        # for RFC-011 consumers.  Neither field is the operational truth source.
        "verdict": historical_verdict,
        "historical_verdict": historical_verdict,
        "contract_sha256": (manifest.get("verification") or {}).get("contract_sha256"),
        "source": manifest.get("source", {}),
        "summary": manifest.get("summary", ""),
        "exported_at": exported_at,
    }
    reference_identity = validate_reference_identity(
        provenance.get("reference_identity"),
        required="reference_identity" in provenance,
    )
    if reference_identity is not None:
        entry["reference_identity"] = reference_identity
    # Validate both existing indexes before any write.  Initial export appends
    # REVIEW_REQUIRED only once; a repeated registration never masks a revoke.
    doc = _load(dest_root)
    previous = doc["tools"].get(manifest_name)
    if previous is not None:
        previous_task_id = previous.get("task_id")
        if previous_task_id == task_id:
            previous_run_id = previous.get("run_id")
            previous_contract = previous.get("contract_sha256")
            if (
                previous_run_id not in (None, entry["run_id"])
                or previous_contract not in (None, entry["contract_sha256"])
            ):
                raise ValueError(
                    f"{manifest_name}: 同一 task_id={task_id!r} 的 run/contract "
                    "与 registry 不一致，拒绝覆盖"
                )
            previous_reference_identity = validate_reference_identity(
                previous.get("reference_identity"),
                required="reference_identity" in previous,
            )
            if previous_reference_identity != reference_identity:
                raise ValueError(
                    f"{manifest_name}: 同一 task_id={task_id!r} 的 reference_identity "
                    "与 registry 不一致，拒绝覆盖"
                )
            entry["previous_versions"] = list(previous.get("previous_versions", []))
        else:
            replaces = provenance.get("replaces")
            if not isinstance(replaces, dict) or _upgrade_previous is None:
                raise ValueError(
                    f"{manifest_name}: task 变更只能由受管 installer 结算"
                )
            if any(
                previous.get(field) != _upgrade_previous.get(field)
                for field in ("task_id", "run_id", "contract_sha256")
            ):
                raise ValueError(f"{manifest_name}: installer 前态与 registry 不一致")
            indexed_previous_task = previous_task_id or replaces.get("task_id")
            if replaces.get("task_id") != indexed_previous_task:
                raise ValueError(
                    f"{manifest_name}: 新版本 provenance 未绑定 registry 中的前一 task"
                )
            _validate_upgrade_archive(
                dest_root,
                manifest_name,
                replaces,
                _upgrade_previous,
            )
            history = list(previous.get("previous_versions", []))
            history.append(
                {
                    "task_id": indexed_previous_task,
                    "run_id": previous.get("run_id"),
                    "contract_sha256": previous.get("contract_sha256"),
                    "exported_at": previous.get("exported_at"),
                    "archive_path": replaces.get("archive_path"),
                    "historical_verdict": previous.get(
                        "historical_verdict", previous.get("verdict")
                    ),
                }
            )
            entry["previous_versions"] = history
    ensure_initial_review_decision(
        dest_root,
        tool=manifest_name,
        task_id=task_id,
        run_id=entry["run_id"],
        evidence_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )
    doc["tools"][manifest_name] = entry
    _save(dest_root, doc)
    return entry


def list_tools(
    dest_root: Path, *, scan: bool = False, _lock_held: bool = False
) -> list[dict]:
    """List package health plus historical and operational release status."""
    if scan and not _lock_held:
        with registry_install_lock(dest_root):
            return list_tools(dest_root, scan=True, _lock_held=True)
    dest_root = Path(dest_root)
    doc = _load(dest_root)
    release_decisions = fold_release_decisions(dest_root)
    if scan and dest_root.is_dir():
        for d in sorted(p for p in dest_root.iterdir() if p.is_dir()):
            try:
                ensure_safe_package_tree(d)
            except ToolPathError:
                continue
            mf = d / "tool.json"
            if not mf.is_file():
                continue
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if not isinstance(m, dict):
                continue
            name = m.get("name")
            if not name:
                continue
            try:
                validate_tool_name(name)
                if d.resolve() != canonical_tool_path(dest_root, name):
                    continue
            except ToolPathError:
                continue
            historical_verdict = (m.get("verification") or {}).get("verdict")
            try:
                task_id, package_provenance = _load_package_provenance(
                    d,
                    m,
                    require_verification_binding=is_historical_tool_ready(
                        historical_verdict
                    ),
                )
            except (OSError, UnicodeError, ValueError):
                continue
            observed = {
                "task_id": task_id,
                "run_id": (m.get("verification") or {}).get("run_id"),
                "verdict": historical_verdict,
                "historical_verdict": historical_verdict,
                "contract_sha256": (m.get("verification") or {}).get(
                    "contract_sha256"
                ),
            }
            package_reference_identity = validate_reference_identity(
                package_provenance.get("reference_identity"),
                required="reference_identity" in package_provenance,
            )
            if package_reference_identity is not None:
                observed["reference_identity"] = package_reference_identity
            if name not in doc["tools"]:
                doc["tools"][name] = {
                    "path": str(d),
                    **observed,
                    "source": m.get("source", {}),
                    "summary": m.get("summary", ""),
                    "exported_at": None,           # scan 补录:不伪造导出时间
                    "provenance": "scan",
                }
            else:
                entry = doc["tools"][name]
                indexed_path = entry.get("path")
                if indexed_path and Path(indexed_path).resolve() != d.resolve():
                    continue
                entry.setdefault("path", str(d))
                # Repair only absent legacy index fields from the package
                # evidence. Conflicting non-empty values remain visible and
                # make upgrade preflight fail instead of being overwritten.
                for field, value in observed.items():
                    # A legacy same-task row cannot acquire a trust identity
                    # after export.  That would let a caller edit provenance and
                    # use scan as a self-attestation mechanism.  Only an entirely
                    # new scanned entry may record reference_identity.
                    if field == "reference_identity":
                        continue
                    if entry.get(field) in (None, "") and value not in (None, ""):
                        entry[field] = value
        _save(dest_root, doc)

    out: list[dict] = []
    for name, entry in sorted(doc["tools"].items()):
        row = {"name": name, **entry}
        historical_verdict = entry.get("historical_verdict", entry.get("verdict"))
        try:
            indexed_path = entry.get("path")
            if not isinstance(indexed_path, str):
                raise ToolPathError("registry path 必须为字符串")
            tool_dir = Path(indexed_path)
            if tool_dir.resolve() != canonical_tool_path(dest_root, name):
                raise ToolPathError("registry path 不指向受管 canonical tool 目录")
            if not tool_dir.exists():
                row["status"] = "MISSING"
                row["historical_verdict"] = historical_verdict
                row["verdict"] = historical_verdict
                row["operational_status"] = REVIEW_REQUIRED
                row["operational_reason_code"] = "PACKAGE_MISSING"
                out.append(row)
                continue
            ensure_safe_package_tree(tool_dir)
        except (OSError, ToolPathError, TypeError, ValueError):
            # A registry is an index, never authority to read arbitrary paths.
            # Keep the damaged row visible, but do not derive manifest,
            # provenance, MCP, or ACTIVE state from an external target.
            row["status"] = "INVALID_PATH"
            row["historical_verdict"] = historical_verdict
            row["verdict"] = historical_verdict
            row["operational_status"] = REVIEW_REQUIRED
            row["operational_reason_code"] = "INVALID_REGISTRY_PATH"
            out.append(row)
            continue
        mf = tool_dir / "tool.json"
        if not mf.is_file():
            row["status"] = "MISSING"
        else:
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
                if not isinstance(m, dict) or m.get("name") != name:
                    raise ValueError("manifest name 与 canonical directory 不一致")
                historical_verdict = (m.get("verification") or {}).get("verdict")
                row["status"] = (
                    "OK" if is_historical_tool_ready(historical_verdict) else "UNVERIFIED"
                )
                provenance_task_id, package_provenance = _load_package_provenance(
                    tool_dir,
                    m,
                    require_verification_binding=is_historical_tool_ready(
                        historical_verdict
                    ),
                )
                row["task_id"] = provenance_task_id
                package_reference_identity = validate_reference_identity(
                    package_provenance.get("reference_identity"),
                    required="reference_identity" in package_provenance,
                )
                registry_reference_identity = validate_reference_identity(
                    entry.get("reference_identity"),
                    required="reference_identity" in entry,
                )
                if (
                    package_reference_identity is not None
                    or registry_reference_identity is not None
                ) and package_reference_identity != registry_reference_identity:
                    raise ValueError("registry/package reference_identity 不一致")
            except (OSError, UnicodeError, ValueError):
                row["status"] = "MISSING"
        row["historical_verdict"] = historical_verdict
        # Preserve the legacy alias in list output while making its meaning
        # explicit.  Operational state is always folded from the JSONL ledger.
        row["verdict"] = historical_verdict
        if row["status"] == "MISSING" and mf.is_file():
            row["status"] = "INVALID_IDENTITY"
            row["operational_status"] = REVIEW_REQUIRED
            row["operational_reason_code"] = "INVALID_PACKAGE_IDENTITY"
            out.append(row)
            continue
        release = release_decisions.get(name)
        current_task_id = row.get("task_id", "")
        release_matches = bool(
            release is not None and release["task_id"] == current_task_id
        )
        if row["status"] != "OK":
            # Historical/package health is a prerequisite for any operational
            # decision.  A stale ACTIVE ledger row can never promote an
            # unverified package; callers receive the same fail-closed Core
            # projection without needing a UI-specific override.
            row["operational_status"] = REVIEW_REQUIRED
            row["operational_reason_code"] = (
                "PACKAGE_MISSING"
                if row["status"] == "MISSING"
                else "HISTORICAL_VERIFICATION_NOT_READY"
            )
        elif release is not None and release_matches:
            # release_matches 定义即含非 None;重述一遍只为类型可证,恒等
            row["operational_status"] = release["decision"]
            row["operational_reason_code"] = release["reason_code"]
            row["operational_task_id"] = release["task_id"]
        elif release is not None:
            row["operational_status"] = REVIEW_REQUIRED
            row["operational_reason_code"] = "TASK_VERSION_UNAUDITED"
            row["previous_operational_task_id"] = release["task_id"]
        else:
            row["operational_status"] = REVIEW_REQUIRED
        mcp_server = tool_dir / "mcp_server.py"
        if mcp_server.is_file():
            row["mcp_server_present"] = True
            try:
                runtime_aware = "RELEASE_LEDGER =" in mcp_server.read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeError):
                runtime_aware = False
            row["mcp_runtime_release_enforced"] = runtime_aware
            if row["operational_status"] != "ACTIVE" and not runtime_aware:
                row["mcp_exposure_warning"] = "LEGACY_SERVER_MUST_BE_DETACHED"
        out.append(row)
    return out
