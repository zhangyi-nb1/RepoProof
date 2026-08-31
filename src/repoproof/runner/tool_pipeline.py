"""LOCAL-TOOL 单命令旅程编排(M3-a · RFC-010 §六 M3/方向文档 §7)。

两段式(单命令 ≠ 零交互 —— §7 的形态是"少量关键确认"):

    repoproof tool add   → intake + LLM 起草 → draft 束 + 人的待办清单
                           (人:放样例真值 / 审 statement 与 reference /
                            定工具名 —— 全部 [G1] 人闸职责)
    repoproof tool build → confirm(D+装配+T 闸冻结) → 钉版上游确保 →
                           conformance 选取+物化预检 → wheelhouse 备轮 →
                           fake 彩排(必须 PASS 才许烧真预算) → 真模型 →
                           export + 注册表登记(运营态 REVIEW_REQUIRED)

编排只做**顺序与门**,每步的判定权仍在各自组件(闸门语义零改动);
任何一步失败即停、如实返回该步的结论 —— 编排不吞错、不重试真发。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

from repoproof.adoption.assembly.tool_assembler import next_tool_task_id
from repoproof.adoption.intake.tool_confirm import (
    check_draft_complete,
    confirm_tool_draft,
)
from repoproof.adoption.intake.upstream_conformance import (
    precheck_upstream_conformance,
    reference_upstream_symbols,
    select_upstream_test_nodes,
)
from repoproof.adoption.intake.upstream_pin import (
    normalize_dist_name,
    upstream_version,
)
from repoproof.runner.tool_export import (
    ToolExportError,
    install_verified_tool,
    preflight_tool_install,
)
from repoproof.runner.tool_host_bridge import ToolBridgeError, materialize_tool_task
from repoproof.runner.tool_release import (
    ReleaseLedgerError,
    is_historical_tool_ready,
    operational_status,
)


class PipelineError(RuntimeError):
    """A Product pipeline stop with a stable, user-actionable projection."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "FROZEN_TASK_RESUME_FAILED",
        recommended_action: str | None = None,
        partial_result: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.recommended_action = recommended_action
        self.partial_result = dict(partial_result or {})


def _install_error_projection(exc: BaseException) -> tuple[str, str]:
    """Keep exact install blockers instead of collapsing them to wheelhouse errors."""

    message = str(exc)
    if "LEGACY_MCP_MUST_BE_DETACHED" in message:
        return (
            "LEGACY_MCP_MUST_BE_DETACHED",
            "先在 AI 助手中解绑旧版 MCP server，再把旧 mcp_server.py 移到"
            "可恢复备份目录；随后重试。不要删除旧工具包或改写 release ledger。",
        )
    return (
        "TOOL_INSTALL_PREFLIGHT_FAILED",
        "检查目标工具目录、registry、package identity 与 release ledger 后重试；本次不得进入 Agent repair。",
    )


def tool_build_completed(result: dict, *, rehearsal_only: bool) -> bool:
    """Return whether a CLI build reached its declared completion boundary."""

    if rehearsal_only:
        return result.get("verdict") == "REHEARSAL_PASS_ONLY"
    return bool(result.get("exported") and is_historical_tool_ready(result.get("historical_verdict")))


def _rehearsal_stage(report: dict) -> dict:
    """Project the zero-model positive control as a typed Product stage."""

    stage = {
        "verdict": report.get("verdict"),
        "run_id": report.get("run_id"),
        "gate_reasons": report.get("gate_reasons"),
        "agent_model_call_count": 0,
    }
    if report.get("verdict") == "PASS_ADAPTED":
        return stage

    from repoproof.execution.audit_failure import AuditFailureMetadata

    failure = AuditFailureMetadata(
        failure_owner="HARNESS",
        failure_stage="SEMANTIC_VERIFICATION",
        failure_class="CONTRACT_ORACLE_CONFLICT",
        retry_policy="REVIEW_REQUIRED",
        requires_new_task_version=False,
        recommended_action_code="RESTORE_SEMANTIC_VERIFIER_AND_REVIEW",
        recommended_action=(
            "先检查冻结合同、oracle 与验证 Harness 的一致性；若只是 Harness "
            "实现故障，修复后重跑同一任务；只有合同语义变化时才创建新版本。"
        ),
        product_stop_code="STOP_NEEDS_HUMAN",
    )
    stage.update(failure.as_payload())
    stage["reason_codes"] = ["REHEARSAL_POSITIVE_CONTROL_FAILED"]
    stage["failure_assessment"] = {
        **failure.as_payload(),
        "reason_codes": ["REHEARSAL_POSITIVE_CONTROL_FAILED"],
    }
    return stage


