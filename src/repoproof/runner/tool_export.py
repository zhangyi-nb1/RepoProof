"""Verified Local Tool 导出(M1 · TOOL_PACKAGE_LAYOUT §一/§二/§五)。

把一发 **通过 gate 的** LOCAL-TOOL run 物化成用户可用的工具包:
    <dest_root>/<tool.name>/
        …骨架 + agent 补丁(= 冻结的 adaptation.patch 重放到骨架副本)
        tool.json          verification 键由此处填充(此前必须为 null)
        evidence/          report / adaptation_manifest / verification/*
                           / provenance(EXPORT_ONLY 纪律:held-out 与
                           oracle 永不进包)

纪律:
  - 只认 gate 结论:report.json 的 verdict ∈ {PASS_ADAPTED, PASS_DIRECT},
    其余一律拒导出 —— FAIL 也交付证据包,但那走 run_dir,不落 ~/tools;
  - 交付树 = 骨架 + patch 确定性重建(与 clean replay 同构),不从会话
    工作树拷贝 —— 结论出自 patch,交付也必须出自 patch;
  - agent 写的 tool.json verification 必须是 null(越权声明在此拦截)。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from repoproof.domain.models import TaskContract
from repoproof.runner.tool_paths import (
    ToolPathError,
    canonical_tool_path,
    ensure_managed_directory,
    ensure_safe_package_tree,
    tool_install_lock,
    validate_tool_task_id,
)
from repoproof.runner.tool_registry import load_registry, register_tool
from repoproof.runner.tool_release import (
    ensure_initial_review_decision,
    is_historical_tool_ready,
    load_release_decisions,
)

_PASS = {"PASS_ADAPTED", "PASS_DIRECT"}


class ToolExportError(RuntimeError):
    pass


def _tool_path(root: Path, name: str) -> Path:
    """Resolve one canonical command path without allowing path traversal."""

    try:
        return canonical_tool_path(root, name)
    except ToolPathError as exc:
        raise ToolExportError(str(exc)) from exc


def _require_safe_package_tree(root: Path) -> None:
    try:
        ensure_safe_package_tree(root)
    except ToolPathError as exc:
        raise ToolExportError(str(exc)) from exc


def _tree_identity_no_follow(root: Path) -> str:
    """Hash a candidate subtree including modes and symlink targets."""

    digest = hashlib.sha256()
    if not root.exists() and not root.is_symlink():
        digest.update(b"ABSENT")
        return digest.hexdigest()

    def visit(path: Path, relative: str) -> None:
        metadata = path.lstat()
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(stat.S_IFMT(metadata.st_mode)).encode())
        digest.update(b"\0")
        digest.update(str(stat.S_IMODE(metadata.st_mode)).encode())
        digest.update(b"\0")
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif stat.S_ISREG(metadata.st_mode):
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    digest.update(chunk)
        elif stat.S_ISDIR(metadata.st_mode):
            for child in sorted(path.iterdir(), key=lambda item: item.name):
                visit(child, f"{relative}/{child.name}")

    visit(root, root.name)
    return digest.hexdigest()


def _replace_for_recovery(source: Path, target: Path) -> None:
    """Treat a post-syscall BaseException as success when disk proves the move."""

    try:
        os.replace(source, target)
    except BaseException:
        if target.exists() and not source.exists():
            return
        raise


def _export_context(
    run_dir: Path,
    *,
    host_contract_path: Path,
    tool_contract_path: Path,
) -> tuple[dict[str, Any], TaskContract, str, Path]:
    run_dir = Path(run_dir)
    report_p = run_dir / "report.json"
    if not report_p.is_file():
        raise ToolExportError(f"run 目录缺 report.json:{run_dir}")
    report = json.loads(report_p.read_text(encoding="utf-8"))
    verdict = report.get("verdict")
    if verdict not in _PASS:
        raise ToolExportError(
            f"verdict={verdict!r} 不可导出(只认 gate 的 PASS_*;"
            "FAIL 的证据留在 run 目录,不落用户工具区)")

    tc, tc_digest = TaskContract.load_frozen(tool_contract_path, require_sidecar=True)
    if tc.task_family != "LOCAL-TOOL" or tc.tool is None:
        raise ToolExportError(f"{tc.task_id}: 不是 LOCAL-TOOL 契约")
    _tool_path(Path("."), tc.tool.name)
    try:
        validate_tool_task_id(tc.tool.name, tc.task_id)
    except ToolPathError as exc:
        raise ToolExportError(str(exc)) from exc
    if report.get("task_id") != tc.task_id:
        raise ToolExportError(
            f"run 属 {report.get('task_id')!r},契约是 {tc.task_id!r} —— 不许错配")

    import yaml
    host_doc = yaml.safe_load(Path(host_contract_path).read_text(encoding="utf-8"))
    host_copy = Path(host_doc["host"]["copy_path"])
    if not host_copy.is_dir():
        raise ToolExportError(f"骨架副本不存在:{host_copy}")
    return report, tc, tc_digest, host_copy


def _materialize_verified_tool(
    run_dir: Path,
    *,
    report: dict[str, Any],
    contract: TaskContract,
    contract_digest: str,
    host_copy: Path,
    dest: Path,
) -> Path:
    """Build a complete candidate at an absent path; clean it on failure."""

    tool = contract.tool
    if tool is None:      # _export_context 已把守;此处防绕过直调
        raise ToolExportError(f"{contract.task_id}: 契约缺 tool 段,不可导出")
    if dest.exists():
        raise ToolExportError(f"候选导出目标已存在:{dest}")
    try:
        # 交付树 = 骨架 + 冻结补丁(确定性重建;.venv 等可再生件天然不在)
        shutil.copytree(host_copy, dest)
        venv_identity = _tree_identity_no_follow(dest / ".venv")
        patch = Path(run_dir) / "adaptation.patch"
        patch_bytes = patch.read_bytes() if patch.is_file() else b""
        if patch_bytes.strip():
            # cwd=dest 下必须给绝对路径 —— 相对 run_dir 的路径在这里失效
            got = subprocess.run(
                ["git", "apply", str(patch.resolve())],
                cwd=dest,
                capture_output=True,
                text=True,
            )
            if got.returncode != 0:
                raise ToolExportError(f"补丁重放失败:{got.stderr[:400]}")
        if _tree_identity_no_follow(dest / ".venv") != venv_identity:
            raise ToolExportError("adaptation.patch 不得创建或修改候选工具的 .venv")

        # Never follow an adaptation-created link while reading/writing a
        # manifest, evidence file, launcher, build script, or MCP target.
        _require_safe_package_tree(dest)

        # manifest verification 填充(agent 侧必须是 null —— 越权声明拦截)
        mf_p = dest / "tool.json"
        manifest = json.loads(mf_p.read_text(encoding="utf-8"))
        if manifest.get("verification") is not None:
            raise ToolExportError(
                "交付的 tool.json 已带非 null verification —— agent 越权声明,拒导出"
            )
        verdict = report["verdict"]
        manifest["verification"] = {
            "verdict": report.get("verdict_public") or verdict,
            "internal_verdict": verdict,
            "run_id": report.get("run_id"),
            "contract_sha256": contract_digest,
            "gate_report": "evidence/report.json",
            "replay_mode": "clean_adoption",
        }
        mf_p.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )

        # evidence/(EXPORT_ONLY:oracle/held-out 不在 run_dir 交付面,天然不进包)
        ev = dest / "evidence"
        ev.mkdir()
        for name in ("report.json", "adaptation_manifest.json", "adaptation.patch"):
            src = Path(run_dir) / name
            if src.is_file():
                shutil.copy2(src, ev / name)
        ver_dir = Path(run_dir) / "verification"
        if ver_dir.is_dir():
            shutil.copytree(ver_dir, ev / "verification")
        (ev / "provenance.json").write_text(
            json.dumps(
                {
                    "tool": tool.name,
                    "task_id": contract.task_id,
                    "run_id": report.get("run_id"),
                    "source": {
                        "url": contract.source_repo.url,
                        "resolved_commit": contract.source_repo.resolved_commit,
                        "license": contract.source_repo.license,
                        "distribution": contract.source_repo.distribution,
                    },
                    "tool_contract_sha256": contract_digest,
                    "final_trace_sha256": report.get("final_trace_sha256"),
                },
                ensure_ascii=False,
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )

        for rel in (f"bin/{tool.name}", "build.sh"):
            path = dest / rel
            if path.is_file():
                path.chmod(0o755)
        _require_safe_package_tree(dest)
        return dest
    except BaseException:
        if dest.exists():
            shutil.rmtree(dest)
        raise


def export_verified_tool(
    run_dir: Path,
    *,
    host_contract_path: Path,
    tool_contract_path: Path,
    dest_root: Path,
) -> Path:
    """Export a first installation; an existing command is never overwritten."""

    report, contract, digest, host_copy = _export_context(
        run_dir,
        host_contract_path=host_contract_path,
        tool_contract_path=tool_contract_path,
    )
    tool = contract.tool
    if tool is None:      # _export_context 已把守;此处防绕过直调
        raise ToolExportError(f"{contract.task_id}: 契约缺 tool 段,不可导出")
    dest_root = Path(dest_root).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    with tool_install_lock(dest_root):
        dest = _tool_path(dest_root, tool.name)
        if dest.exists():
            raise ToolExportError(f"导出目标已存在,拒绝覆盖:{dest}")
        stage_root = Path(
            tempfile.mkdtemp(prefix=".repoproof-export-", dir=dest_root)
        )
        candidate = _tool_path(stage_root, tool.name)
        try:
            _materialize_verified_tool(
                run_dir,
                report=report,
                contract=contract,
                contract_digest=digest,
                host_copy=host_copy,
                dest=candidate,
            )
            os.replace(candidate, dest)
        except BaseException:
            if dest.exists() and not candidate.exists():
                _replace_for_recovery(dest, candidate)
            shutil.rmtree(stage_root, ignore_errors=True)
            raise
        shutil.rmtree(stage_root, ignore_errors=True)
        return dest


_TASK_VERSION = re.compile(r"^(?P<lineage>.+)-v(?P<version>[1-9][0-9]*)$")


def _reject_json_constant(constant: str) -> None:
    raise ValueError(f"non-standard JSON constant: {constant}")


def _strict_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _read_json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw,
            parse_constant=_reject_json_constant,
            parse_float=_strict_json_float,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise ToolExportError(f"{label} 无法读取:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise ToolExportError(f"{label} 必须为 JSON object:{path}")
    return value, raw


def _registry_entry(dest_root: Path, name: str) -> dict[str, Any] | None:
    try:
        registry = load_registry(dest_root)
    except (OSError, ToolPathError, UnicodeError, ValueError) as exc:
        raise ToolExportError(f"registry 无法严格加载:{exc}") from exc
    return registry["tools"].get(name)


def _registry_commit_matches_install(
    dest_root: Path,
    *,
    tool_name: str,
    task_id: str,
    run_id: Any,
    contract_sha256: str,
    dest: Path,
) -> bool:
    """Detect the narrow case where registry replacement committed before an interrupt."""

    try:
        entry = _registry_entry(dest_root, tool_name)
        registered_path = entry.get("path") if entry is not None else None
        path_matches = bool(
            isinstance(registered_path, str)
            and Path(registered_path).resolve() == dest.resolve()
        )
    except (OSError, ToolExportError, TypeError, ValueError):
        return False
    return bool(
        entry is not None
        and path_matches
        and entry.get("task_id") == task_id
        and entry.get("run_id") == run_id
        and entry.get("contract_sha256") == contract_sha256
    )


def preflight_tool_install(
    dest_root: Path, tool_name: str, task_id: str
) -> dict[str, Any] | None:
    """Validate a first install or strictly newer same-lineage task upgrade.

    This check is read-only and is called before a real model run.  The actual
    installer repeats it while holding the install lock.
    """

    dest_root = Path(dest_root).resolve()
    load_release_decisions(dest_root)  # damaged operational truth fails closed
    dest = _tool_path(dest_root, tool_name)
    registry_entry = _registry_entry(dest_root, tool_name)
    if not dest.exists():
        if registry_entry is not None:
            raise ToolExportError(
                f"registry 已登记 {tool_name!r} 但安装目录不存在，先修复索引"
            )
        return None
    if dest.is_symlink() or not dest.is_dir():
        raise ToolExportError(f"既有安装不是普通目录，拒绝升级:{dest}")
    _require_safe_package_tree(dest)

    manifest, manifest_raw = _read_json_object(dest / "tool.json", label="既有 manifest")
    provenance, provenance_raw = _read_json_object(
        dest / "evidence" / "provenance.json", label="既有 provenance"
    )
    old_task_id = provenance.get("task_id")
    if manifest.get("name") != tool_name or not isinstance(old_task_id, str):
        raise ToolExportError("既有工具 name/task provenance 不完整，拒绝猜测升级")
    try:
        validate_tool_task_id(tool_name, old_task_id)
    except ToolPathError as exc:
        raise ToolExportError(str(exc)) from exc
    if provenance.get("tool") != tool_name:
        raise ToolExportError("既有 provenance tool 与 canonical command 不一致")
    if not is_historical_tool_ready((manifest.get("verification") or {}).get("verdict")):
        raise ToolExportError("既有工具不是历史 VERIFIED_TOOL_READY，拒绝原位升级")
    if registry_entry is None:
        raise ToolExportError(
            f"既有工具 {tool_name!r} 缺 registry 索引；先运行 tool list --scan"
        )
    if old_task_id == task_id:
        raise ToolExportError(f"同一 task_id={task_id!r} 不得覆盖；请生成新版本")

    old_match = _TASK_VERSION.fullmatch(old_task_id)
    new_match = _TASK_VERSION.fullmatch(task_id)
    if old_match is None or new_match is None:
        raise ToolExportError("升级 task_id 必须以 -vN 结尾")
    if old_match["lineage"] != new_match["lineage"]:
        raise ToolExportError(
            f"task 谱系不一致:{old_task_id!r} -> {task_id!r}"
        )
    if int(new_match["version"]) <= int(old_match["version"]):
        raise ToolExportError(f"只允许升级到更高 task version:{old_task_id} -> {task_id}")

    verification = manifest.get("verification") or {}
    registered_task = registry_entry.get("task_id")
    if registered_task != old_task_id:
        raise ToolExportError(
            f"registry task_id={registered_task!r} 与当前包 {old_task_id!r} 冲突"
        )
    registered_path = registry_entry.get("path")
    if not registered_path or Path(registered_path).resolve() != dest.resolve():
        raise ToolExportError("registry path 与当前安装目录冲突")
    package_run_id = verification.get("run_id")
    package_contract = verification.get("contract_sha256")
    if (
        not isinstance(package_run_id, str)
        or not package_run_id
        or provenance.get("run_id") != package_run_id
        or registry_entry.get("run_id") != package_run_id
    ):
        raise ToolExportError("registry/package/provenance run_id 不一致")
    if (
        not isinstance(package_contract, str)
        or not package_contract
        or provenance.get("tool_contract_sha256") != package_contract
        or registry_entry.get("contract_sha256") != package_contract
    ):
        raise ToolExportError("registry/package/provenance contract_sha256 不一致")
    package_verdict = verification.get("verdict")
    if registry_entry.get(
        "historical_verdict", registry_entry.get("verdict")
    ) != package_verdict:
        raise ToolExportError("registry 与 package historical_verdict 不一致")

    mcp_server = dest / "mcp_server.py"
    if mcp_server.is_file():
        try:
            runtime_aware = "RELEASE_LEDGER =" in mcp_server.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ToolExportError(f"无法检查既有 MCP server:{exc}") from exc
        if not runtime_aware:
            raise ToolExportError(
                "LEGACY_MCP_MUST_BE_DETACHED: 先停用/解绑 pre-M5 MCP server，"
                "再移走该文件后重试；RepoProof 不会自动删除它"
            )

    package_identity = hashlib.sha256(
        manifest_raw + b"\0" + provenance_raw
    ).hexdigest()
    return {
        "path": dest,
        "task_id": old_task_id,
        "run_id": verification.get("run_id"),
        "contract_sha256": verification.get("contract_sha256"),
        "package_identity": package_identity,
    }


def _safe_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def install_verified_tool(
    run_dir: Path,
    *,
    host_contract_path: Path,
    tool_contract_path: Path,
    dest_root: Path,
    exported_at: str,
) -> Path:
    """Install or upgrade with fail-closed release state and preserved history."""

    report, contract, digest, host_copy = _export_context(
        run_dir,
        host_contract_path=host_contract_path,
        tool_contract_path=tool_contract_path,
    )
    tool = contract.tool
    if tool is None:      # _export_context 已把守;此处防绕过直调
        raise ToolExportError(f"{contract.task_id}: 契约缺 tool 段,不可导出")
    dest_root = Path(dest_root).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    with tool_install_lock(dest_root):
        current = preflight_tool_install(dest_root, tool.name, contract.task_id)
        stage_root = Path(
            tempfile.mkdtemp(prefix=".repoproof-install-", dir=dest_root)
        )
        candidate = _tool_path(stage_root, tool.name)
        archive: Path | None = None
        old_moved = False
        candidate_live = False
        install_committed = False
        try:
            _materialize_verified_tool(
                run_dir,
                report=report,
                contract=contract,
                contract_digest=digest,
                host_copy=host_copy,
                dest=candidate,
            )
            if current is not None:
                try:
                    archive_parent = ensure_managed_directory(
                        dest_root, ".repoproof-versions", tool.name
                    )
                except ToolPathError as exc:
                    raise ToolExportError(str(exc)) from exc
                archive = (
                    archive_parent
                    / (
                        f"{_safe_component(current['task_id'])}--"
                        f"{current['package_identity'][:16]}"
                    )
                )
                if archive.exists() or archive.is_symlink():
                    raise ToolExportError(f"历史归档位已存在，拒绝覆盖:{archive}")
                provenance_path = candidate / "evidence" / "provenance.json"
                provenance, _raw = _read_json_object(
                    provenance_path, label="候选 provenance"
                )
                provenance["replaces"] = {
                    "task_id": current["task_id"],
                    "run_id": current["run_id"],
                    "contract_sha256": current["contract_sha256"],
                    "archive_path": str(archive.relative_to(dest_root)),
                }
                provenance_path.write_text(
                    json.dumps(provenance, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8",
                )

            manifest_bytes = (candidate / "tool.json").read_bytes()
            ensure_initial_review_decision(
                dest_root,
                tool=tool.name,
                task_id=contract.task_id,
                run_id=report.get("run_id"),
                evidence_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            )

            dest = _tool_path(dest_root, tool.name)
            # archive 恰在 current 非 None 时被赋值;按 archive 判等价,
            # 且类型可证(mypy 不传导 current→archive 的耦合)
            if archive is not None:
                try:
                    os.replace(dest, archive)
                finally:
                    # `os.replace` may have committed immediately before a
                    # catchable BaseException.  Reconcile from the filesystem,
                    # not from whether Python reached the next assignment.
                    old_moved = archive.exists() and not dest.exists()
            try:
                os.replace(candidate, dest)
            finally:
                candidate_live = dest.exists() and not candidate.exists()
            try:
                register_tool(
                    dest_root,
                    dest,
                    run_id=report.get("run_id"),
                    exported_at=exported_at,
                    _lock_held=True,
                    _upgrade_previous=current,
                )
            except BaseException as exc:
                # `_save` uses atomic replacement.  An interrupt can therefore
                # arrive after the new registry is durable but before control
                # returns to us.  In that one case the package + registry are a
                # committed unit and rolling only the package back would create
                # a split-brain installation.
                if _registry_commit_matches_install(
                    dest_root,
                    tool_name=tool.name,
                    task_id=contract.task_id,
                    run_id=report.get("run_id"),
                    contract_sha256=digest,
                    dest=dest,
                ):
                    install_committed = True
                    if isinstance(exc, Exception):
                        raise ToolExportError(
                            "registry 已完成原子提交；安装保持新版本，"
                            f"但提交后的调用被中断:{exc}"
                        ) from exc
                    raise
                # Canonical command must never be left as an unregistered orphan.
                try:
                    try:
                        _replace_for_recovery(dest, candidate)
                    finally:
                        candidate_live = dest.exists() and not candidate.exists()
                    if old_moved and archive is not None:
                        try:
                            _replace_for_recovery(archive, dest)
                        finally:
                            old_moved = archive.exists() and not dest.exists()
                except BaseException as rollback_exc:
                    raise ToolExportError(
                        "registry 结算及自动恢复均失败；运营状态仍 fail closed，"
                        f"请检查 canonical/archive/staging:{rollback_exc}"
                    ) from rollback_exc
                if isinstance(exc, Exception):
                    raise ToolExportError(
                        f"registry 结算失败；旧包已恢复，候选保留在 {candidate}:{exc}"
                    ) from exc
                raise
        except BaseException:
            if not install_committed:
                dest = _tool_path(dest_root, tool.name)
                if candidate_live:
                    try:
                        _replace_for_recovery(dest, candidate)
                    finally:
                        candidate_live = dest.exists() and not candidate.exists()
                if old_moved and archive is not None:
                    try:
                        _replace_for_recovery(archive, dest)
                    finally:
                        old_moved = archive.exists() and not dest.exists()
            if not candidate.exists():
                shutil.rmtree(stage_root, ignore_errors=True)
            raise
        else:
            shutil.rmtree(stage_root, ignore_errors=True)
            return _tool_path(dest_root, tool.name)