def ensure_pinned_upstream(url: str, commit: str, project_root: Path) -> Path:
    """确保 upstream-cache/upstream-<commit12> 存在且 HEAD 严格等于 pinned。

    优先升格 analysis 浅克隆(HEAD 已对);否则完整 clone + detach。"""
    project_root = Path(project_root)
    dest = project_root / "upstream-cache" / f"upstream-{commit[:12]}"

    def _head(p: Path) -> str:
        r = subprocess.run(["git", "-C", str(p), "rev-parse", "HEAD"], capture_output=True, text=True)
        return r.stdout.strip()

    if dest.is_dir():
        if _head(dest) != commit:
            raise PipelineError(f"钉版树 HEAD 与契约不符:{dest}")
        return dest
    analysis = project_root / "upstream-cache" / "analysis"
    if analysis.is_dir():
        for cand in analysis.iterdir():
            if cand.is_dir() and _head(cand) == commit:
                # The analysis checkout is already the pinned Git tree. Preserve
                # tracked symlinks as symlinks when promoting it; dereferencing a
                # link changes the worktree type and makes the freshly promoted
                # checkout fail its own provenance-integrity check.
                shutil.copytree(cand, dest, symlinks=True)
                return dest
    r = subprocess.run(["git", "clone", "--quiet", url, str(dest)], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise PipelineError(f"clone 失败:{r.stderr[-300:]}")
    r = subprocess.run(["git", "-C", str(dest), "checkout", "-q", "--detach", commit], capture_output=True, text=True)
    if r.returncode != 0 or _head(dest) != commit:
        raise PipelineError(f"checkout {commit[:12]} 失败:{r.stderr[-200:]}")
    return dest


def _reference_pins(project_root: Path, task_id: str) -> list[str]:
    lock = Path(project_root) / "controls" / task_id / "reference" / "requirements.lock.txt"
    if not lock.is_file():
        return []
    return [
        ln.strip()
        for ln in lock.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def resolve_upstream_pins(
    project_root: Path,
    task_id: str,
    *,
    distribution: str,
    upstream_dir: Path,
    requested_revision: str = "",
    resolved_commit: str = "",
) -> list[str]:
    """备轮用的 pin 集合 —— **必须含上游本体**,否则当场拒发。

    `reference.lock.txt` 一旦缺席，旧路径中的 `_reference_pins`
    会**静默返回空** ——
    wheelhouse 只装 pytest 那套,会话里根本没有上游,于是每条能力测试都
    炸 `ModuleNotFoundError`,再被包装成 `DEPENDENCY_ERROR` +
    `REGRESSION_FAILURE`,在**三轮修复之后**才浮出来,离病因十万八千里。
    "可选"是假的:不写就必崩。

    两件事:①锁文件缺上游时,从**钉版上游树自己**声明的版本派生
    `dist==version`(陷阱消灭);②派生不出来就抛错,绝不建一个注定装不上
    上游的 wheelhouse(静默降级 → 当场拒发)。
    """
    pins = _reference_pins(project_root, task_id)
    want = normalize_dist_name(distribution)
    if not want:
        return pins
    if any(normalize_dist_name(re.split(r"[=<>!~\[]", p, maxsplit=1)[0]) == want for p in pins):
        return pins
    version = upstream_version(
        upstream_dir,
        distribution=distribution,
        requested_revision=requested_revision,
        resolved_commit=resolved_commit,
    )
    if not version:
        raise PipelineError(
            f"备轮缺上游 {distribution!r}:controls/{task_id}/reference/"
            "requirements.lock.txt 没有它,钉版树里也读不出声明版本。"
            f"请在 draft 束的 reference.lock.txt 写上 `{distribution}==<版本>`"
            " —— 没有它,会话里 import 不到上游,所有能力测试都会以 "
            "ModuleNotFoundError 失败。"
        )
    return [*pins, f"{distribution}=={version}"]


def _build_preflight_venv(task_dir: Path, pins: list[str]) -> Path:
    """conformance 预检解释器:一次性 venv,装 reference 锁定集(联网)。"""
    venv = task_dir / "_preflight_venv"
    subprocess.run(["python3", "-m", "venv", str(venv)], check=True, capture_output=True)
    py = venv / "bin" / "python"
    subprocess.run(
        [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "pytest", *pins],
        check=True,
        capture_output=True,
        timeout=600,
    )
    return py


def _stage_workspace_wheelhouse(
    *, host_contract_path: Path, tool_contract_path: Path, wheelhouse: Path
) -> dict[str, object] | None:
    """Copy the frozen offline wheel set into a v4 delivery package skeleton.

    The build Harness may use an external wheelhouse, but an exported workspace
    must remain rebuildable after that Harness tree disappears.  Only regular
    wheel files are accepted, and the destination is the immutable host copy
    from which clean replay and export are reconstructed.
    """
    tool_doc = yaml.safe_load(Path(tool_contract_path).read_text(encoding="utf-8")) or {}
    tool = tool_doc.get("tool") or {}
    if tool.get("delivery_profile_id") != "workspace_bundle_v1":
        return None
    host_doc = yaml.safe_load(Path(host_contract_path).read_text(encoding="utf-8")) or {}
    host_copy = Path(str((host_doc.get("host") or {}).get("copy_path") or ""))
    if host_copy.is_symlink() or not host_copy.is_dir():
        raise PipelineError("workspace export host copy is missing or unsafe")
    source = Path(wheelhouse)
    if source.is_symlink() or not source.is_dir():
        raise PipelineError("workspace wheelhouse is missing or unsafe")
    wheels = sorted(source.iterdir(), key=lambda item: item.name)
    if not wheels:
        raise PipelineError("workspace wheelhouse is empty")
    for item in wheels:
        if item.is_symlink() or not item.is_file() or item.suffix != ".whl":
            raise PipelineError(f"workspace wheelhouse contains a non-wheel or unsafe path:{item.name}")
    destination = host_copy / "vendor" / "wheels"
    if destination.is_symlink():
        raise PipelineError("workspace package-local wheelhouse is a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    for existing in destination.iterdir():
        if existing.name == ".gitkeep" and existing.is_file():
            existing.unlink()
            continue
        raise PipelineError(f"workspace package-local wheelhouse is not pristine:{existing.name}")
    for item in wheels:
        shutil.copy2(item, destination / item.name)
    return {
        "path": str(destination),
        "wheel_count": len(wheels),
        "self_contained": True,
    }


def _consume_prefrozen_wheelhouse(
    *,
    draft_archive: Path,
    destination: Path,
) -> dict:
    """Copy a preregistered wheel set after exact manifest verification.

    Re-resolving equivalent package versions from an index does not preserve
    the bytes that a qualification protocol preregistered.  When a draft
    explicitly carries frozen wheels, this boundary consumes those exact
    regular files or stops before Agent execution.
    """

    from repoproof.domain.models import AdmissionError
    from repoproof.harness.wheelhouse import verify_wheelhouse

    archive = Path(draft_archive)
    source = archive / "wheelhouse"
    manifest_path = archive / "wheelhouse_manifest.json"
    if source.is_symlink() or not source.is_dir():
        raise PipelineError(
            "预冻结 wheelhouse 缺失或不是普通目录",
            reason_code="PREFROZEN_WHEELHOUSE_INVALID",
        )
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise PipelineError(
            "预冻结 wheelhouse manifest 缺失或不是普通文件",
            reason_code="PREFROZEN_WHEELHOUSE_MANIFEST_INVALID",
        )
    try:
        if manifest_path.stat().st_size > 1024 * 1024:
            raise ValueError("manifest too large")
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        if set(document) != {"root", "wheels"}:
            raise ValueError("manifest fields differ")
        expected_root = str(document["root"])
        expected_wheels = document["wheels"]
        if (
            re.fullmatch(r"[0-9a-f]{64}", expected_root) is None
            or not isinstance(expected_wheels, dict)
            or not expected_wheels
        ):
            raise ValueError("manifest identity invalid")
        for name, digest in expected_wheels.items():
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or not name.endswith(".whl")
                or not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            ):
                raise ValueError("manifest wheel entry invalid")
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise PipelineError(
            "预冻结 wheelhouse manifest 无效",
            reason_code="PREFROZEN_WHEELHOUSE_MANIFEST_INVALID",
        ) from exc

    entries = sorted(source.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise PipelineError(
            "预冻结 wheelhouse 含非普通文件",
            reason_code="PREFROZEN_WHEELHOUSE_INVALID",
        )
    if {path.name for path in entries} != set(expected_wheels):
        raise PipelineError(
            "预冻结 wheelhouse 文件集合与 manifest 不一致",
            reason_code="PREFROZEN_WHEELHOUSE_IDENTITY_MISMATCH",
        )
    try:
        verified = verify_wheelhouse(
            source,
            expected_wheels=expected_wheels,
            expected_root=expected_root,
        )
    except AdmissionError as exc:
        raise PipelineError(
            "预冻结 wheelhouse 字节身份与 manifest 不一致",
            reason_code="PREFROZEN_WHEELHOUSE_IDENTITY_MISMATCH",
        ) from exc

    destination = Path(destination)
    if destination.exists() and (
        destination.is_symlink()
        or not destination.is_dir()
        or any(destination.iterdir())
    ):
        raise PipelineError(
            "执行 wheelhouse 目标不是安全空目录",
            reason_code="PREFROZEN_WHEELHOUSE_DESTINATION_UNSAFE",
        )
    destination.mkdir(parents=True, exist_ok=True)
    for source_wheel in entries:
        target = destination / source_wheel.name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(target, flags, 0o600)
        except OSError as exc:
            raise PipelineError(
                "无法原子落位预冻结 wheel",
                reason_code="PREFROZEN_WHEELHOUSE_DESTINATION_UNSAFE",
            ) from exc
        try:
            with source_wheel.open("rb") as reader, os.fdopen(fd, "wb") as writer:
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
        except Exception:
            target.unlink(missing_ok=True)
            raise
    try:
        return verify_wheelhouse(
            destination,
            expected_wheels=verified["wheels"],
            expected_root=verified["root"],
        )
    except AdmissionError as exc:
        raise PipelineError(
            "预冻结 wheelhouse 落位后身份漂移",
            reason_code="PREFROZEN_WHEELHOUSE_IDENTITY_MISMATCH",
        ) from exc


def _record_workspace_repair_incidents(
    *,
    project_root: Path,
    task_id: str,
    run_id: str,
) -> list[str]:
    """Append one public-only incident for every failing workspace Agent round."""

    import json

    from repoproof.persistence.product_incidents import (
        IncidentDisposition,
        IncidentOwner,
        ProductIncidentV1,
        public_incident_fingerprint,
        write_product_incident,
    )
    from repoproof.persistence.qualification_records import (
        qualification_framework_tree_sha256,
    )

    contract_path = Path(project_root) / "contracts" / f"{task_id}.yaml"
    document = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
    if ((document.get("tool") or {}).get("delivery_profile_id")) != "workspace_bundle_v1":
        return []
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise PipelineError("workspace run did not publish a safe run_id for incidents")
    commit = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    framework_tree = qualification_framework_tree_sha256(
        Path(project_root) / "src" / "repoproof"
    )
    repair_root = Path(project_root) / "runs" / run_id / "repair"
    written: list[str] = []
    if repair_root.is_symlink() or not repair_root.is_dir():
        return written
    owner_map = {
        "AGENT": "AGENT_ADAPTER",
        "AGENT_ADAPTER": "AGENT_ADAPTER",
        "USER": "USER_INPUT",
        "USER_INPUT": "USER_INPUT",
        "CONTRACT": "CONTRACT",
        "HARNESS": "HARNESS",
        "UPSTREAM": "UPSTREAM",
        "EXTERNAL": "EXTERNAL",
    }
    for path in sorted(repair_root.glob("round-*/record.json")):
        if path.is_symlink() or not path.is_file():
            raise PipelineError("workspace repair incident source is unsafe")
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict):
            raise PipelineError("workspace repair incident source is invalid")
        public_failed = int(row.get("public_failed") or 0)
        policy_violations = int(row.get("policy_violations") or 0)
        reason_codes = [
            str(item)
            for item in row.get("reason_codes") or []
            if str(item).strip()
        ]
        adapter_diff_present = bool(row.get("adapter_diff_present", True))
        if not adapter_diff_present:
            reason_codes.append("NO_ADAPTER_DIFF")
        if public_failed <= 0 and policy_violations <= 0 and not reason_codes:
            continue
        packets = row.get("failure_packets")
        packet_rows = packets if isinstance(packets, list) else []
        public_nodes = tuple(
            sorted(
                {
                    str(packet.get("type") or "PUBLIC_FAILURE")[:160]
                    for packet in packet_rows
                    if isinstance(packet, dict)
                }
            )
        )
        if not public_nodes and public_failed > 0:
            public_nodes = ("PUBLIC_FAILURE",)
        if not public_nodes and policy_violations > 0:
            public_nodes = ("POLICY_VIOLATION",)
        from typing import cast

        owner = cast(
            IncidentOwner,
            owner_map.get(
                str(row.get("failure_owner") or "AGENT_ADAPTER"),
                "HARNESS",
            ),
        )
        repair_eligible = bool(
            owner == "AGENT_ADAPTER"
            and adapter_diff_present
            and public_nodes
            and str(row.get("recommended_action") or "REPAIR") == "REPAIR"
        )
        if repair_eligible:
            disposition = "REPAIR_AGENT"
        elif owner == "CONTRACT":
            disposition = "NEW_TASK_VERSION"
        elif owner in {"HARNESS", "UPSTREAM", "EXTERNAL"}:
            disposition = "RETRY_INFRASTRUCTURE"
        elif owner == "USER_INPUT":
            disposition = "STOP_NEEDS_HUMAN"
        else:
            disposition = "STOP_NEEDS_HUMAN"
        disposition = cast(IncidentDisposition, disposition)
        fingerprint = str(row.get("public_failure_fingerprint") or "")
        if re.fullmatch(r"[0-9a-f]{16}", fingerprint) is None:
            fingerprint = public_incident_fingerprint(
                stage="AGENT_ADAPTER",
                owner=owner,
                reason_codes=reason_codes,
                public_failed_nodes=public_nodes,
            )
        round_index = int(row.get("round_index") or 0)
        identity = hashlib.sha256(
            f"{run_id}\0{round_index}".encode()
        ).hexdigest()[:24]
        incident = ProductIncidentV1(
            incident_id=f"incident-{identity}",
            framework_git_commit=commit,
            framework_tree_sha256=framework_tree,
            profile_id="workspace_bundle_v1",
            task_version=task_id,
            stage="AGENT_ADAPTER",
            owner=owner,
            normalized_fingerprint=fingerprint,
            public_failed_nodes=public_nodes,
            reason_codes=tuple(sorted(set(reason_codes))),
            artifact_tree_diff={
                "changed_file_count": len(row.get("changed_files") or []),
                "diff_lines": int(row.get("diff_lines") or 0),
                "public_failed": public_failed,
                "regression_failed": int(row.get("regression_failed") or 0),
                "policy_violations": policy_violations,
            },
            agent_diff_present=adapter_diff_present,
            repair_eligible=repair_eligible,
            disposition=disposition,
            created_at=datetime.datetime.now(datetime.UTC).isoformat().replace(
                "+00:00", "Z"
            ),
        )
        written.append(
            str(
                write_product_incident(
                    Path(project_root) / "runs" / "product-incidents",
                    incident,
                )
            )
        )
    return written


def tool_build_real_from_frozen(
    task_id: str,
    project_root: Path,
    *,
    dest_root: Path,
    agent_backend: str = "mini-swe",
    batch: str = "EXPLORATORY_UNPREREGISTERED",
    rehearsal_only: bool = False,
    draft_dir: Path | None = None,
    bench_root: Path | None = None,
) -> dict:
    """Resume a frozen task at rehearsal or real build without re-freezing it.

    为什么必须有(2026-08-28 用户实测):`tool_build` 在**彩排之前**就把
    草稿 `shutil.move` 进了 `tool_tasks/_drafts`(冻结即消耗,这本身是对的
    —— 题面已冻结,草稿不该再被编辑)。但 UI 只有"从草稿构建"一个入口,
    于是**彩排通过之后无路可走**:回到构建页只会看到"草稿目录不存在",
    用户只能重建一份新草稿再来 —— 那会冻出 v2、v3、v4…(用户手上那串
    版本号就是这么来的),而且每次都要重新准备样例。

    "先彩排、通过再真发"是对的流程;缺的是它的下半程。这里补上:
    题面不重冻(冻结是不可改写的),直接对同一份合同跑真发 → 独立验证
    → 导出 + 注册,与 `tool_build` 的后半段同一条路径。
    """
    project_root = Path(project_root)
    # 两份合同别混:`contracts/<task>.yaml` 是**工具合同**(TaskContract),
    # 而 run_host_guided_cli 要的是物化出来的**宿主合同**
    # (`tool_tasks/<task>/contract.yaml`,HostContract schema)。
    # 2026-08-28 实测:传错那份会在加载时抛一串 pydantic
    # "Field required: budgets.max_rounds / acceptance.hidden_oracle_command",
    # 看起来像题面缺字段,其实是拿错了文件。
    tool_contract = project_root / "contracts" / f"{task_id}.yaml"
    host_contract = project_root / "tool_tasks" / task_id / "contract.yaml"
    if not tool_contract.is_file():
        raise PipelineError(f"找不到已冻结的任务合同:{tool_contract}")
    if not host_contract.is_file():
        if draft_dir is not None and (Path(draft_dir) / "draft.yaml").is_file():
            return tool_build(
                Path(draft_dir),
                project_root,
                bench_root=(Path(bench_root) if bench_root is not None else Path("~/RepoProofBench").expanduser()),
                dest_root=dest_root,
                run_real=not rehearsal_only,
                agent_backend=agent_backend,
                batch=batch,
                resume_task_id=task_id,
            )
        raise PipelineError(
            f"找不到物化的宿主合同:{host_contract} —— 该任务尚未物化(或 tool_tasks 目录被清理过),无法续跑真发。"
        )
    stages: dict = {
        "resumed_from_frozen": {
            "task_id": task_id,
            "tool_contract": str(tool_contract),
            "host_contract": str(host_contract),
        }
    }

    # Resuming reaches the same install boundary as the original build.  Run
    # the read-only install preflight before spending real-model budget;
    # otherwise a legacy MCP file or damaged registry is discovered only
    # after an otherwise verified Agent run.
    if not rehearsal_only:
        try:
            tool_doc = yaml.safe_load(tool_contract.read_text(encoding="utf-8")) or {}
            tool_name = str(((tool_doc.get("tool") or {}).get("name")) or "").strip()
            if not tool_name:
                raise ToolExportError("冻结工具合同缺少 tool.name")
            current = preflight_tool_install(Path(dest_root), tool_name, task_id)
        except (
            ToolExportError,
            ReleaseLedgerError,
            OSError,
            TypeError,
            ValueError,
            yaml.YAMLError,
        ) as exc:
            reason_code, action = _install_error_projection(exc)
            stages["install_preflight"] = {
                "ok": False,
                "error": str(exc),
                "reason_code": reason_code,
            }
            raise PipelineError(
                f"工具安装预检失败:{exc}",
                reason_code=reason_code,
                recommended_action=action,
                partial_result={
                    "task_id": task_id,
                    "stages": stages,
                    "verdict": "BLOCKED",
                    "exported": None,
                },
            ) from exc
        stages["install_preflight"] = {
            "ok": True,
            "mode": "upgrade" if current is not None else "first_install",
            "previous_task_id": current.get("task_id") if current else None,
        }

    from repoproof.runner.product_preflight import run_product_preflight

    try:
        host_doc = yaml.safe_load(host_contract.read_text(encoding="utf-8")) or {}
        wheelhouse = Path(str((host_doc.get("host") or {}).get("wheelhouse_path") or ""))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        raise PipelineError(f"无法读取冻结宿主合同的 wheelhouse：{exc}") from exc
    preflight = run_product_preflight(
        project_root=project_root,
        task_id=task_id,
        tool_contract_path=tool_contract,
        host_contract_path=host_contract,
        wheelhouse=wheelhouse,
    )
    stages["preflight"] = preflight.model_dump(mode="json")
    if not preflight.ok:
        return {
            "task_id": task_id,
            "stages": stages,
            "verdict": "BLOCKED",
            "exported": None,
        }

    from repoproof.adoption.repair.failure_assessment import (
        assess_report,
        derive_repair_metrics,
    )
    from repoproof.runner.host_guided import run_host_guided_cli

    if rehearsal_only:
        fake = run_host_guided_cli(host_contract, project_root, fake="positive", batch=batch)
        rp = fake.get("report") or {}
        stages["rehearsal"] = _rehearsal_stage(rp)
        verdict = "REHEARSAL_PASS_ONLY" if rp.get("verdict") == "PASS_ADAPTED" else f"REHEARSAL_{rp.get('verdict')}"
        return {
            "task_id": task_id,
            "stages": stages,
            "verdict": verdict,
            "exported": None,
        }

    real = run_host_guided_cli(host_contract, project_root, fake=None, batch=batch, backend=agent_backend)
    if real.get("blocked"):
        stages["real"] = real
        return {"task_id": task_id, "stages": stages, "verdict": "REAL_BLOCKED", "exported": None}
    rp = real.get("report") or {}
    stages["product_incidents"] = {
        "records": _record_workspace_repair_incidents(
            project_root=project_root,
            task_id=task_id,
            run_id=str(rp.get("run_id") or ""),
        )
    }
    metrics = derive_repair_metrics(rp)
    stages["real"] = {
        "verdict": rp.get("verdict"),
        "verdict_public": rp.get("verdict_public"),
        "run_id": rp.get("run_id"),
        "gate_reasons": rp.get("gate_reasons"),
        "repair_metrics": metrics,
        "product_stop_code": metrics["product_stop_code"],
    }
    if rp.get("verdict") not in ("PASS_ADAPTED", "PASS_DIRECT"):
        stages["real"]["failure_assessment"] = assess_report(rp).model_dump()
        return {"task_id": task_id, "stages": stages, "verdict": rp.get("verdict"), "exported": None}

    historical_verdict = rp.get("verdict_public") or rp.get("verdict")
    try:
        dest = install_verified_tool(
            project_root / "runs" / rp["run_id"],
            host_contract_path=host_contract,
            tool_contract_path=tool_contract,
            dest_root=Path(dest_root),
            exported_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except (ToolExportError, ReleaseLedgerError, OSError, ValueError) as exc:
        stages["export"] = {"ok": False, "error": str(exc)}
        reason_code, action = _install_error_projection(exc)
        raise PipelineError(
            f"工具安装结算失败:{exc}",
            reason_code=reason_code,
            recommended_action=action,
            partial_result={
                "task_id": task_id,
                "stages": stages,
                "verdict": historical_verdict,
                "historical_verdict": historical_verdict,
                "exported": None,
            },
        ) from exc
    release_status = operational_status(Path(dest_root), dest.name, task_id=task_id)
    stages["export"] = {
        "dest": str(dest),
        "historical_verdict": historical_verdict,
        "operational_status": release_status,
    }
    return {
        "task_id": task_id,
        "stages": stages,
        "verdict": historical_verdict,
        "historical_verdict": historical_verdict,
        "operational_status": release_status,
        "exported": str(dest),
    }


def rehearsed_tasks(project_root: Path) -> list[dict]:
    """已冻结、彩排过、但**还没导出**的任务 —— 构建页的"待续跑"清单。

    判据全部来自盘上事实:合同存在 + 台账里有该任务的彩排发次
    (`fake-scripted:*`)+ 尚无真发导出。
    """
    import json

    project_root = Path(project_root)
    ledger = project_root / "benchmarks" / "v2" / "runs.jsonl"
    rehearsed: dict[str, dict] = {}
    exported: set[str] = set()
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            tid, model = str(row.get("task_id") or ""), str(row.get("model") or "")
            if not tid.startswith("tool-"):
                continue
            if model.startswith("fake-scripted"):
                rehearsed[tid] = {"task_id": tid, "last_rehearsal": row.get("run_id"), "verdict": row.get("verdict")}
            else:
                exported.add(tid)
    out = [
        v for k, v in rehearsed.items() if k not in exported and (project_root / "contracts" / f"{k}.yaml").is_file()
    ]
    return sorted(out, key=lambda r: str(r["task_id"]), reverse=True)


def tool_build(
    draft_dir: Path,
    project_root: Path,
    *,
    bench_root: Path,
    dest_root: Path,
    run_real: bool = True,
    agent_backend: str = "mini-swe",
    conformance_symbols: list[str] | None = None,
    batch: str = "EXPLORATORY_UNPREREGISTERED",
    setup_commands: list[list[str]] | None = None,  # 测试注入(E2E shim)
    wheelhouse_cmd: list[str] | None = None,  # 测试注入(跳过备轮)
    resume_task_id: str | None = None,
) -> dict:
    """→ {task_id, stages, verdict, historical_verdict,
    operational_status, exported};任一门不过即返回(stages 记录到
    哪一步、为何停)。兼容字段 ``verdict`` 仍表示历史验证结论。
    """
    from repoproof.runner.host_guided import run_host_guided_cli

    if agent_backend not in {"codex-cli", "mini-swe"}:
        raise PipelineError(f"Product Mode 不支持 agent backend={agent_backend!r};可选 codex-cli / mini-swe")

    project_root = Path(project_root)
    draft_dir = Path(draft_dir)
    stages: dict = {}

    draft_path = draft_dir / "draft.yaml"
    draft = yaml.safe_load(draft_path.read_text(encoding="utf-8")) if draft_path.is_file() else None
    predicted_task_id: str | None = None
    if run_real and isinstance(draft, dict):
        # D checks are read-only.  Once they pass, reject an impossible or
        # unsafe install before confirm freezes a new task version, and long
        # before either rehearsal or real-model budget is spent.
        if not check_draft_complete(
            draft,
            draft_dir,
            project_root=project_root,
        ):
            try:
                predicted_task_id = (
                    str(resume_task_id)
                    if resume_task_id is not None
                    else next_tool_task_id(project_root, draft["tool"]["name"])
                )
                current = preflight_tool_install(Path(dest_root), draft["tool"]["name"], predicted_task_id)
            except (ToolExportError, ReleaseLedgerError, OSError, ValueError) as exc:
                stages["install_preflight"] = {"ok": False, "error": str(exc)}
                reason_code, action = _install_error_projection(exc)
                raise PipelineError(
                    f"工具安装预检失败:{exc}",
                    reason_code=reason_code,
                    recommended_action=action,
                    partial_result={
                        "stages": stages,
                        "verdict": "BLOCKED",
                        "exported": None,
                    },
                ) from exc
            stages["install_preflight"] = {
                "ok": True,
                "mode": "upgrade" if current is not None else "first_install",
                "previous_task_id": current.get("task_id") if current else None,
            }

    # 0b) 执行路由(RFC-013):draft 束带已确认 plan.yaml → 按计划路线;
    # 无 plan = 向后兼容缺省 AGENT_ADAPT。DIRECT_WRAP 在此处即执法
    # assert_may_execute(未确认/被改动的计划连装配都不许进)。
    route = "AGENT_ADAPT"
    adapter_src: str | None = None
    plan_obj = None
    plan_path = draft_dir / "plan.yaml"
    if plan_path.is_file():
        from repoproof.adoption.delivery.direct_adapter import (
            compile_direct_adapter,
            derive_adapter_spec,
        )
        from repoproof.adoption.planning.capability_plan import (
            CapabilityPlanV1,
            CapabilityPlanV2,
            assert_may_execute,
            assert_plan_matches_source,
        )

        plan_document = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        plan_type = CapabilityPlanV2 if plan_document.get("schema_version") == 2 else CapabilityPlanV1
        plan_obj = plan_type.model_validate(plan_document)
        assert_may_execute(plan_obj)
        # plan 与 draft 上游身份绑定:拿别的仓/别的版本的计划冒充即拒
        # (外部审计 P0 实证的补丁之二)。
        if isinstance(draft, dict):
            _sr = draft.get("source_repo") or {}
            assert_plan_matches_source(
                plan_obj, url=str(_sr.get("url") or ""), commit=str(_sr.get("resolved_commit") or "")
            )
        route = plan_obj.implementation_route
        if (
            isinstance(draft, dict)
            and ((draft.get("tool") or {}).get("delivery_profile_id")) == "workspace_bundle_v1"
            and route != "AGENT_ADAPT"
        ):
            raise PipelineError("workspace composition must use the frozen AGENT_ADAPT route")
        if route == "DIRECT_WRAP":
            spec = derive_adapter_spec(plan_obj)
            adapter_src = compile_direct_adapter(spec)
            stages["route"] = {
                "route": route,
                "locator": spec.locator,
                "agent_invoked": False,
                "plan_sha256": plan_obj.plan_sha256,
            }
        else:
            stages["route"] = {"route": route, "agent_invoked": True, "plan_sha256": plan_obj.plan_sha256}

    # 1) 人闸后的确认:D 闸 → 装配 → T 闸 → 冻结。若上一次在冻结后、
    # 物化前因 Harness 预检停止，只允许对身份完全一致的冻结合同续跑；
    # 不删除、不重冻，也不分配 v2。
    if resume_task_id is None:
        try:
            info = confirm_tool_draft(draft_dir, project_root)
        except ValueError as exc:
            raise PipelineError(f"任务版本谱系或草稿装配无效:{exc}") from exc
        task_id = info["task_id"]
    else:
        task_id = str(resume_task_id).strip()
        if re.fullmatch(r"tool-[a-z0-9][a-z0-9-]*-v[1-9][0-9]*", task_id) is None:
            raise PipelineError("预物化续跑 task_id 非法")
        if not isinstance(draft, dict):
            raise PipelineError("预物化续跑缺少可验证的草稿合同")
        frozen_path = project_root / "contracts" / f"{task_id}.yaml"
        sidecar = frozen_path.with_suffix(frozen_path.suffix + ".sha256")
        if not frozen_path.is_file() or not sidecar.is_file():
            raise PipelineError("预物化续跑缺少冻结合同或哈希 sidecar")
        frozen = yaml.safe_load(frozen_path.read_text(encoding="utf-8")) or {}
        if not isinstance(frozen, dict):
            raise PipelineError("预物化续跑冻结合同不是对象")
        frozen_source = frozen.get("source_repo") or {}
        draft_source = draft.get("source_repo") or {}
        frozen_intent = (frozen.get("capability") or {}).get("intent_contract") or {}
        draft_intent = draft.get("_intent_contract") or {}
        identity_matches = (
            frozen.get("task_id") == task_id
            and ((frozen.get("tool") or {}).get("name")) == ((draft.get("tool") or {}).get("name"))
            and all(
                frozen_source.get(key) == draft_source.get(key)
                for key in (
                    "url",
                    "resolved_commit",
                    "distribution",
                    "import_module",
                )
            )
            and ((frozen_intent.get("confirmation") or {}).get("semantics_sha256"))
            == ((draft_intent.get("confirmation") or {}).get("semantics_sha256"))
        )
        if not identity_matches:
            raise PipelineError("冻结合同与预物化草稿身份不一致；拒绝续跑或重写旧版本")
        example_file = (
            draft_dir / "workspace_examples.yaml"
            if ((draft.get("tool") or {}).get("delivery_profile_id")) == "workspace_bundle_v1"
            else draft_dir / "examples.yaml"
        )
        examples_doc = yaml.safe_load(example_file.read_text(encoding="utf-8")) or {}
        total_examples = len(examples_doc.get("examples") or [])
        info = {
            "task_id": task_id,
            "public": max(0, total_examples - 1),
            "held": 1 if total_examples else 0,
        }
        stages["resumed_pre_materialization"] = {
            "task_id": task_id,
            "frozen_contract": str(frozen_path),
            "identity_matched": True,
            "contract_rewritten": False,
        }
    if predicted_task_id is not None and task_id != predicted_task_id:
        raise PipelineError(f"安装预检 task_id={predicted_task_id} 与冻结结果 {task_id} 分叉")
    stages["confirm"] = {"task_id": task_id, "public": info["public"], "held": info["held"]}

    frozen_reference_path = project_root / "controls" / task_id / "reference" / "impl.py"
    try:
        reference_source = frozen_reference_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PipelineError("冻结任务缺少可读取的 reference implementation") from exc

    if not isinstance(draft, dict):
        draft = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
    sr = draft["source_repo"]

    # 2) 钉版上游 + conformance 选取(确定性)。选择依据来自已审阅
    # reference 的实际 upstream call AST，不从用户措辞抽词，也不维护
    # 仓库/格式别名表。
    up = ensure_pinned_upstream(sr["url"], sr["resolved_commit"], project_root)
    symbols = (
        list(conformance_symbols)
        if conformance_symbols is not None
        else reference_upstream_symbols(
            reference_source,
            import_module=str(sr["import_module"]),
        )
    )
    selected = select_upstream_test_nodes(up, symbols)
    stages["conformance_selected"] = selected
    selection_basis = {
        "schema_version": 1,
        "kind": "REFERENCE_UPSTREAM_SYMBOLS",
        "reference_sha256": hashlib.sha256(reference_source.encode("utf-8")).hexdigest(),
        "import_module": str(sr["import_module"]),
        "symbols": symbols,
    }
    stages["conformance_selection_basis"] = selection_basis

    # 2b) DIRECT_WRAP:受信模板 adapter + 确定 lock **在装配骨架里落位**
    # (materialize 之前 —— 任务包/bench 副本由骨架拷出)。S0 即完整交付,
    # agent 零 diff,completion gate 的既有 PASS_DIRECT 语义自然成立。
    pins = resolve_upstream_pins(
        project_root,
        task_id,
        distribution=sr["distribution"],
        upstream_dir=up,
        requested_revision=str(sr.get("revision") or ""),
        resolved_commit=str(sr.get("resolved_commit") or ""),
    )
    if route == "DIRECT_WRAP":
        skel = Path(project_root) / "fixtures" / f"tool_skeleton_{draft['tool']['name']}"
        pkg = str(draft["tool"]["name"]).replace("-", "_")
        impl_p = skel / "src" / pkg / "impl.py"
        if not impl_p.is_file():
            raise PipelineError(f"DIRECT_WRAP 找不到骨架能力位:{impl_p}")
        if adapter_src is None:  # route=DIRECT_WRAP 时路由段必已编译;防失配
            raise PipelineError("DIRECT_WRAP 路由却没有已编译的适配器源 —— 路由段状态失配")
        impl_p.write_text(adapter_src, encoding="utf-8")
        (skel / "requirements.lock.txt").write_text(
            ("\n".join(pins) + "\n") if pins else "# DIRECT_WRAP:上游经会话环境提供,无第三方 pins\n", encoding="utf-8"
        )
    task_dir = Path(project_root) / "tool_tasks" / task_id
    if task_dir.exists() or (Path(bench_root) / task_id).exists():
        raise PipelineError(f"物化目标已存在:{task_id}(改题面请先重出 draft → 新版本号)")
    conf_py = None
    conf_record = {
        "selected": selected,
        "status": "SKIPPED",
        "selection_basis": selection_basis,
    }
    if selected and pins:
        tmp_task = Path(project_root) / "tool_tasks"
        tmp_task.mkdir(exist_ok=True)
        conf_py = _build_preflight_venv(tmp_task / f"_{task_id}_pf", pins)
        try:
            conf_record = precheck_upstream_conformance(
                up,
                selected,
                conf_py,
            )
            conf_record["selection_basis"] = selection_basis
            stages["conformance_preflight"] = conf_record
        except RuntimeError as exc:
            stages["conformance_preflight"] = {
                "ok": False,
                "error": str(exc),
                "selected": selected,
                "agent_model_call_count": 0,
            }
            return {
                "task_id": task_id,
                "stages": stages,
                "verdict": "BLOCKED",
                "exported": None,
                "failure_owner": "HARNESS",
                "reason_codes": ["UPSTREAM_CONFORMANCE_ENVIRONMENT"],
                "product_stop_code": "STOP_HARNESS_OR_EXTERNAL",
                "recommended_action": ("检查钉版上游的测试依赖或所选公开测试节点；该环境故障不得进入 Agent repair。"),
            }
        finally:
            shutil.rmtree(conf_py.parents[1], ignore_errors=True)
            conf_py = None
    try:
        contract = materialize_tool_task(
            project_root,
            Path(project_root) / "contracts" / f"{task_id}.yaml",
            out_root=Path(project_root) / "tool_tasks",
            host_copy_root=Path(bench_root),
            setup_commands=setup_commands,
            upstream_conformance=selected,
            upstream_conformance_record=conf_record,
        )
    except ToolBridgeError as e:
        stages["materialize"] = {"ok": False, "error": str(e)}
        return {
            "task_id": task_id,
            "stages": stages,
            "verdict": "BLOCKED",
            "exported": None,
            "failure_owner": "HARNESS",
            "reason_codes": ["TASK_MATERIALIZATION_FAILED"],
            "product_stop_code": "STOP_HARNESS_OR_EXTERNAL",
            "recommended_action": ("检查冻结任务骨架、控制组和物化目标；该故障不得进入 Agent repair。"),
        }
    stages["materialize"] = {"ok": True, "contract": str(contract)}

    # 3b) draft 束归档进任务区(真值留痕;移出 H9-a 扫描面 —— 束里的
    # 样例/期望与 oracle 逐字节同,留在 /tmp 真发必被残留闸拒,按设计)。
    # 时机在 materialize 成功之后:任何更早失败,束留原位供人改后重跑。
    archive = project_root / "tool_tasks" / "_drafts" / task_id
    if archive.exists():
        raise PipelineError(f"draft 归档位已存在:{archive}")
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(draft_dir), str(archive))
    stages["draft_archived"] = str(archive)

    # 4) wheelhouse 备轮(reference 锁定集 + 测量工具链)
    wheelhouse = Path(bench_root) / task_id / "wheelhouse"
    prefrozen_present = (
        (archive / "wheelhouse").exists()
        or (archive / "wheelhouse_manifest.json").exists()
    )
    prefrozen_manifest: dict | None = None
    if wheelhouse_cmd is None and prefrozen_present:
        prefrozen_manifest = _consume_prefrozen_wheelhouse(
            draft_archive=archive,
            destination=wheelhouse,
        )
    else:
        r = subprocess.run(
            wheelhouse_cmd
            or [
                "python3",
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "-q",
                *pins,
                "pytest",
                "setuptools",
                "wheel",
                "-d",
                str(wheelhouse),
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        if r.returncode != 0:
            raise PipelineError(f"wheelhouse 备轮失败:{r.stderr[-300:]}")
    # 事后核账只在**真备轮**时成立:`wheelhouse_cmd` 是测试注入口(E2E 用
    # `true` 跳过下载、改由 PYTHONPATH shim 提供上游),那种情况下这里没有
    # 东西可核 —— 核一个没发生的动作只会得出假结论。生产侧无人传此参数。
    downloaded = [f.name for f in wheelhouse.iterdir() if f.is_file()] if wheelhouse_cmd is None else []
    want = normalize_dist_name(sr["distribution"]) if wheelhouse_cmd is None else ""
    if want and not any(normalize_dist_name(n.split("-")[0]) == want for n in downloaded):
        # 事后核账:pip 说成功不等于上游真躺在那儿。不量一次就等于假设。
        raise PipelineError(
            f"备轮完成但 wheelhouse 里没有上游 {sr['distribution']!r}:"
            f"{sorted(downloaded)[:8]} —— 会话将 import 不到上游,拒绝继续。"
        )
    stages["wheelhouse"] = {
        "wheels": len(list(wheelhouse.glob("*.whl"))),
        "upstream_present": True,
        "source": (
            "PREREGISTERED"
            if prefrozen_manifest is not None
            else "INDEX_RESOLVED"
        ),
        "root": (prefrozen_manifest or {}).get("root"),
    }

    if wheelhouse_cmd is None:
        staged_wheelhouse = _stage_workspace_wheelhouse(
            host_contract_path=Path(contract),
            tool_contract_path=project_root / "contracts" / f"{task_id}.yaml",
            wheelhouse=wheelhouse,
        )
        if staged_wheelhouse is not None:
            stages["package_wheelhouse"] = staged_wheelhouse

    # ToolSpec v3 Fresh audit executes the task-authored semantic verifier in
    # the same exact dependency/source context that existed before the Coding
    # Agent ran.  Freeze that trusted context now, while the target skeleton is
    # still pristine and before either rehearsal or a real model can consume
    # budget.  The Agent works in an isolated worktree, so its legitimate
    # adapter patch never rewrites this source-side package manifest.
    if wheelhouse_cmd is None:
        from repoproof.harness import task_package
        from repoproof.harness.wheelhouse import compute_manifest

        try:
            package_manifest = task_package.freeze(
                project_root,
                project_root / "contracts" / f"{task_id}.yaml",
                upstream_dir=up,
                wheelhouse_manifest=compute_manifest(wheelhouse),
            )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            raise PipelineError(
                "ToolSpec v3 冻结证据束无法生成；不得进入 Agent",
                reason_code="FROZEN_TASK_PACKAGE_INVALID",
                recommended_action=(
                    "检查冻结合同、oracle、目标骨架、钉版上游和 wheelhouse；修复 Harness 后创建新 task version。"
                ),
                partial_result={
                    "task_id": task_id,
                    "stages": stages,
                    "verdict": "BLOCKED",
                    "exported": None,
                },
            ) from exc
        stages["task_package"] = {
            "root_hash": package_manifest.root_hash,
            "wheelhouse_root": package_manifest.wheelhouse_root,
            "frozen_before_agent": True,
        }

    # 4b) 预算前强制预检:仅使用冻结合同、wheelhouse 与第一个确认样例。
    # 这里失败不会创建 Agent run,也不会进入 RepairLoop。
    if wheelhouse_cmd is None:
        from repoproof.runner.product_preflight import run_product_preflight

        preflight = run_product_preflight(
            project_root=project_root,
            task_id=task_id,
            tool_contract_path=project_root / "contracts" / f"{task_id}.yaml",
            host_contract_path=Path(contract),
            wheelhouse=wheelhouse,
        )
        stages["preflight"] = preflight.model_dump(mode="json")
        if not preflight.ok:
            return {
                "task_id": task_id,
                "stages": stages,
                "verdict": "BLOCKED",
                "exported": None,
            }
    else:
        stages["preflight"] = {
            "schema_version": 1,
            "ok": True,
            "test_injected": True,
            "checks": [],
        }

    # 5/6) 路由执行器(Gate 3):两条路线共享前段(confirm/pin/物化/备轮)
    # 与后段(投影/export/注册);中段按 Capability Plan 分道。
    if route == "DIRECT_WRAP":
        # 确定性快路径:骨架已含受信模板交付,零 Agent、零真发 ——
        # 一发 fake="direct"(零动作提交)走完整验证链;零 diff + 全门过
        # = PASS_DIRECT(completion gate 既有语义,零改动)。
        d = run_host_guided_cli(contract, project_root, fake="direct", batch=batch)
        if d.get("blocked"):
            stages["direct"] = d
            return {"task_id": task_id, "stages": stages, "verdict": "DIRECT_BLOCKED", "exported": None}
        rp = d.get("report") or {}
        stages["direct"] = {
            "verdict": rp.get("verdict"),
            "run_id": rp.get("run_id"),
            "gate_reasons": rp.get("gate_reasons"),
            "agent_invoked": False,
            "route": route,
        }
        # DIRECT_WRAP 失败不得自动切 AGENT_ADAPT(RFC-013 §4):换路线
        # 必须重新生成并确认计划。
    else:
        # 5) fake 彩排门:不 PASS 不许烧真预算
        fake = run_host_guided_cli(contract, project_root, fake="positive", batch=batch)
        fk = fake.get("report") or {}
        stages["rehearsal"] = _rehearsal_stage(fk)
        if fk.get("verdict") != "PASS_ADAPTED":
            return {"task_id": task_id, "stages": stages, "verdict": f"REHEARSAL_{fk.get('verdict')}", "exported": None}

        if not run_real:
            return {"task_id": task_id, "stages": stages, "verdict": "REHEARSAL_PASS_ONLY", "exported": None}

        # 6) 真模型单发(provider 从 env;未配置由 preflight 如实拦)
        real = run_host_guided_cli(
            contract,
            project_root,
            fake=None,
            batch=batch,
            backend=agent_backend,
        )
        if real.get("blocked"):
            stages["real"] = real
            return {"task_id": task_id, "stages": stages, "verdict": "REAL_BLOCKED", "exported": None}
        rp = real.get("report") or {}
        stages["product_incidents"] = {
            "records": _record_workspace_repair_incidents(
                project_root=project_root,
                task_id=task_id,
                run_id=str(rp.get("run_id") or ""),
            )
        }
        stages["agent_backend"] = {
            "id": agent_backend,
            "product_mode_only": agent_backend == "codex-cli",
            "benchmark_eligible": False,
        }
    # Gate 2:修复循环事实的产品投影(纯读取侧派生,历史/新 run 同函,
    # 不回写 report 与任何台账)。两条路线共用。
    from repoproof.adoption.repair.failure_assessment import (
        assess_report,
        derive_repair_metrics,
    )

    proj_key = "direct" if route == "DIRECT_WRAP" else "real"
    metrics = derive_repair_metrics(rp)
    stages[proj_key] = {
        **stages.get(proj_key, {}),
        "verdict": rp.get("verdict"),
        "verdict_public": rp.get("verdict_public"),
        "run_id": rp.get("run_id"),
        "gate_reasons": rp.get("gate_reasons"),
        "repair_metrics": metrics,
        "product_stop_code": metrics["product_stop_code"],
    }
    expected = ("PASS_DIRECT",) if route == "DIRECT_WRAP" else ("PASS_ADAPTED", "PASS_DIRECT")
    if rp.get("verdict") not in expected:
        stages[proj_key]["failure_assessment"] = assess_report(rp).model_dump()
        return {"task_id": task_id, "stages": stages, "verdict": rp.get("verdict"), "exported": None}

    # 7) export + 注册
    historical_verdict = rp.get("verdict_public") or rp.get("verdict")
    try:
        dest = install_verified_tool(
            Path(project_root) / "runs" / rp["run_id"],
            host_contract_path=contract,
            tool_contract_path=Path(project_root) / "contracts" / f"{task_id}.yaml",
            dest_root=Path(dest_root),
            exported_at=datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except (ToolExportError, ReleaseLedgerError, OSError, ValueError) as exc:
        stages["export"] = {"ok": False, "error": str(exc)}
        reason_code, action = _install_error_projection(exc)
        raise PipelineError(
            f"工具安装结算失败:{exc}",
            reason_code=reason_code,
            recommended_action=action,
            partial_result={
                "task_id": task_id,
                "stages": stages,
                "verdict": historical_verdict,
                "historical_verdict": historical_verdict,
                "exported": None,
            },
        ) from exc
    release_status = operational_status(Path(dest_root), dest.name, task_id=task_id)
    stages["export"] = {
        "dest": str(dest),
        "historical_verdict": historical_verdict,
        "operational_status": release_status,
    }
    return {
        "task_id": task_id,
        "stages": stages,
        "verdict": historical_verdict,
        "historical_verdict": historical_verdict,
        "operational_status": release_status,
        "exported": str(dest),
    }
