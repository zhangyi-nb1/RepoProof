"""Bounded Product Mode jobs and draft editing for RepoProof Studio.

Product state lives below ``REPOPROOF_UI_STATE_ROOT`` (``~/.repoproof`` by
default).  This service never writes Benchmark Lab ``runs/``, benchmarks or
evidence, and every CLI launch uses an argv list rather than a shell.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from repoproof.adoption.assembly.example_compiler import (
    UPSTREAM_CONFIRMED,
    TruthProvenance,
    truth_binding_sha256,
)
from repoproof.adoption.assembly.tool_assembler import next_tool_task_id
from repoproof.adoption.intake.draft_readiness import (
    DraftReadinessV1,
    evaluate_draft_readiness,
    resolved_dependency_lock,
)
from repoproof.adoption.intake.intent_contract import (
    IntentContractDraftV1,
    IntentContractError,
    install_artifact_protocol,
    install_delivery_intent_from_interface,
    invalidate_intent_confirmation,
    replace_delivery_input_representation,
    replace_semantic_commitments,
)
from repoproof.adoption.intake.tool_confirm import (
    ConfirmError,
    confirm_tool_intent_file,
)
from repoproof.execution.core_execution import (
    LEGACY_LAB_STATE,
    RUNNING,
    legacy_state_blocker,
    read_durable_job_state,
    start_durable_job,
)
from repoproof.execution.product_action import read_product_action_result_with_sha256
from repoproof.persistence.qualification_records import (
    qualification_framework_tree_sha256,
)
from repoproof.runner.tool_paths import (
    ToolPathError,
    canonical_tool_path,
    ensure_safe_package_tree,
    validate_tool_name,
    validate_tool_task_id,
)
from repoproof.ui.services.product_mode import ui_state_root

PRODUCT_LOCK = "product-job.json"
_EXACT_PIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9._+!-]*")
_CONTROL_REPAIR_MARKER = ".repoproof-control-repair.incomplete"


def _product_source_tree_sha256(root: Path | None = None) -> str:
    """Bind a Studio process to the Python source tree it actually loaded.

    Streamlit reloads page files without evicting imported Core/service modules.
    A page can therefore look current while executing older admission or trust
    semantics.  Hashing the package source is deliberately broader than an API
    signature check: semantic-only edits must also force a process restart.
    """

    package_root = Path(root or Path(__file__).resolve().parents[2])
    return qualification_framework_tree_sha256(package_root)


_LOADED_PRODUCT_SOURCE_SHA256 = _product_source_tree_sha256()


def product_runtime_source_freshness() -> dict[str, str | bool]:
    """Report only source identity, never paths or source contents."""

    try:
        current = _product_source_tree_sha256()
    except OSError:
        return {
            "fresh": False,
            "reason_code": "PRODUCT_RUNTIME_SOURCE_FINGERPRINT_UNAVAILABLE",
        }
    return {
        "fresh": current == _LOADED_PRODUCT_SOURCE_SHA256,
        "reason_code": (
            "PRODUCT_RUNTIME_SOURCE_CURRENT"
            if current == _LOADED_PRODUCT_SOURCE_SHA256
            else "PRODUCT_RUNTIME_SOURCE_STALE"
        ),
        "loaded_sha256": _LOADED_PRODUCT_SOURCE_SHA256,
        "current_sha256": current,
    }


def _open_absolute_directory(path: Path) -> int:
    """Open an absolute directory one component at a time without symlinks."""

    absolute = Path(path).absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(absolute.anchor, flags | nofollow)
    try:
        for part in absolute.parts[1:]:
            next_fd = os.open(part, flags | nofollow, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    except BaseException:
        os.close(fd)
        raise
    return fd


def _open_child_directory(parent_fd: int, name: str, *, create: bool) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if create:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
    return os.open(name, flags | nofollow, dir_fd=parent_fd)


def _read_file_at(parent_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
    try:
        chunks: list[bytes] = []
        while chunk := os.read(fd, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_new_file_at(parent_fd: int, name: str, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def _replace_file_at(parent_fd: int, name: str, payload: bytes) -> None:
    temporary = f".{name}.{secrets.token_hex(12)}.tmp"
    try:
        _write_new_file_at(parent_fd, temporary, payload)
        os.replace(
            temporary,
            name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _path_has_symlink(path: Path) -> bool:
    absolute = Path(path).absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
        if not current.exists():
            break
    return False


def _validated_draft_dir(
    value: Path,
    *,
    require_existing: bool,
) -> tuple[Path | None, str | None]:
    """Keep Studio-authored draft mutations below its private drafts root."""

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return None, "草稿目录必须使用绝对路径。"
    if _path_has_symlink(candidate):
        return None, "草稿目录及其父目录不能是 symlink。"
    drafts_root = (ui_state_root() / "drafts").expanduser().resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(drafts_root)
    except ValueError:
        return None, f"草稿目录必须位于受管目录内：{drafts_root}"
    if require_existing:
        if not resolved.is_dir() or resolved.is_symlink():
            return None, f"草稿目录不存在或不是普通目录：{resolved}"
        for required in ("draft.yaml", "reference_impl.py", "examples.yaml"):
            path = resolved / required
            if path.is_symlink() or (path.exists() and not path.is_file()):
                return None, f"草稿控制文件必须是普通文件：{path}"
        examples_dir = resolved / "examples"
        if not examples_dir.is_dir() or examples_dir.is_symlink():
            return None, f"样例目录必须是受管草稿内的普通目录：{examples_dir}"
    elif resolved.exists() or resolved.is_symlink():
        return None, f"草稿目录已存在，拒绝覆盖：{resolved}"
    return resolved, None


def validate_managed_draft_dir(
    value: Path,
    *,
    require_existing: bool = True,
) -> tuple[Path | None, str | None]:
    """Public read gate used before Studio renders any draft content."""

    return _validated_draft_dir(Path(value), require_existing=require_existing)


def _dependency_lock_state(draft_dir: Path, draft: dict) -> dict:
    """→ {source, pins, note}:这次构建会拿什么版本的上游进会话。

    source = "user"(草稿束里你写的 reference.lock.txt)
           | "derived"(从钉版树声明版本派生)
           | "missing"(两者都没有 —— 构建会当场拒发,不会再白跑三轮)
    """
    from repoproof.adoption.intake.upstream_pin import derive_reference_lock
    from repoproof.ui.services.product_mode import project_root

    lock = Path(draft_dir) / "reference.lock.txt"
    if lock.is_file() and lock.read_text(encoding="utf-8").strip():
        pins = [
            ln.strip() for ln in lock.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")
        ]
        return {"source": "user", "pins": pins, "note": "以你在草稿束里写的 reference.lock.txt 为准。"}
    sr = draft.get("source_repo") or {}
    derived = derive_reference_lock(
        project_root(),
        distribution=str(sr.get("distribution") or ""),
        resolved_commit=str(sr.get("resolved_commit") or ""),
        import_module=str(sr.get("import_module") or ""),
        requested_revision=str(sr.get("revision") or ""),
    )
    if derived:
        pins = [ln.strip() for ln in derived.splitlines() if ln.strip() and not ln.startswith("#")]
        return {"source": "derived", "pins": pins, "note": "你没写依赖锁，系统按钉版上游树自己声明的版本派生。"}
    return {
        "source": "missing",
        "pins": [],
        "note": (
            "钉版树读不出声明版本（多半是动态版本）。请在草稿目录下"
            "新建 reference.lock.txt 写上 `<包名>==<版本>` —— "
            "没有它，会话里装不上上游，构建会被拒发。"
        ),
    }


def _control_repair_incomplete(draft_dir: Path) -> bool:
    """A durable marker makes every partially mutated control bundle unusable."""

    return os.path.lexists(Path(draft_dir) / _CONTROL_REPAIR_MARKER)


def _core_draft_readiness(
    draft: dict,
    draft_dir: Path,
    *,
    allow_control_repair: bool = False,
) -> DraftReadinessV1:
    """Evaluate one managed draft through the Core-owned read-only boundary."""

    from repoproof.ui.services.product_mode import project_root

    readiness = evaluate_draft_readiness(
        draft,
        draft_dir,
        project_root=project_root(),
    )
    if allow_control_repair or not _control_repair_incomplete(draft_dir):
        return readiness
    return readiness.model_copy(
        update={
            "status": "INCOMPATIBLE",
            "compatible": False,
            "current": False,
            "ready": False,
            "ready_to_confirm": False,
            "reason_codes": list(
                dict.fromkeys(
                    [
                        "DRAFT_CONTROL_REPAIR_INCOMPLETE",
                        *readiness.reason_codes,
                    ]
                )
            ),
            "recommended_action": (
                "检测到未完成的控制面修复事务。不要继续确认、生成样例或冻结；"
                "请从 repair 前快照恢复该草稿，或创建新 task version。"
            ),
        }
    )


def _readiness_rejection(readiness: DraftReadinessV1, *, action: str) -> dict:
    code = "DRAFT_INCOMPATIBLE" if not readiness.compatible else "DRAFT_NOT_READY"
    return {
        "ok": False,
        "error_code": code,
        "reason_codes": readiness.reason_codes,
        "error": f"{action}被 Core readiness 拒绝。",
        "recommended_action": readiness.recommended_action,
        "draft_readiness": readiness.model_dump(mode="json"),
    }


def read_managed_draft_review(value: Path) -> dict:
    """Read the bounded review surface without following optional symlinks."""

    draft_dir, error = validate_managed_draft_dir(value)
    if draft_dir is None:
        return {"ok": False, "error": error}
    draft_fd: int | None = None
    try:
        draft_fd = _open_absolute_directory(draft_dir)
        raw_draft = _read_file_at(draft_fd, "draft.yaml").decode("utf-8")
        draft = yaml.safe_load(raw_draft) or {}
        if not isinstance(draft, dict):
            raise TypeError("draft.yaml 根节点必须是对象")
        tool = draft.get("tool") or {}
        workspace_profile = (
            int(tool.get("schema_version") or 1) == 4
            and tool.get("delivery_profile_id") == "workspace_bundle_v1"
        )
        examples_name = "workspace_examples.yaml" if workspace_profile else "examples.yaml"
        raw_examples = _read_file_at(draft_fd, examples_name).decode("utf-8")
        reference = _read_file_at(draft_fd, "reference_impl.py").decode("utf-8")
        try:
            semantic_verifier = _read_file_at(
                draft_fd,
                "semantic_verifier.py",
            ).decode("utf-8")
        except FileNotFoundError:
            semantic_verifier = ""
        examples_doc = yaml.safe_load(raw_examples) or {}
        if not isinstance(examples_doc, dict):
            raise TypeError(f"{examples_name} 根节点必须是对象")
        try:
            gaps = _read_file_at(draft_fd, "GAPS.md").decode("utf-8")
        except FileNotFoundError:
            gaps = ""
        readiness = _core_draft_readiness(draft, draft_dir)
        readiness_document = readiness.model_dump(mode="json")
        return {
            "ok": True,
            "draft_dir": draft_dir,
            "draft": draft,
            "raw_draft": raw_draft,
            "examples": examples_doc.get("examples") or [],
            "delivery_profile_id": (
                "workspace_bundle_v1" if workspace_profile else "cli_v2"
            ),
            "workspace_contract": (
                tool.get("workspace_contract") if workspace_profile else None
            ),
            "reference_impl": reference,
            "semantic_verifier": semantic_verifier,
            "gaps": gaps,
            "draft_readiness": readiness_document,
            # Transitional projection for callers released before the Core
            # readiness protocol.  It contains no independent verdict logic.
            "semantic_readiness": {
                "ok": readiness.ready_to_confirm,
                "reason_codes": readiness.reason_codes,
                "recommended_action": readiness.recommended_action,
            },
            # 依赖锁的**可见状态**(2026-08-28 用户实测):GAPS.md 一直写着
            # `reference_lock(owner=AUTO):由 pip 冻结闭包生成`,但从没有
            # 组件真的生成它 —— 承诺了没兑现,而审核页也从不显示它,于是
            # 用户走完全部步骤仍拿到一个必崩的构建。现在既然真会派生,
            # 就得让人看得见、能核对。
            "dependency_lock": _dependency_lock_state(draft_dir, draft),
        }
    except (OSError, UnicodeError, TypeError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"草稿无法安全读取：{exc}"}
    finally:
        if draft_fd is not None:
            os.close(draft_fd)


def _validated_dest_root(value: Path) -> tuple[Path | None, str | None]:
    """Validate an explicit managed tool root without silently broadening it."""

    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return None, "工具库位置必须使用绝对路径。"
    if _path_has_symlink(candidate):
        return None, "工具库位置及其父目录不能是 symlink。"
    resolved = candidate.resolve(strict=False)
    forbidden = {
        Path("/").resolve(),
        Path.home().resolve(),
        _product_root().resolve(),
        ui_state_root().expanduser().resolve(),
    }
    if resolved in forbidden:
        return None, f"工具库位置过于宽泛，拒绝使用：{resolved}"
    if resolved.exists() and not resolved.is_dir():
        return None, f"工具库位置不是目录：{resolved}"
    return resolved, None


def _valid_public_github_repo(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return False
    parts = [part for part in parsed.path.split("/") if part]
    return bool(
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and port is None
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and "%" not in parsed.path
        and len(parts) == 2
        and all(part not in {".", ".."} for part in parts)
    )


def _product_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _product_python(root: Path | None = None) -> str:
    candidate = Path(root or _product_root()) / ".venv" / "bin" / "python"
    return str(candidate if candidate.is_file() else Path(sys.executable))


def tool_add_argv(
    root: Path,
    *,
    repo: str,
    capability: str,
    draft_dir: Path,
    revision: str | None = None,
    fake_drafter: bool = False,
    authoritative_delivery_requirements: dict | None = None,
) -> list[str]:
    argv = [
        _product_python(root),
        "-m",
        "repoproof.cli",
        "tool",
        "add",
        "--repo",
        repo,
        "--capability",
        capability,
        "--draft-out",
        str(draft_dir),
    ]
    if revision:
        argv += ["--revision", revision]
    if authoritative_delivery_requirements is not None:
        argv += [
            "--delivery-requirements-json",
            json.dumps(
                authoritative_delivery_requirements,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ]
    if fake_drafter:
        argv.append("--fake-drafter")
    return argv


def tool_build_argv(
    root: Path,
    *,
    draft_dir: Path,
    dest_root: Path,
    rehearsal_only: bool,
    agent_backend: str = "mini-swe",
) -> list[str]:
    argv = [
        _product_python(root),
        "-m",
        "repoproof.cli",
        "tool",
        "build",
        "--draft-dir",
        str(draft_dir),
        "--dest-root",
        str(dest_root),
        "--agent-backend",
        agent_backend,
    ]
    if rehearsal_only:
        argv.append("--rehearsal-only")
    return argv


def product_job_state() -> dict | None:
    path = ui_state_root() / PRODUCT_LOCK
    if not path.is_file():
        return None
    return read_durable_job_state(path)


def read_product_job_log(job: dict, *, limit: int = 12000) -> dict:
    """Read only the tail of a regular log below Studio's private log root."""

    raw = job.get("log")
    if not isinstance(raw, str) or not raw:
        return {"ok": False, "error": "日志位置未记录。"}
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() or _path_has_symlink(candidate):
        return {"ok": False, "error": "日志路径无效。"}
    logs_root = (ui_state_root() / "logs").expanduser().resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(logs_root)
    except ValueError:
        return {"ok": False, "error": "日志路径不在受管目录内。"}
    try:
        fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return {"ok": False, "error": "日志文件尚未创建。"}
    except OSError as exc:
        return {"ok": False, "error": f"日志无法安全读取：{exc}"}
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            return {"ok": False, "error": "日志目标不是普通文件。"}
        offset = max(0, opened.st_size - max(1, limit))
        os.lseek(fd, offset, os.SEEK_SET)
        payload = os.read(fd, max(1, limit))
    finally:
        os.close(fd)
    return {"ok": True, "text": payload.decode("utf-8", errors="replace")}


def _start_product_job(
    argv: list[str],
    *,
    kind: str,
    label: str,
    expected_artifact: Path | None = None,
    expected_action_result: bool = False,
    journey_id: str = "",
    metadata: dict | None = None,
) -> dict:
    # 判定器是 **fail-closed** 的:退出码 0 但没形成"预期产物"一律记 FAILED
    # (`test_exit_zero_without_expected_artifact_is_failed` 钉着这条,是有意的
    # ——证明不了产出就不许算成功)。因此**漏给 expected_artifact 是调用方的
    # 缺陷**,而它的表现极具误导性:2026-08-28 用户的续跑真发跑出
    # PASS_ADAPTED、工具都装进了 ~/tools,界面却写"失败:未形成预期产物"。
    # 与其让人等几分钟再吃一个假失败,不如在这里当场拒绝。
    if expected_artifact is None and not expected_action_result:
        return {
            "ok": False,
            "error": (
                f"内部缺陷:{label} 没有声明预期产物,"
                "而判定器按 fail-closed 处理(证明不了产出即判失败)。"
                "请给这个任务补上 expected_artifact。"
            ),
        }
    root = _product_root()
    state_root = ui_state_root()
    for legacy_path in (
        state_root / PRODUCT_LOCK,
        root / LEGACY_LAB_STATE,
    ):
        if reason := legacy_state_blocker(legacy_path):
            return {"ok": False, "error": reason}
    current = product_job_state()
    if current and current.get("status") == RUNNING:
        return {"ok": False, "error": f"已有任务在运行：{current.get('label')}"}
    state_root.mkdir(parents=True, exist_ok=True)
    log_dir = state_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}"
    log = log_dir / f"{kind}-{stamp}.log"
    job_id = uuid.uuid4().hex
    result_dir = state_root / "job-results"
    result_dir.mkdir(parents=True, exist_ok=True)
    result_json = result_dir / f"{job_id}.json"
    # A resumed checkpoint may intentionally leave every frozen artifact
    # byte-for-byte unchanged. Its fresh, job-bound ProductActionResultV1 is the
    # correct Worker artifact: Pipeline independently projects the verdict inside
    # that result. The per-job path did not exist before launch, so the durable
    # runner still requires a concrete new artifact before reporting success.
    worker_artifact = result_json if expected_action_result else expected_artifact
    action_argv = [
        *argv,
        "--job-id",
        job_id,
        "--result-json",
        str(result_json),
    ]
    if journey_id:
        action_argv.extend(["--journey-id", journey_id])
    state_metadata = {
        "result_json": str(result_json),
        "journey_id": journey_id,
        **(metadata or {}),
    }
    started = start_durable_job(
        root=root,
        state_path=state_root / PRODUCT_LOCK,
        worker_python=_product_python(root),
        argv=action_argv,
        cwd=root,
        log_path=log,
        kind=kind,
        label=label,
        expected_artifact=worker_artifact,
        metadata=state_metadata,
        job_id=job_id,
    )
    if started.get("ok") and journey_id:
        try:
            from repoproof.ui.services.product_journeys import update_journey

            journey_changes = {"last_job_id": job_id}
            for key in ("tool_name", "task_id", "draft_dir", "dest_root"):
                value = (metadata or {}).get(key)
                if value:
                    journey_changes[key] = value
            update_journey(journey_id, **journey_changes)
        except (OSError, ValueError):
            # The action remains safely bound in ProductJobStateV2. A corrupt
            # navigation pointer must not cancel or redefine the Core action.
            started["journey_warning"] = "任务已启动，但 Journey 导航记录无法更新。"
    return started


def product_job_action_result(job: dict | None = None) -> dict:
    """Read the structured semantic result bound to one durable job."""

    job = job or product_job_state()
    if not job:
        return {"ok": False, "error_code": "NO_PRODUCT_JOB", "error": "没有后台任务。"}
    raw = job.get("result_json")
    if not isinstance(raw, str) or not raw:
        return {
            "ok": False,
            "error_code": "ACTION_RESULT_UNAVAILABLE",
            "error": "旧任务没有结构化动作结果；日志只能用于排查，不能推导可信状态。",
        }
    candidate = Path(raw).expanduser()
    root = (ui_state_root() / "job-results").resolve()
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return {
            "ok": False,
            "error_code": "ACTION_RESULT_PATH_INVALID",
            "error": "动作结果路径不在受管目录内。",
        }
    try:
        result, actual_sha256 = read_product_action_result_with_sha256(resolved)
    except FileNotFoundError:
        return {
            "ok": False,
            "error_code": "ACTION_RESULT_PENDING",
            "error": "动作结果尚未写入。",
        }
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error_code": "ACTION_RESULT_INVALID",
            "error": f"动作结果损坏：{exc}",
        }
    expected_sha256 = job.get("result_json_sha256")
    if isinstance(expected_sha256, str) and expected_sha256:
        if not secrets.compare_digest(actual_sha256, expected_sha256):
            return {
                "ok": False,
                "error_code": "ACTION_RESULT_HASH_MISMATCH",
                "error": "动作结果与后台任务记录的终态哈希不一致。",
            }
    if result.job_id != job.get("job_id"):
        return {
            "ok": False,
            "error_code": "ACTION_RESULT_JOB_MISMATCH",
            "error": "动作结果与后台任务身份不一致。",
        }
    return {"ok": True, "result": result.model_dump(mode="json")}


def start_tool_add(
    *,
    repo: str,
    capability: str,
    draft_dir: Path,
    revision: str | None = None,
    fake_drafter: bool = False,
    journey_id: str = "",
    authoritative_delivery_requirements: dict | None = None,
) -> dict:
    if not _valid_public_github_repo(repo):
        return {"ok": False, "error": "当前只支持公开 GitHub 仓库地址。"}
    if len(capability.strip()) < 8:
        return {"ok": False, "error": "请用一句完整的话描述想要的能力。"}
    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=False)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir  # 判空后再回赋:参数类型不被 None 污染
    root = _product_root()
    return _start_product_job(
        tool_add_argv(
            root,
            repo=repo,
            capability=capability.strip(),
            draft_dir=draft_dir,
            revision=revision,
            fake_drafter=fake_drafter,
            authoritative_delivery_requirements=(
                authoritative_delivery_requirements
            ),
        ),
        kind="tool-add",
        label=f"分析并起草 {repo.rsplit('/', 1)[-1]}",
        expected_artifact=draft_dir / "draft.yaml",
        journey_id=journey_id,
        metadata={"draft_dir": str(draft_dir), "journey_stage": 1},
    )


def list_rehearsed_tasks() -> list[dict]:
    """已冻结且彩排过、但还没导出的任务(构建页"待续跑")。"""
    from repoproof.runner.tool_pipeline import rehearsed_tasks
    from repoproof.ui.services.product_mode import project_root

    try:
        return rehearsed_tasks(project_root())
    except OSError:
        return []


def start_tool_build_real(
    task_id: str,
    dest_root: Path,
    agent_backend: str = "mini-swe",
    journey_id: str = "",
    rehearsal_only: bool = False,
    draft_dir: Path | None = None,
) -> dict:
    """对已冻结任务跑真实构建 —— 彩排通过之后的下半程。

    2026-08-28 实录:`tool_build` 在彩排**之前**就把草稿归档(冻结即消耗,
    这是对的),但 UI 只有"从草稿构建"一个入口 —— 于是彩排通过后回到构建
    页只看到"草稿目录不存在",用户只能重建草稿再冻一版(v2/v3/v4…)。
    题面不重冻,直接对同一份合同续跑。
    """
    checked_root, dest_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": dest_error}
    clean = str(task_id or "").strip()
    if not clean or "/" in clean or clean.startswith("."):
        return {"ok": False, "error": "任务 id 非法"}
    root = _product_root()
    # 预期产物 = 导出的工具清单(与 start_tool_build 真发分支同口径)。
    # 工具名以**冻结的工具合同**为准,不从 task_id 猜。
    frozen_contract = root / "contracts" / f"{clean}.yaml"
    expected = None
    if not rehearsal_only:
        try:
            frozen = yaml.safe_load(frozen_contract.read_text(encoding="utf-8")) or {}
            tool_name = str(((frozen.get("tool") or {}).get("name")) or "").strip()
            if tool_name:
                expected = checked_root / tool_name / "tool.json"
        except (OSError, yaml.YAMLError):
            expected = None
    argv = [
        _product_python(root),
        "-m",
        "repoproof.cli",
        "tool",
        "build-real",
        "--task-id",
        clean,
        "--dest-root",
        str(checked_root),
        "--agent-backend",
        agent_backend,
    ]
    if rehearsal_only:
        argv.append("--rehearsal-only")
    if draft_dir is not None:
        checked_draft, draft_error = _validated_draft_dir(
            Path(draft_dir),
            require_existing=True,
        )
        if checked_draft is None:
            return {"ok": False, "error": draft_error}
        argv += ["--draft-dir", str(checked_draft)]
    return _start_product_job(
        argv,
        kind="tool-build",
        label=("重新运行零模型演练" if rehearsal_only else "真实构建") + f" {clean}（已冻结任务续跑）",
        expected_artifact=expected,
        expected_action_result=rehearsal_only,
        journey_id=journey_id,
        metadata={
            "task_id": clean,
            **({"draft_dir": str(checked_draft)} if draft_dir is not None else {}),
            "dest_root": str(checked_root),
            "journey_stage": 3 if rehearsal_only else 4,
        },
    )


def start_tool_build(
    *,
    draft_dir: Path,
    dest_root: Path,
    rehearsal_only: bool,
    agent_backend: str = "mini-swe",
    journey_id: str = "",
) -> dict:
    if agent_backend not in {"codex-cli", "mini-swe"}:
        return {"ok": False, "error": "未知 Agent backend。"}
    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=True)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir  # 判空后再回赋:参数类型不被 None 污染
    checked_root, dest_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": dest_error}
    dest_root = checked_root  # 判空后再回赋,同上
    draft_path = draft_dir / "draft.yaml"
    if not draft_path.is_file():
        return {"ok": False, "error": f"未找到草稿：{draft_path}"}
    try:
        draft = yaml.safe_load(draft_path.read_text(encoding="utf-8")) or {}
        if not isinstance(draft, dict):
            raise TypeError("draft.yaml 根节点必须是对象")
        readiness = _core_draft_readiness(draft, draft_dir)
        if not readiness.ready:
            return _readiness_rejection(readiness, action="启动构建")
        name = validate_tool_name(draft["tool"]["name"])
    except (OSError, KeyError, TypeError, ToolPathError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"草稿无法读取：{exc}"}
    root = _product_root()
    # draft.task_id is only an intake suggestion and may still say v1 after an
    # earlier version was frozen.  The assembler is the version authority.
    try:
        predicted_task_id = next_tool_task_id(root, name)
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "error_code": "TASK_VERSION_LINEAGE_INVALID",
            "error": f"任务版本谱系无法安全计算：{exc}",
        }
    expected = root / "contracts" / f"{predicted_task_id}.yaml" if rehearsal_only else dest_root / name / "tool.json"
    return _start_product_job(
        tool_build_argv(
            root,
            draft_dir=draft_dir,
            dest_root=dest_root,
            rehearsal_only=rehearsal_only,
            agent_backend=agent_backend,
        ),
        kind="tool-build",
        label=("离线彩排" if rehearsal_only else "完整构建") + f" {name}",
        expected_artifact=expected,
        journey_id=journey_id,
        metadata={
            "tool_name": name,
            "task_id": predicted_task_id,
            "draft_dir": str(draft_dir),
            "dest_root": str(dest_root),
            "journey_stage": 3 if rehearsal_only else 4,
        },
    )


def save_draft_review(
    draft_dir: Path,
    *,
    tool_name: str,
    summary: str,
    statement: str,
    semantic_commitments: list[str] | None = None,
    input_format: str,
    input_representation: str | None = None,
    output_format: str,
    output_schema: str,
    reference_impl: str,
    semantic_verifier: str | None = None,
    output_contract: dict | None = None,
    workspace_contract: dict | None = None,
    artifact_protocol: dict | None = None,
    # intake 把这三个标为 owner=USER(提取不到时要人来定),但审核页一直
    # 没有入口、本函数也不收 —— 声明了责任却没有履行路径,Studio 用户
    # 只能去手改 YAML(2026-08-28 AUTO/USER 全量核账发现的第二笔账)。
    distribution: str | None = None,
    import_module: str | None = None,
    license_id: str | None = None,
    reference_lock: str | None = None,
    _control_repair_transaction: bool = False,
) -> dict:
    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=True)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir  # 判空后再回赋:参数类型不被 None 污染
    clean_name = tool_name.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", clean_name):
        return {"ok": False, "error": "工具名只能包含小写字母、数字和连字符。"}
    draft_fd: int | None = None
    try:
        draft_fd = _open_absolute_directory(draft_dir)
        draft = yaml.safe_load(_read_file_at(draft_fd, "draft.yaml").decode("utf-8")) or {}
        if not isinstance(draft, dict):
            raise TypeError("draft.yaml 根节点必须是对象")
        tool_document = draft.get("tool") or {}
        workspace_profile = (
            int(tool_document.get("schema_version") or 1) == 4
            and tool_document.get("delivery_profile_id") == "workspace_bundle_v1"
        )
        if workspace_profile:
            from repoproof.domain.models import WorkspaceArtifactContractV1

            if output_contract is not None:
                return {
                    "ok": False,
                    "error": "WORKSPACE_STDOUT_CONTRACT_FORBIDDEN",
                    "failure_owner": "CONTRACT",
                    "reason_codes": ["WORKSPACE_STDOUT_CONTRACT_FORBIDDEN"],
                }
            selected_workspace_contract = (
                workspace_contract
                if workspace_contract is not None
                else tool_document.get("workspace_contract")
            )
            try:
                parsed_workspace_contract = WorkspaceArtifactContractV1.model_validate(
                    selected_workspace_contract
                )
            except ValueError as exc:
                return {
                    "ok": False,
                    "error": f"WORKSPACE_CONTRACT_INVALID: {exc}",
                    "failure_owner": "CONTRACT",
                    "reason_codes": ["WORKSPACE_CONTRACT_INVALID"],
                }
        else:
            if workspace_contract is not None:
                return {
                    "ok": False,
                    "error": "CLI_WORKSPACE_CONTRACT_FORBIDDEN",
                    "failure_owner": "CONTRACT",
                    "reason_codes": ["CLI_WORKSPACE_CONTRACT_FORBIDDEN"],
                }
            parsed_workspace_contract = None
        current_readiness = _core_draft_readiness(
            draft,
            draft_dir,
            allow_control_repair=_control_repair_transaction,
        )
        if not current_readiness.compatible or not current_readiness.current:
            return _readiness_rejection(current_readiness, action="保存草稿")
        try:
            current_semantic_verifier = _read_file_at(
                draft_fd,
                "semantic_verifier.py",
            ).decode("utf-8")
        except FileNotFoundError:
            current_semantic_verifier = ""
        # 保命闸(2026-08-28 实录):控件值一旦因任何原因是空的,保存就会把
        # 起草器辛苦填出来的内容抹掉,而用户看不见自己抹了什么。语义很清楚:
        # **清空不是一种编辑意图** —— 想改就写新的,想删没有正当场景。
        blanked = [
            name
            for name, new_value, old_value in (
                ("一句话摘要", summary, (draft.get("tool") or {}).get("summary")),
                ("能力和边界", statement, (draft.get("capability") or {}).get("statement")),
                (
                    "输入格式",
                    input_format,
                    ((draft.get("tool") or {}).get("interface") or {}).get("input", {}).get("format"),
                ),
                (
                    "输出格式",
                    output_format,
                    ((draft.get("tool") or {}).get("interface") or {}).get("output", {}).get("format"),
                ),
                ("输出结构名称", output_schema, (draft.get("capability") or {}).get("output_schema")),
                (
                    "独立语义验证器",
                    semantic_verifier,
                    current_semantic_verifier,
                ),
            )
            if new_value is not None and not str(new_value or "").strip() and str(old_value or "").strip()
        ]
        if blanked:
            return {
                "ok": False,
                "error": (
                    "拒绝保存:这些字段原本有内容，提交上来却是空的"
                    f"（{'、'.join(blanked)}）。多半是页面显示过期——"
                    "请刷新本页再改；清空不会被当作一次编辑。"
                ),
            }
        draft["tool"]["name"] = clean_name
        draft["tool"]["summary"] = summary.strip()
        draft["tool"]["interface"]["input"]["format"] = input_format.strip()
        draft["tool"]["interface"]["output"]["format"] = output_format.strip()
        if output_contract is not None and not workspace_profile:
            draft["tool"]["interface"]["output"]["contract"] = output_contract
        if workspace_profile and parsed_workspace_contract is not None:
            draft["tool"]["workspace_contract"] = parsed_workspace_contract.model_dump(
                mode="json"
            )
            draft["tool"]["interface"]["output"].pop("contract", None)
        if input_representation is not None:
            if input_representation not in {"utf8_text", "binary"}:
                return {
                    "ok": False,
                    "error": "INPUT_REPRESENTATION_INVALID: 请选择文本或二进制输入。",
                    "failure_owner": "USER_INPUT",
                    "reason_codes": ["INPUT_REPRESENTATION_INVALID"],
                }
            replace_delivery_input_representation(
                draft,
                input_representation,
            )
        install_delivery_intent_from_interface(
            draft,
            profile_id=str((draft.get("_delivery_profile") or {}).get("profile_id") or "cli_v2"),
        )
        if semantic_commitments is None:
            current_statement = str((draft.get("capability") or {}).get("statement") or "")
            if statement.strip() != current_statement:
                return {
                    "ok": False,
                    "error": ("能力语义必须通过公开行为承诺编辑；不能绕过追踪链直接改写最终 statement。"),
                }
        else:
            replace_semantic_commitments(draft, semantic_commitments)
        # The presentation grammar and semantic commitments are one public
        # contract.  Validate an edited protocol only after commitment IDs have
        # reached their new state, but before writing any file.  ``None`` means
        # "not edited" for compatibility; an empty/invalid object is rejected by
        # Core and can never erase the previously saved protocol.
        if artifact_protocol is not None:
            install_artifact_protocol(draft, artifact_protocol)
        sr = draft.setdefault("source_repo", {})
        for key, value in (("distribution", distribution), ("import_module", import_module), ("license", license_id)):
            if value is not None and value.strip():
                sr[key] = value.strip()
        normalized_lock: str | None = None
        if reference_lock is not None and reference_lock.strip():
            if len(reference_lock.encode("utf-8")) > 64 * 1024:
                return {"ok": False, "error": "依赖锁过大，拒绝保存。"}
            pins = [
                line.strip()
                for line in reference_lock.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            invalid_pins = [pin for pin in pins if _EXACT_PIN_RE.fullmatch(pin) is None]
            if not pins:
                return {"ok": False, "error": "依赖锁至少需要一个 `包名==精确版本`。"}
            if invalid_pins:
                return {
                    "ok": False,
                    "error": "依赖锁只接受 `包名==精确版本`，不接受 URL、路径、范围或 shell 选项："
                    + "、".join(invalid_pins[:3]),
                }
            normalized_lock = "\n".join(pins) + "\n"
        draft["capability"]["output_schema"] = output_schema.strip()
        draft["task_id"] = f"tool-{clean_name}-v1"
        target = draft.get("target_project") or {}
        target["path"] = f"fixtures/tool_skeleton_{clean_name}"
        target["package"] = clean_name.replace("-", "_")
        target["entry_point"] = clean_name
        draft["target_project"] = target
        draft["tool"]["interface"]["usage"] = (
            f"{clean_name} <input> --out-dir <new-directory>"
            if workspace_profile
            else f"{clean_name} <input> [--out FILE]"
        )
        invalidate_intent_confirmation(draft)
        _replace_file_at(
            draft_fd,
            "reference_impl.py",
            reference_impl.encode("utf-8"),
        )
        if semantic_verifier is not None:
            _replace_file_at(
                draft_fd,
                "semantic_verifier.py",
                semantic_verifier.encode("utf-8"),
            )
        _replace_file_at(
            draft_fd,
            "draft.yaml",
            yaml.safe_dump(draft, allow_unicode=True, sort_keys=False).encode("utf-8"),
        )
        if normalized_lock is not None:
            _replace_file_at(draft_fd, "reference.lock.txt", normalized_lock.encode("utf-8"))
        return {"ok": True, "note": "审核修改已保存；冻结前仍会经过确定性检查。"}
    except (
        IntentContractError,
        OSError,
        UnicodeError,
        KeyError,
        TypeError,
        yaml.YAMLError,
    ) as exc:
        return {"ok": False, "error": f"保存失败：{exc}"}
    finally:
        if draft_fd is not None:
            os.close(draft_fd)


def confirm_draft_intent(draft_dir: Path) -> dict:
    """Persist an explicit human confirmation bound to current semantics."""

    checked_dir, path_error = _validated_draft_dir(
        Path(draft_dir),
        require_existing=True,
    )
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    try:
        draft = yaml.safe_load((checked_dir / "draft.yaml").read_text(encoding="utf-8")) or {}
        if not isinstance(draft, dict):
            raise TypeError("draft.yaml 根节点必须是对象")
        readiness = _core_draft_readiness(draft, checked_dir)
        if not readiness.ready_to_confirm:
            return _readiness_rejection(readiness, action="确认语义")
        confirm_tool_intent_file(checked_dir)
        return {
            "ok": True,
            "note": "已绑定当前用户目标、公开行为承诺和交付接口；后续修改会使本次确认失效。",
        }
    except (ConfirmError, OSError, TypeError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"语义确认失败：{exc}"}


def add_golden_example(
    draft_dir: Path,
    *,
    input_name: str,
    input_bytes: bytes,
    expected_name: str,
    expected_bytes: bytes,
    truth_provenance: TruthProvenance = "USER_SUPPLIED",
    candidate_evidence_id: str | None = None,
    candidate_truth_binding_sha256: str | None = None,
) -> dict:
    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=True)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir  # 判空后再回赋:参数类型不被 None 污染
    invalid_names = {"", ".", ".."}
    if (
        input_name in invalid_names
        or expected_name in invalid_names
        or Path(input_name).name != input_name
        or Path(expected_name).name != expected_name
    ):
        return {"ok": False, "error": "样例文件名不能包含目录。"}
    input_rel = Path("inputs") / input_name
    expected_rel = Path("expected") / expected_name
    draft_fd: int | None = None
    examples_fd: int | None = None
    inputs_fd: int | None = None
    expected_fd: int | None = None
    input_created = False
    expected_created = False
    committed = False
    try:
        # Directory descriptors + O_NOFOLLOW keep every mutation inside the
        # already validated draft even if a local path is swapped concurrently.
        draft_fd = _open_absolute_directory(draft_dir)
        draft = yaml.safe_load(_read_file_at(draft_fd, "draft.yaml").decode("utf-8")) or {}
        if not isinstance(draft, dict):
            raise TypeError("draft.yaml 根节点必须是对象")
        readiness = _core_draft_readiness(draft, draft_dir)
        if not readiness.compatible or not readiness.current:
            return _readiness_rejection(readiness, action="保存样例")
        examples_fd = _open_child_directory(draft_fd, "examples", create=True)
        inputs_fd = _open_child_directory(examples_fd, "inputs", create=True)
        expected_fd = _open_child_directory(examples_fd, "expected", create=True)
        _write_new_file_at(inputs_fd, input_name, input_bytes)
        input_created = True
        _write_new_file_at(expected_fd, expected_name, expected_bytes)
        expected_created = True
        doc = yaml.safe_load(_read_file_at(draft_fd, "examples.yaml").decode("utf-8")) or {"examples": []}
        if not isinstance(doc, dict):
            raise TypeError("examples.yaml 根节点必须是对象")
        entry: dict[str, str] = {
            "input_file": str(input_rel),
            "expected_file": str(expected_rel),
            "truth_provenance": truth_provenance,
        }
        if truth_provenance == UPSTREAM_CONFIRMED:
            entry["truth_binding_sha256"] = truth_binding_sha256(
                input_bytes,
                expected_bytes,
            )
            if candidate_evidence_id is not None:
                if (
                    re.fullmatch(r"[0-9a-f]{64}", candidate_evidence_id) is None
                    or re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(candidate_truth_binding_sha256 or ""),
                    )
                    is None
                ):
                    raise ValueError("候选逐条证据身份无效")
                entry["candidate_evidence_id"] = candidate_evidence_id
                entry["candidate_truth_binding_sha256"] = str(candidate_truth_binding_sha256)
        doc.setdefault("examples", []).append(entry)
        _replace_file_at(
            draft_fd,
            "examples.yaml",
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False).encode("utf-8"),
        )
        committed = True
        return {"ok": True, "note": f"已加入样例：{input_name} → {expected_name}"}
    except FileExistsError:
        return {"ok": False, "error": "同名样例已存在，拒绝覆盖。"}
    except (OSError, UnicodeError, TypeError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"保存样例失败：{exc}"}
    finally:
        # Keep the manifest and both files transactional from the UI's point
        # of view: a failed manifest update must not leave an unregistered
        # golden file behind.
        if not committed:
            if input_created and inputs_fd is not None:
                try:
                    os.unlink(input_name, dir_fd=inputs_fd)
                except FileNotFoundError:
                    pass
            if expected_created and expected_fd is not None:
                try:
                    os.unlink(expected_name, dir_fd=expected_fd)
                except FileNotFoundError:
                    pass
        for fd in (expected_fd, inputs_fd, examples_fd, draft_fd):
            if fd is not None:
                os.close(fd)


_WORKSPACE_FIXTURE_STATE = "workspace_fixture_candidates.json"
_WORKSPACE_REFERENCE_RUNNER = '''import importlib.util
import json
import sys
from pathlib import Path

source, input_path, output_dir = sys.argv[1:4]
try:
    spec = importlib.util.spec_from_file_location("repoproof_workspace_reference", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("workspace reference cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    build = getattr(module, "build_workspace", None)
    if not callable(build):
        raise TypeError("reference must export build_workspace(input_path, output_dir)")
    build(Path(input_path), Path(output_dir))
except Exception as exc:
    if isinstance(exc, ModuleNotFoundError):
        kind = "dependency_missing"
    elif type(exc).__name__ == "UserInputError":
        kind = "fixture_rejected"
    elif isinstance(exc, (RuntimeError, TypeError)) and "reference" in str(exc):
        kind = "protocol_invalid"
    else:
        kind = "reference_exception"
    print(
        "REPOPROOF_WORKSPACE_REFERENCE_FAILURE="
        + json.dumps(
            {"failure_kind": kind, "exception_type": type(exc).__name__},
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )
    raise SystemExit(90) from None
'''

_WORKSPACE_REFERENCE_FAILURE_PREFIX = "REPOPROOF_WORKSPACE_REFERENCE_FAILURE="


def _workspace_tool_from_draft(draft: dict):
    from pydantic import ValidationError

    from repoproof.domain.models import ToolSpec
    from repoproof.execution.workspace_bundle import WorkspaceBundleError

    try:
        tool = ToolSpec.model_validate(draft.get("tool"))
    except ValidationError as exc:
        raise WorkspaceBundleError("WORKSPACE_CONTRACT_INVALID") from exc
    if (
        tool.schema_version != 4
        or tool.delivery_profile_id != "workspace_bundle_v1"
        or tool.workspace_contract is None
    ):
        raise ValueError("WORKSPACE_PROFILE_REQUIRED")
    return tool


def _workspace_tree_projection(path: Path, *, contract=None) -> dict[str, object]:
    from repoproof.execution.workspace_bundle import (
        WorkspaceBundleError,
        build_artifact_manifest,
        validate_workspace,
    )

    try:
        validation = validate_workspace(path, contract) if contract is not None else None
        manifest = (
            validation.manifest
            if validation is not None and validation.manifest is not None
            else build_artifact_manifest(path)
        )
    except WorkspaceBundleError as exc:
        return {
            "ok": False,
            "error": exc.code,
            "reason_codes": [exc.code],
        }
    entries = [
        {
            "path": item.path,
            "size": item.size,
            "mode": oct(item.mode),
            "sha256": item.sha256,
        }
        for item in manifest.entries
    ]
    return {
        "ok": bool(validation is None or validation.ok),
        "reason_codes": list(validation.reason_codes) if validation is not None else [],
        "tree_sha256": manifest.tree_sha256,
        "file_count": manifest.file_count,
        "total_bytes": manifest.total_bytes,
        "entries": entries,
    }


def _workspace_candidate_token(record: dict[str, object]) -> str:
    digest = hashlib.sha256(b"REPOPROOF-WORKSPACE-UI-CANDIDATE-v1\0")
    for key in (
        "blueprint_id",
        "builder_source_sha256",
        "input_sha256",
        "expected_tree_sha256",
    ):
        payload = str(record.get(key) or "").encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _workspace_candidate_record_paths(
    draft_dir: Path,
    state: dict,
    record: dict,
) -> tuple[Path, Path]:
    generation_id = str(state.get("generation_id") or "")
    if not re.fullmatch(r"generation-[0-9]+-[0-9a-f]{8}", generation_id):
        raise ValueError("WORKSPACE_CANDIDATE_GENERATION_INVALID")
    root = draft_dir / "workspace-candidates" / generation_id
    if root.is_symlink() or not root.is_dir() or _path_has_symlink(root):
        raise ValueError("WORKSPACE_CANDIDATE_ROOT_UNSAFE")
    resolved_root = root.resolve()
    paths: list[Path] = []
    for key in ("input_path", "expected_dir"):
        candidate = Path(str(record.get(key) or ""))
        if not candidate.is_absolute() or _path_has_symlink(candidate):
            raise ValueError("WORKSPACE_CANDIDATE_PATH_UNSAFE")
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("WORKSPACE_CANDIDATE_PATH_ESCAPE") from exc
        paths.append(resolved)
    return paths[0], paths[1]


def _run_workspace_reference_candidate(
    *,
    reference_source: Path,
    input_path: Path,
    expected_dir: Path,
    contract,
    python_exe: str,
    upstream_dir: Path,
    timeout_s: int = 120,
) -> dict[str, object]:
    """Build one expected workspace in an offline, disposable reference root."""

    from repoproof.execution.offline_sandbox import (
        OfflineSandboxUnavailable,
        offline_sandbox_argv,
        sanitised_subprocess_env,
    )
    from repoproof.execution.workspace_bundle import (
        WorkspaceBundleError,
        snapshot_admitted_path,
        validate_workspace,
    )

    if expected_dir.exists() or expected_dir.is_symlink():
        raise WorkspaceBundleError("WORKSPACE_EXPECTED_DESTINATION_EXISTS")
    with tempfile.TemporaryDirectory(prefix="rp-workspace-reference-") as temp:
        root = Path(temp)
        source_parent_fd = _open_absolute_directory(reference_source.parent)
        try:
            source_payload = _read_file_at(source_parent_fd, reference_source.name)
        finally:
            os.close(source_parent_fd)
        source = root / "reference_impl.py"
        source.write_bytes(source_payload)
        source.chmod(0o400)
        runner = root / "runner.py"
        runner.write_text(_WORKSPACE_REFERENCE_RUNNER, encoding="utf-8")
        runner.chmod(0o400)
        admitted_input = root / "input"
        snapshot_admitted_path(input_path, admitted_input)
        output = root / "output"
        argv = [
            python_exe,
            str(runner),
            str(source),
            str(admitted_input),
            str(output),
        ]
        try:
            argv = offline_sandbox_argv(argv, root)
        except OfflineSandboxUnavailable as exc:
            raise WorkspaceBundleError(
                "WORKSPACE_REFERENCE_ISOLATION_UNAVAILABLE"
            ) from exc
        try:
            process = subprocess.run(  # noqa: S603 - fixed argv, no shell
                argv,
                cwd=root,
                env=sanitised_subprocess_env(root, [str(upstream_dir)]),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkspaceBundleError("WORKSPACE_REFERENCE_TIMEOUT") from exc
        except OSError as exc:
            raise WorkspaceBundleError("WORKSPACE_REFERENCE_START_FAILED") from exc
        if process.returncode != 0:
            structured: dict[str, str] | None = None
            for line in reversed(process.stderr.splitlines()):
                if not line.startswith(_WORKSPACE_REFERENCE_FAILURE_PREFIX):
                    continue
                try:
                    candidate = json.loads(
                        line.removeprefix(_WORKSPACE_REFERENCE_FAILURE_PREFIX)
                    )
                except json.JSONDecodeError:
                    break
                if isinstance(candidate, dict):
                    structured = {
                        "failure_kind": str(candidate.get("failure_kind") or ""),
                        "exception_type": str(candidate.get("exception_type") or ""),
                    }
                break
            if structured is None:
                raise WorkspaceBundleError(
                    "WORKSPACE_REFERENCE_PROCESS_FAILED",
                    f"exit={process.returncode}",
                )
            code = {
                "dependency_missing": "WORKSPACE_REFERENCE_DEPENDENCY_MISSING",
                "fixture_rejected": "WORKSPACE_REFERENCE_FIXTURE_REJECTED",
                "protocol_invalid": "WORKSPACE_REFERENCE_PROTOCOL_INVALID",
                "reference_exception": "WORKSPACE_REFERENCE_EXECUTION_FAILED",
            }.get(
                structured["failure_kind"],
                "WORKSPACE_REFERENCE_PROCESS_FAILED",
            )
            raise WorkspaceBundleError(code, structured["exception_type"])
        validation = validate_workspace(output, contract)
        if not validation.ok or validation.manifest is None:
            raise WorkspaceBundleError(
                "WORKSPACE_REFERENCE_CONTRACT_FAILED",
                ",".join(validation.reason_codes),
            )
        snapshot_admitted_path(output, expected_dir, limits=contract.limits)
        return {
            "tree_sha256": validation.manifest.tree_sha256,
            "file_count": validation.manifest.file_count,
            "total_bytes": validation.manifest.total_bytes,
        }


def propose_workspace_fixture_candidates(
    draft_dir: Path,
    *,
    n: int,
    offline: bool,
) -> dict:
    """Materialise model-authored scenarios through one frozen task builder.

    The model never supplies fixture bytes.  Both online and offline buttons use
    the blueprints already bound into the current draft; ``offline`` only labels
    the user's requested mode and never changes expected truth generation.
    """

    import shutil
    from contextlib import ExitStack

    from pydantic import ValidationError

    from repoproof.adoption.intake.example_proposer import (
        prepared_reference_environment,
    )
    from repoproof.adoption.intake.tool_drafter import DraftError
    from repoproof.adoption.intake.workspace_fixtures import (
        FixtureBlueprintV1,
        FixtureBuilderError,
        InputFixtureCandidateV1,
        assert_distinct_fixture_inputs,
        build_fixture_candidate,
    )
    from repoproof.execution.core_execution import atomic_write_json
    from repoproof.execution.workspace_bundle import WorkspaceBundleError

    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=True)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir
    generation_root: Path | None = None
    try:
        draft = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8")) or {}
        if not isinstance(draft, dict):
            raise TypeError("draft.yaml root")
        readiness = _core_draft_readiness(draft, draft_dir)
        if not readiness.compatible or not readiness.current:
            return _readiness_rejection(readiness, action="生成目录样例")
        tool = _workspace_tool_from_draft(draft)
        contract = tool.workspace_contract
        assert contract is not None
        builder = draft_dir / "fixture_builder.py"
        blueprints_document = json.loads(
            (draft_dir / "fixture_blueprints.json").read_text(encoding="utf-8")
        )
        rows = blueprints_document.get("blueprints")
        if not isinstance(rows, list):
            raise ValueError("WORKSPACE_FIXTURE_BLUEPRINTS_INVALID")
        blueprints = [FixtureBlueprintV1.model_validate(item) for item in rows]
        requested = max(1, min(int(n), 4))
        if offline:
            selected = blueprints[:requested]
            drafter_name = "frozen-draft-blueprints"
        else:
            from repoproof.adoption.intake.tool_drafter import (
                normalize_workspace_fixture_blueprints_document,
                online_drafter,
            )

            drafter = online_drafter()
            proposed = drafter.propose_workspace_fixture_blueprints(
                {
                    "how_many": requested,
                    "capability_goal": str(
                        (draft.get("capability") or {}).get("statement") or ""
                    ),
                    "input_kind": tool.interface.input.kind,
                    "seed_blueprints": [
                        {
                            **item.model_dump(mode="json", exclude={"parameters"}),
                            "parameters_json": json.dumps(
                                item.parameters,
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        }
                        for item in blueprints
                    ],
                    "excluded_blueprint_ids": [],
                    "excluded_parameter_fingerprints": [],
                }
            )
            selected = [
                FixtureBlueprintV1.model_validate(item)
                for item in normalize_workspace_fixture_blueprints_document(
                    proposed,
                    input_kind=tool.interface.input.kind,
                    expected_count=requested,
                )
            ]
            drafter_name = getattr(drafter, "name", type(drafter).__name__)
        if not selected:
            raise ValueError("WORKSPACE_FIXTURE_BLUEPRINTS_EMPTY")
        upstream, upstream_error = _draft_upstream_dir(draft_dir)
        if upstream is None:
            return {
                "ok": False,
                "error": upstream_error,
                "failure_owner": "HARNESS",
                "reason_codes": ["PINNED_UPSTREAM_UNAVAILABLE"],
            }
        lock_text = resolved_dependency_lock(
            draft,
            draft_dir,
            project_root=_product_root(),
        )
        if not lock_text:
            return {
                "ok": False,
                "error": "固定上游依赖锁尚未成立；本次没有调用模型。",
                "failure_owner": "HARNESS",
                "reason_codes": ["DEPENDENCY_LOCK_MISSING"],
                "recommended_action": "先补齐精确依赖锁，再生成真实目录样例。",
            }
        generation_id = f"generation-{int(time.time())}-{secrets.token_hex(4)}"
        generation_root = draft_dir / "workspace-candidates" / generation_id
        generation_root.mkdir(parents=True, exist_ok=False)
        records: list[dict[str, object]] = []
        input_candidates: list[InputFixtureCandidateV1] = []
        stack = ExitStack()
        try:
            reference_python = stack.enter_context(
                prepared_reference_environment(
                    draft_dir,
                    wheelhouse_cache_root=ui_state_root() / "reference-wheelhouses",
                    resolved_lock_text=lock_text,
                )
            ) or _product_python()
            for blueprint in selected:
                candidate = build_fixture_candidate(
                    blueprint=blueprint,
                    builder_id="task-fixture-builder-v1",
                    builder_source=builder,
                    fixture_root=generation_root / "inputs",
                    python_exe=reference_python,
                    isolation_required=True,
                )
                input_candidates.append(candidate)
                assert_distinct_fixture_inputs(input_candidates)
                expected_dir = generation_root / "expected" / blueprint.blueprint_id
                expected = _run_workspace_reference_candidate(
                    reference_source=draft_dir / "reference_impl.py",
                    input_path=Path(candidate.fixture_path),
                    expected_dir=expected_dir,
                    contract=contract,
                    python_exe=reference_python,
                    upstream_dir=upstream,
                )
                record: dict[str, object] = {
                    "blueprint_id": blueprint.blueprint_id,
                    "title": blueprint.title,
                    "scenario": blueprint.scenario,
                    "input_kind": blueprint.input_kind,
                    "builder_source_sha256": candidate.builder_source_sha256,
                    "input_path": candidate.fixture_path,
                    "input_sha256": candidate.fixture_identity.sha256,
                    "input_file_count": candidate.fixture_identity.file_count,
                    "input_total_bytes": candidate.fixture_identity.total_bytes,
                    "expected_dir": str(expected_dir.resolve()),
                    "expected_tree_sha256": expected["tree_sha256"],
                    "expected_file_count": expected["file_count"],
                    "expected_total_bytes": expected["total_bytes"],
                    "confirmed": False,
                    "generation_id": generation_id,
                }
                record["candidate_token"] = _workspace_candidate_token(record)
                records.append(record)
        finally:
            stack.close()
        state = {
            "schema_version": 1,
            "generation_id": generation_id,
            "records": records,
        }
        atomic_write_json(draft_dir / _WORKSPACE_FIXTURE_STATE, state)
        public_records: list[dict[str, object]] = []
        for record in records:
            public_records.append(
                {
                    key: record[key]
                    for key in (
                        "blueprint_id",
                        "title",
                        "scenario",
                        "input_kind",
                        "input_sha256",
                        "input_file_count",
                        "input_total_bytes",
                        "expected_tree_sha256",
                        "expected_file_count",
                        "expected_total_bytes",
                        "candidate_token",
                        "confirmed",
                    )
                }
            )
        return {
            "ok": True,
            "drafter": drafter_name,
            "note": (
                "场景来自模型草稿，字节由冻结 fixture builder 生成，"
                "期望工作区来自固定版本上游 reference。"
            ),
            "requested": requested,
            "usable_count": len(public_records),
            "shortfall": max(0, requested - len(public_records)),
            "offline": bool(offline),
            "generation_id": generation_id,
            "candidates": public_records,
        }
    except (
        FixtureBuilderError,
        DraftError,
        WorkspaceBundleError,
        ValidationError,
        OSError,
        UnicodeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        yaml.YAMLError,
    ) as exc:
        if generation_root is not None:
            shutil.rmtree(generation_root, ignore_errors=True)
        code = str(getattr(exc, "code", type(exc).__name__.upper()))
        contract_owned = (
            code.startswith("FIXTURE_")
            or code.startswith("WORKSPACE_CONTRACT_")
            or code.startswith("WORKSPACE_REFERENCE_EXECUTION_")
            or code.startswith("WORKSPACE_REFERENCE_FIXTURE_")
            or code.startswith("WORKSPACE_REFERENCE_PROTOCOL_")
            or code.startswith("WORKSPACE_REFERENCE_DEPENDENCY_")
        )
        diagnostics = str(getattr(exc, "detail", "") or "")
        return {
            "ok": False,
            "error": f"目录样例生成失败：{code}",
            "failure_owner": "CONTRACT" if contract_owned else "HARNESS",
            "reason_codes": [code],
            "diagnostics": [diagnostics] if diagnostics else [],
            "recommended_action": (
                (
                    "冻结前的合同、fixture 或 reference 不可执行；修正公共语义并创建新的任务版本，"
                    "不要把控制面故障交给构建 Agent 盲修。"
                )
                if contract_owned
                else (
                    "修复隔离环境或执行器后从当前 Journey 重试；"
                    "本次不得消耗构建 Agent repair。"
                )
            ),
        }


def workspace_candidate_preview(
    draft_dir: Path,
    *,
    candidate_token: str,
) -> dict:
    """Return bounded trees and small text previews for one server-bound candidate."""

    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=True)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    try:
        state = json.loads((checked_dir / _WORKSPACE_FIXTURE_STATE).read_text(encoding="utf-8"))
        record = next(
            item
            for item in state.get("records") or []
            if item.get("candidate_token") == candidate_token
        )
        draft = yaml.safe_load((checked_dir / "draft.yaml").read_text(encoding="utf-8")) or {}
        tool = _workspace_tool_from_draft(draft)
        input_path, expected_dir = _workspace_candidate_record_paths(
            checked_dir,
            state,
            record,
        )
        expected = _workspace_tree_projection(
            expected_dir,
            contract=tool.workspace_contract,
        )
        from repoproof.execution.workspace_bundle import identify_input_path

        current_input = identify_input_path(input_path)
        if (
            current_input.sha256 != record.get("input_sha256")
            or expected.get("tree_sha256") != record.get("expected_tree_sha256")
        ):
            raise ValueError("WORKSPACE_CANDIDATE_CONTENT_DRIFT")
        if input_path.is_dir():
            input_tree = _workspace_tree_projection(input_path)
        else:
            input_tree = {
                "ok": True,
                "entries": [{"path": input_path.name, "size": input_path.stat().st_size}],
                "file_count": 1,
                "total_bytes": input_path.stat().st_size,
                "tree_sha256": str(record["input_sha256"]),
            }
        previews: list[dict[str, str]] = []
        raw_entries = expected.get("entries")
        entries = raw_entries if isinstance(raw_entries, list) else []
        for item in entries[:8]:
            path = expected_dir / str(item.get("path") or "")
            if int(item.get("size") or 0) > 16_384:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            previews.append({"path": str(item["path"]), "text": text[:2000]})
        return {
            "ok": bool(input_tree.get("ok") and expected.get("ok")),
            "input_tree": input_tree,
            "expected_tree": expected,
            "text_previews": previews,
        }
    except (OSError, StopIteration, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"WORKSPACE_CANDIDATE_STATE_INVALID: {exc}"}


def workspace_candidate_zip(
    draft_dir: Path,
    *,
    candidate_token: str,
) -> dict:
    """Create deterministic transport bytes without treating ZIP as evidence."""

    from repoproof.execution.workspace_bundle import write_deterministic_zip

    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=True)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    try:
        state = json.loads((checked_dir / _WORKSPACE_FIXTURE_STATE).read_text(encoding="utf-8"))
        record = next(
            item
            for item in state.get("records") or []
            if item.get("candidate_token") == candidate_token
        )
        _input_path, expected_dir = _workspace_candidate_record_paths(
            checked_dir,
            state,
            record,
        )
        actual_tree = _workspace_tree_projection(expected_dir)
        if (
            not actual_tree.get("ok")
            or actual_tree.get("tree_sha256") != record.get("expected_tree_sha256")
        ):
            raise ValueError("WORKSPACE_CANDIDATE_TREE_DRIFT")
        with tempfile.TemporaryDirectory(prefix="rp-workspace-zip-") as temp:
            archive = write_deterministic_zip(
                expected_dir,
                Path(temp) / "workspace.zip",
            )
            payload = archive.read_bytes()
        return {
            "ok": True,
            "filename": f"{record['blueprint_id']}.workspace.zip",
            "bytes": payload,
            "tree_sha256": record["expected_tree_sha256"],
            "note": "ZIP 仅用于传输；可信判定继续绑定解包前的目录树哈希。",
        }
    except (OSError, StopIteration, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"WORKSPACE_ZIP_FAILED: {exc}"}


def _validated_installed_workspace_artifact(
    tool_name: str,
    *,
    artifact_dir: Path,
    dest_root: Path,
) -> tuple[Path, object]:
    """Bind a user-selected output directory to one current Core package."""

    from repoproof.domain.models import WorkspaceArtifactContractV1
    from repoproof.ui.services.product_mode import list_tools

    name = validate_tool_name(tool_name)
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        raise ValueError(path_error)
    library = list_tools(checked_root)
    if library.get("registry_error") or library.get("release_error"):
        raise ValueError("TOOL_REGISTRY_UNREADABLE")
    entry = next(
        (row for row in library.get("tools") or [] if row.get("name") == name),
        None,
    )
    if entry is None or entry.get("health") != "OK":
        raise ValueError("PACKAGE_IDENTITY_UNHEALTHY")
    if entry.get("operational_status") != "ACTIVE":
        raise ValueError("WORKSPACE_TOOL_NOT_ACTIVE")
    if entry.get("delivery_profile_id") != "workspace_bundle_v1":
        raise ValueError("WORKSPACE_PROFILE_REQUIRED")
    package = Path(str(entry.get("path") or ""))
    if package.resolve() != canonical_tool_path(checked_root, name).resolve():
        raise ValueError("PACKAGE_IDENTITY_UNHEALTHY")
    ensure_safe_package_tree(package)
    manifest_path = package / "tool.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("PACKAGE_IDENTITY_UNHEALTHY")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = WorkspaceArtifactContractV1.model_validate(
        manifest.get("workspace_contract")
    )
    candidate = Path(artifact_dir).expanduser().absolute()
    if _path_has_symlink(candidate):
        raise ValueError("WORKSPACE_ARTIFACT_PATH_UNSAFE")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("WORKSPACE_ARTIFACT_DIRECTORY_MISSING")
    return resolved, contract


def inspect_workspace_artifact(
    tool_name: str,
    *,
    artifact_dir: Path,
    dest_root: Path,
) -> dict:
    """Validate and preview a completed workspace with the installed contract."""

    try:
        resolved, contract = _validated_installed_workspace_artifact(
            tool_name,
            artifact_dir=artifact_dir,
            dest_root=dest_root,
        )
        projection = _workspace_tree_projection(resolved, contract=contract)
        if not projection.get("ok"):
            return {
                **projection,
                "failure_owner": "HARNESS",
                "recommended_action": "不要使用或打包该目录；按 Core 原因修复后重新生成。",
            }
        return {
            **projection,
            "artifact_dir": str(resolved),
            "note": "预览来自当前目录的重新校验，不读取旧 UI 状态。",
        }
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ToolPathError,
    ) as exc:
        return {"ok": False, "error": f"WORKSPACE_ARTIFACT_INVALID: {exc}"}


def workspace_artifact_zip(
    tool_name: str,
    *,
    artifact_dir: Path,
    dest_root: Path,
) -> dict:
    """Return a deterministic transport ZIP after a fresh contract check."""

    from repoproof.execution.workspace_bundle import write_deterministic_zip

    inspected = inspect_workspace_artifact(
        tool_name,
        artifact_dir=artifact_dir,
        dest_root=dest_root,
    )
    if not inspected.get("ok"):
        return inspected
    try:
        source = Path(str(inspected["artifact_dir"]))
        with tempfile.TemporaryDirectory(prefix="rp-installed-workspace-zip-") as temp:
            archive = write_deterministic_zip(
                source,
                Path(temp) / "workspace.zip",
            )
            payload = archive.read_bytes()
        return {
            "ok": True,
            "filename": f"{validate_tool_name(tool_name)}.workspace.zip",
            "bytes": payload,
            "tree_sha256": inspected["tree_sha256"],
            "note": "ZIP 仅用于传输；可信状态仍绑定目录树、语义证据与 ledger。",
        }
    except (OSError, ValueError, ToolPathError) as exc:
        return {"ok": False, "error": f"WORKSPACE_ZIP_FAILED: {exc}"}


def open_workspace_artifact(
    tool_name: str,
    *,
    artifact_dir: Path,
    dest_root: Path,
) -> dict:
    """Open a freshly validated directory in the local file manager."""

    inspected = inspect_workspace_artifact(
        tool_name,
        artifact_dir=artifact_dir,
        dest_root=dest_root,
    )
    if not inspected.get("ok"):
        return inspected
    if sys.platform != "darwin":
        return {"ok": False, "error": "WORKSPACE_OPEN_PLATFORM_UNSUPPORTED"}
    try:
        process = subprocess.run(  # noqa: S603 - fixed local opener argv
            ["open", str(inspected["artifact_dir"])],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"WORKSPACE_OPEN_FAILED: {type(exc).__name__}"}
    if process.returncode != 0:
        return {"ok": False, "error": "WORKSPACE_OPEN_FAILED"}
    return {"ok": True, "note": "已在 Finder 中打开重新校验过的工作区。"}


def confirm_workspace_fixture_candidate(
    draft_dir: Path,
    *,
    candidate_token: str,
) -> dict:
    """Copy one exact input/output directory pair into frozen-example staging."""

    import shutil

    from repoproof.adoption.assembly.workspace_tool_assembler import (
        WorkspaceGoldenExampleV1,
        workspace_truth_binding_sha256,
    )
    from repoproof.execution.core_execution import atomic_write_json
    from repoproof.execution.workspace_bundle import (
        WorkspaceBundleError,
        build_artifact_manifest,
        identify_input_path,
        snapshot_admitted_path,
        validate_workspace,
    )

    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=True)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir
    created: list[Path] = []
    original_workspace_examples: bytes | None = None
    original_state: bytes | None = None
    original_draft: bytes | None = None
    try:
        draft = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8")) or {}
        readiness = _core_draft_readiness(draft, draft_dir)
        if not readiness.compatible or not readiness.current:
            return _readiness_rejection(readiness, action="确认目录样例")
        tool = _workspace_tool_from_draft(draft)
        contract = tool.workspace_contract
        assert contract is not None
        state_path = draft_dir / _WORKSPACE_FIXTURE_STATE
        original_state = state_path.read_bytes()
        state = json.loads(original_state.decode("utf-8"))
        records = state.get("records") or []
        record = next(
            item
            for item in records
            if item.get("candidate_token") == candidate_token
        )
        if record.get("confirmed"):
            return {"ok": True, "note": "该目录样例已经确认，无需重复写入。"}
        if _workspace_candidate_token(record) != candidate_token:
            raise ValueError("WORKSPACE_CANDIDATE_BINDING_INVALID")
        input_source, expected_source = _workspace_candidate_record_paths(
            draft_dir,
            state,
            record,
        )
        actual_input = identify_input_path(input_source)
        actual_expected = build_artifact_manifest(expected_source, contract.limits)
        if (
            actual_input.sha256 != record.get("input_sha256")
            or actual_expected.tree_sha256 != record.get("expected_tree_sha256")
        ):
            raise ValueError("WORKSPACE_CANDIDATE_CONTENT_DRIFT")
        if validate_workspace(expected_source, contract).ok is not True:
            raise ValueError("WORKSPACE_EXPECTED_CONTRACT_DRIFT")
        slug = str(record["blueprint_id"])
        examples_root = draft_dir / "examples"
        input_destination = examples_root / "workspace-inputs" / slug
        expected_destination = examples_root / "workspace-expected" / slug
        input_identity = snapshot_admitted_path(input_source, input_destination)
        created.append(input_destination)
        snapshot_admitted_path(
            expected_source,
            expected_destination,
            limits=contract.limits,
        )
        created.append(expected_destination)
        expected_manifest = build_artifact_manifest(
            expected_destination,
            contract.limits,
        )
        binding = workspace_truth_binding_sha256(
            input_identity.sha256,
            expected_manifest.tree_sha256,
        )
        example = WorkspaceGoldenExampleV1(
            example_id=slug,
            input_path=input_destination.relative_to(examples_root).as_posix(),
            expected_dir=expected_destination.relative_to(examples_root).as_posix(),
            truth_provenance="UPSTREAM_DERIVED_USER_CONFIRMED",
            truth_binding_sha256=binding,
        )
        examples_path = draft_dir / "workspace_examples.yaml"
        original_workspace_examples = examples_path.read_bytes()
        document = yaml.safe_load(
            original_workspace_examples.decode("utf-8")
        ) or {"examples": []}
        if not isinstance(document, dict) or not isinstance(document.get("examples"), list):
            raise TypeError("workspace_examples.yaml root")
        if any(item.get("example_id") == slug for item in document["examples"]):
            raise ValueError("WORKSPACE_EXAMPLE_ID_EXISTS")
        document["examples"].append(example.model_dump(mode="json"))
        draft_fd = _open_absolute_directory(draft_dir)
        try:
            _replace_file_at(
                draft_fd,
                "workspace_examples.yaml",
                yaml.safe_dump(document, allow_unicode=True, sort_keys=False).encode("utf-8"),
            )
        finally:
            os.close(draft_fd)
        record["confirmed"] = True
        atomic_write_json(state_path, state)
        original_draft = (draft_dir / "draft.yaml").read_bytes()
        invalidate_intent_confirmation(draft)
        draft_fd = _open_absolute_directory(draft_dir)
        try:
            _replace_file_at(
                draft_fd,
                "draft.yaml",
                yaml.safe_dump(draft, allow_unicode=True, sort_keys=False).encode("utf-8"),
            )
        finally:
            os.close(draft_fd)
        return {
            "ok": True,
            "note": f"已确认目录样例：{slug}",
            "truth_binding_sha256": binding,
        }
    except (
        WorkspaceBundleError,
        OSError,
        StopIteration,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        yaml.YAMLError,
    ) as exc:
        for path in reversed(created):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        restore_fd: int | None = None
        try:
            restore_fd = _open_absolute_directory(draft_dir)
            if original_workspace_examples is not None:
                _replace_file_at(
                    restore_fd,
                    "workspace_examples.yaml",
                    original_workspace_examples,
                )
            if original_draft is not None:
                _replace_file_at(restore_fd, "draft.yaml", original_draft)
        except OSError:
            pass
        finally:
            if restore_fd is not None:
                os.close(restore_fd)
        if original_state is not None:
            try:
                (draft_dir / _WORKSPACE_FIXTURE_STATE).write_bytes(original_state)
            except OSError:
                pass
        return {"ok": False, "error": f"目录样例确认失败：{exc}"}


def product_tool_commands() -> set[str]:
    root = _product_root()
    try:
        proc = subprocess.run(
            [_product_python(root), "-m", "repoproof.cli", "tool", "--help"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        text = proc.stdout + proc.stderr
    except (OSError, subprocess.SubprocessError):
        return set()
    return {name for name in ("add", "build", "list", "mcp", "audit", "withdraw") if name in text}


def start_tool_mcp(name: str, dest_root: Path, *, journey_id: str = "") -> dict:
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": path_error}
    dest_root = checked_root  # 判空后再回赋,同上
    try:
        name = validate_tool_name(name)
    except ToolPathError as exc:
        return {"ok": False, "error": str(exc)}
    root = _product_root()
    expected = Path(dest_root) / name / "mcp_server.py"
    return _start_product_job(
        [
            _product_python(root),
            "-m",
            "repoproof.cli",
            "tool",
            "mcp",
            name,
            "--dest-root",
            str(dest_root),
        ],
        kind="tool-mcp",
        label=f"生成 {name} MCP 适配器",
        expected_artifact=expected,
        journey_id=journey_id,
        metadata={"tool_name": name, "dest_root": str(dest_root), "journey_stage": 5},
    )


def _public_example_inputs(tool_dir: Path) -> tuple[list[str], list[str]]:
    """Load only agent-visible input fixtures for Fresh-audit deduplication.

    The exported truth table identifies which fixture is an input, so expected
    files are never fed back as candidate context. Held-out fixtures are absent
    from the package by construction and are therefore never exposed here.
    """

    truth_table = tool_dir / "public_examples" / "truth_table.json"
    if not truth_table.is_file():
        return [], []
    document = json.loads(truth_table.read_text(encoding="utf-8"))
    examples = document.get("examples") if isinstance(document, dict) else None
    if not isinstance(examples, list):
        raise ValueError("公开样例索引不是有效的 examples 列表")
    package_fixture_root = tool_dir / "public_examples" / "inputs"
    if package_fixture_root.is_symlink() or not package_fixture_root.is_dir():
        raise ValueError(
            "工具包没有受管的 public_examples/inputs；这是旧导出格式，"
            "请创建新 task version 并重新构建，不能用骨架旁路 Fresh audit。"
        )
    fixture_root = package_fixture_root.resolve()
    texts: list[str] = []
    names: list[str] = []
    for row in examples[:20]:
        if not isinstance(row, dict):
            raise ValueError("公开样例索引包含非对象条目")
        relative = row.get("input_file")
        if not isinstance(relative, str) or not relative:
            continue
        candidate = fixture_root / relative
        resolved = candidate.resolve()
        try:
            resolved.relative_to(fixture_root)
        except ValueError as exc:
            raise ValueError("公开输入 fixture 越出受管目录") from exc
        if candidate.is_symlink():
            raise ValueError("公开输入 fixture 不得是符号链接")
        if not resolved.is_file():
            raise ValueError("公开输入 fixture 缺失或不是普通文件")
        payload = resolved.read_bytes()
        if len(payload) > 1_000_000:
            raise ValueError("公开输入 fixture 超过 Fresh-audit 候选上下文上限")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            # Current candidate-generation contract is UTF-8 text only. Binary
            # public fixtures cannot safely become LLM context and are skipped.
            continue
        texts.append(text)
        names.append(Path(relative).name)
    return texts, names


def _verify_pinned_upstream_tree(upstream: Path, expected_commit: str) -> None:
    """Fail closed when a cached upstream no longer represents the frozen commit."""

    if upstream.is_symlink() or not upstream.is_dir():
        raise ValueError("钉版上游树缺失或是符号链接")
    head = subprocess.run(
        ["git", "-C", str(upstream), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if head.returncode != 0 or head.stdout.strip() != expected_commit:
        raise ValueError("钉版上游树 HEAD 与冻结合同不一致")
    for argv in (
        ["git", "-C", str(upstream), "diff", "--quiet", "--no-ext-diff", "--"],
        ["git", "-C", str(upstream), "diff", "--cached", "--quiet", "--no-ext-diff", "--"],
    ):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise ValueError("钉版上游树含已跟踪内容漂移")
    status = subprocess.run(
        ["git", "-C", str(upstream), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if status.returncode != 0:
        raise ValueError("无法核验钉版上游工作树")
    for line in status.stdout.splitlines():
        if not line.startswith("?? "):
            continue  # tracked changes were rejected by git diff above
        relative = line[3:].strip().strip('"')
        parts = Path(relative).parts
        cache_only = "__pycache__" in parts or ".pytest_cache" in parts or relative.endswith((".pyc", ".pyo"))
        if not cache_only:
            raise ValueError("钉版上游树含未跟踪内容漂移")


def _verify_frozen_reference_identity(
    *,
    tool_dir: Path,
    registry_entry: dict,
    task_id: str,
    tool_name: str,
    ref_impl: Path,
    ref_lock: Path,
) -> dict[str, str]:
    """Bind Fresh-audit truth to the exact reference pair frozen at export.

    Four independently read values must agree before a drafter is selected:
    package provenance, registry index, current reference implementation, and
    current reference dependency lock.  Legacy packages without this identity
    must be rebuilt as a new task version; silently blessing today's mutable
    controls as yesterday's truth would defeat the purpose of the binding.
    """

    from repoproof.runner.tool_registry import validate_reference_identity

    provenance_path = tool_dir / "evidence" / "provenance.json"
    if provenance_path.is_symlink() or not provenance_path.is_file():
        raise ValueError("受管包 provenance 缺失或不是普通文件")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("受管包 provenance 无法安全读取") from exc
    if not isinstance(provenance, dict):
        raise ValueError("受管包 provenance 必须是 JSON object")
    if provenance.get("tool") != tool_name or provenance.get("task_id") != task_id:
        raise ValueError("受管包 provenance 与当前工具/task 不一致")

    package_identity = validate_reference_identity(provenance.get("reference_identity"), required=True)
    registry_identity = validate_reference_identity(registry_entry.get("reference_identity"), required=True)

    reference_dir = ref_impl.parent
    if reference_dir.is_symlink() or not reference_dir.is_dir() or reference_dir.resolve() != reference_dir.absolute():
        raise ValueError("冻结 reference 目录缺失或包含符号链接")

    def regular_digest(path: Path) -> str:
        if path.parent != reference_dir or path.is_symlink() or not path.is_file():
            raise ValueError(f"冻结 reference 文件缺失或不是普通文件:{path.name}")
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ValueError(f"冻结 reference 文件无法读取:{path.name}") from exc

    current_identity = {
        "impl_sha256": regular_digest(ref_impl),
        "lock_sha256": regular_digest(ref_lock),
    }
    if package_identity != registry_identity or package_identity != current_identity:
        raise ValueError("package/registry/controls reference_identity 不一致")
    return current_identity


def _reference_identity_error(exc: Exception) -> dict:
    return {
        "ok": False,
        "error": f"冻结 reference 身份核验失败：{exc}",
        "failure_owner": "HARNESS",
        "reason_codes": ["REFERENCE_IDENTITY_MISMATCH"],
        "recommended_action": ("不要改写旧 reference；创建新的 task version 并重新构建、导出后再做 Fresh audit。"),
    }


def _audit_candidate_context(
    *,
    tool_name: str,
    task_id: str,
    dest_root: Path,
) -> str:
    return "audit-v1:" + json.dumps(
        {
            "tool_name": tool_name,
            "task_id": task_id,
            "dest_root": str(Path(dest_root).resolve()),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _workspace_audit_candidate_store(
    *,
    tool_name: str,
    task_id: str,
    dest_root: Path,
) -> Path:
    context = _audit_candidate_context(
        tool_name=tool_name,
        task_id=task_id,
        dest_root=dest_root,
    ).replace("audit-v1:", "workspace-audit-v1:", 1)
    key = hashlib.sha256(context.encode("utf-8")).hexdigest()
    root = ui_state_root() / "workspace-audit-candidates" / key
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or _path_has_symlink(root):
        raise ValueError("WORKSPACE_AUDIT_STORE_UNSAFE")
    return root


def _workspace_audit_record_paths(
    store: Path,
    state: dict,
    record: dict,
) -> tuple[Path, Path]:
    generation_id = str(state.get("generation_id") or "")
    if not re.fullmatch(r"generation-[0-9]+-[0-9a-f]{8}", generation_id):
        raise ValueError("WORKSPACE_AUDIT_GENERATION_INVALID")
    generation = store / generation_id
    if generation.is_symlink() or not generation.is_dir() or _path_has_symlink(generation):
        raise ValueError("WORKSPACE_AUDIT_GENERATION_UNSAFE")
    root = generation.resolve()
    result: list[Path] = []
    for key in ("input_path", "expected_dir"):
        path = Path(str(record.get(key) or ""))
        if not path.is_absolute() or _path_has_symlink(path):
            raise ValueError("WORKSPACE_AUDIT_PATH_UNSAFE")
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("WORKSPACE_AUDIT_PATH_ESCAPE") from exc
        result.append(resolved)
    return result[0], result[1]


def _propose_workspace_audit_candidates(
    *,
    name: str,
    task_id: str,
    checked_root: Path,
    root: Path,
    contract,
    ref_impl: Path,
    ref_lock: Path,
    upstream: Path,
    n: int,
    offline: bool,
) -> dict:
    """Generate directory Fresh-audit inputs from the frozen task builder."""

    import shutil
    from contextlib import ExitStack

    from pydantic import ValidationError

    from repoproof.adoption.intake.example_proposer import (
        ReferenceEnvironmentError,
        prepared_reference_environment,
    )
    from repoproof.adoption.intake.tool_drafter import (
        DraftError,
        normalize_workspace_fixture_blueprints_document,
        online_drafter,
    )
    from repoproof.adoption.intake.workspace_fixtures import (
        FixtureBlueprintV1,
        FixtureBuilderError,
        build_fixture_candidate,
    )
    from repoproof.execution.core_execution import atomic_write_json
    from repoproof.execution.workspace_bundle import (
        WorkspaceBundleError,
        identify_input_path,
    )
    from repoproof.harness.task_package import load_and_verify

    tool = contract.tool
    if (
        tool is None
        or tool.schema_version != 4
        or tool.delivery_profile_id != "workspace_bundle_v1"
        or tool.workspace_contract is None
    ):
        return {
            "ok": False,
            "error": "冻结任务不是 workspace_bundle_v1。",
            "failure_owner": "CONTRACT",
            "reason_codes": ["WORKSPACE_PROFILE_REQUIRED"],
        }
    generation_root: Path | None = None
    try:
        load_and_verify(root, root / "contracts" / f"{task_id}.yaml")
        oracle = root / "oracle" / task_id
        builder = oracle / "fixture_builder.py"
        blueprint_path = oracle / "fixture_blueprints.json"
        if (
            builder.is_symlink()
            or not builder.is_file()
            or blueprint_path.is_symlink()
            or not blueprint_path.is_file()
        ):
            raise ValueError("FROZEN_FIXTURE_ASSETS_MISSING")
        document = json.loads(blueprint_path.read_text(encoding="utf-8"))
        raw_seeds = document.get("blueprints") if isinstance(document, dict) else None
        if not isinstance(raw_seeds, list):
            raise ValueError("FROZEN_FIXTURE_BLUEPRINTS_INVALID")
        seeds = [FixtureBlueprintV1.model_validate(item) for item in raw_seeds]
        fixture_root = oracle / "fixtures"
        existing_input_hashes = {
            identify_input_path(path).sha256
            for path in fixture_root.glob("*/input")
            if not path.is_symlink() and (path.is_file() or path.is_dir())
        }
        requested = max(1, min(int(n), 4))
        if offline:
            proposed = seeds
            drafter_name = "frozen-unused-blueprints"
        else:
            drafter = online_drafter()
            response = drafter.propose_workspace_fixture_blueprints(
                {
                    "how_many": requested,
                    "capability_goal": str(contract.capability.statement or ""),
                    "input_kind": tool.interface.input.kind,
                    "seed_blueprints": [
                        {
                            **item.model_dump(mode="json", exclude={"parameters"}),
                            "parameters_json": json.dumps(
                                item.parameters,
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        }
                        for item in seeds
                    ],
                    "excluded_blueprint_ids": [item.blueprint_id for item in seeds],
                    "excluded_parameter_fingerprints": [
                        hashlib.sha256(
                            json.dumps(
                                item.parameters,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        for item in seeds
                    ],
                }
            )
            proposed = [
                FixtureBlueprintV1.model_validate(item)
                for item in normalize_workspace_fixture_blueprints_document(
                    response,
                    input_kind=tool.interface.input.kind,
                    expected_count=requested,
                )
            ]
            drafter_name = getattr(drafter, "name", type(drafter).__name__)
        store = _workspace_audit_candidate_store(
            tool_name=name,
            task_id=task_id,
            dest_root=checked_root,
        )
        generation_id = f"generation-{int(time.time())}-{secrets.token_hex(4)}"
        generation_root = store / generation_id
        generation_root.mkdir(parents=True, exist_ok=False)
        temporary_draft = generation_root / "reference-environment"
        temporary_draft.mkdir()
        shutil.copy2(ref_lock, temporary_draft / "reference.lock.txt")
        records: list[dict[str, object]] = []
        stack = ExitStack()
        try:
            reference_python = stack.enter_context(
                prepared_reference_environment(
                    temporary_draft,
                    wheelhouse_cache_root=ui_state_root() / "reference-wheelhouses",
                )
            ) or _product_python()
            for blueprint in proposed:
                candidate = build_fixture_candidate(
                    blueprint=blueprint,
                    builder_id=f"{task_id}-fixture-builder-v1",
                    builder_source=builder,
                    fixture_root=generation_root / "inputs",
                    python_exe=reference_python,
                    isolation_required=True,
                )
                if candidate.fixture_identity.sha256 in existing_input_hashes:
                    continue
                expected_dir = generation_root / "expected" / blueprint.blueprint_id
                expected = _run_workspace_reference_candidate(
                    reference_source=ref_impl,
                    input_path=Path(candidate.fixture_path),
                    expected_dir=expected_dir,
                    contract=tool.workspace_contract,
                    python_exe=reference_python,
                    upstream_dir=upstream,
                )
                record: dict[str, object] = {
                    "blueprint_id": blueprint.blueprint_id,
                    "title": blueprint.title,
                    "scenario": blueprint.scenario,
                    "input_kind": blueprint.input_kind,
                    "builder_source_sha256": candidate.builder_source_sha256,
                    "input_path": candidate.fixture_path,
                    "input_sha256": candidate.fixture_identity.sha256,
                    "input_file_count": candidate.fixture_identity.file_count,
                    "input_total_bytes": candidate.fixture_identity.total_bytes,
                    "expected_dir": str(expected_dir.resolve()),
                    "expected_tree_sha256": expected["tree_sha256"],
                    "expected_file_count": expected["file_count"],
                    "expected_total_bytes": expected["total_bytes"],
                    "generation_id": generation_id,
                    "confirmed": False,
                }
                record["candidate_token"] = _workspace_candidate_token(record)
                records.append(record)
                if len(records) >= requested:
                    break
        finally:
            stack.close()
        if not records:
            raise ValueError("FRESH_WORKSPACE_BLUEPRINT_MISSING")
        state = {
            "schema_version": 1,
            "tool_name": name,
            "task_id": task_id,
            "dest_root": str(checked_root),
            "generation_id": generation_id,
            "records": records,
        }
        atomic_write_json(store / "state.json", state)
        return {
            "ok": True,
            "tool_name": name,
            "task_id": task_id,
            "dest_root": str(checked_root),
            "artifact_kind": "directory",
            "delivery_profile_id": "workspace_bundle_v1",
            "drafter": drafter_name,
            "candidates": [
                {
                    key: record[key]
                    for key in (
                        "blueprint_id",
                        "title",
                        "scenario",
                        "input_kind",
                        "input_sha256",
                        "input_file_count",
                        "input_total_bytes",
                        "expected_tree_sha256",
                        "expected_file_count",
                        "expected_total_bytes",
                        "candidate_token",
                    )
                }
                for record in records
            ],
            "note": (
                "新鲜输入由模型场景或冻结未用场景提出，真实字节来自冻结 builder；"
                "期望目录来自冻结 reference，且输入身份未出现在构建/held-out fixtures 中。"
            ),
        }
    except ReferenceEnvironmentError as exc:
        code = exc.reason_code
        owner = "HARNESS"
    except DraftError as exc:
        code = str(exc)
        owner = "EXTERNAL"
    except (
        FixtureBuilderError,
        WorkspaceBundleError,
        ValidationError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        code = str(getattr(exc, "code", str(exc) or type(exc).__name__))
        owner = "HARNESS"
    if generation_root is not None:
        shutil.rmtree(generation_root, ignore_errors=True)
    return {
        "ok": False,
        "error": f"Fresh workspace 候选生成失败：{code}",
        "failure_owner": owner,
        "reason_codes": [code],
        "recommended_action": (
            "修复网关、冻结 fixture 资产或依赖环境后重试；本次不进入 Agent repair。"
        ),
    }


def _load_workspace_audit_candidate(
    tool_name: str,
    *,
    dest_root: Path,
    expected_task_id: str,
    candidate_token: str,
) -> tuple[Path, Path, dict[str, object], object]:
    """Reload one server-owned directory candidate and recheck every binding."""

    from repoproof.domain.models import TaskContract
    from repoproof.execution.workspace_bundle import (
        identify_input_path,
        validate_workspace,
    )
    from repoproof.harness.task_package import load_and_verify
    from repoproof.ui.services.product_mode import list_tools, project_root

    name = validate_tool_name(tool_name)
    task_id = validate_tool_task_id(name, expected_task_id)
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        raise ValueError(path_error)
    library = list_tools(checked_root)
    if library.get("registry_error") or library.get("release_error"):
        raise ValueError("TOOL_REGISTRY_UNREADABLE")
    entry = next(
        (row for row in library.get("tools") or [] if row.get("name") == name),
        None,
    )
    if entry is None or str(entry.get("task_id") or "") != task_id:
        raise ValueError("TASK_IDENTITY_MISMATCH")
    if str(entry.get("health") or "") != "OK":
        raise ValueError("PACKAGE_IDENTITY_UNHEALTHY")
    package_path = entry.get("path")
    if not isinstance(package_path, str) or not package_path:
        raise ValueError("PACKAGE_IDENTITY_UNHEALTHY")
    package_dir = Path(package_path)
    if package_dir.resolve() != canonical_tool_path(checked_root, name).resolve():
        raise ValueError("PACKAGE_IDENTITY_UNHEALTHY")
    ensure_safe_package_tree(package_dir)

    project = project_root()
    contract_path = project / "contracts" / f"{task_id}.yaml"
    load_and_verify(project, contract_path)
    contract, _contract_sha = TaskContract.load_frozen(
        contract_path,
        require_sidecar=True,
    )
    tool = contract.tool
    if (
        tool is None
        or tool.schema_version != 4
        or tool.delivery_profile_id != "workspace_bundle_v1"
        or tool.workspace_contract is None
    ):
        raise ValueError("WORKSPACE_PROFILE_REQUIRED")

    store = _workspace_audit_candidate_store(
        tool_name=name,
        task_id=task_id,
        dest_root=checked_root,
    )
    state_path = store / "state.json"
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError("WORKSPACE_AUDIT_STATE_MISSING")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("WORKSPACE_AUDIT_STATE_INVALID")
    if (
        state.get("tool_name") != name
        or state.get("task_id") != task_id
        or state.get("dest_root") != str(checked_root)
    ):
        raise ValueError("WORKSPACE_AUDIT_CONTEXT_MISMATCH")
    records = state.get("records")
    if not isinstance(records, list):
        raise ValueError("WORKSPACE_AUDIT_STATE_INVALID")
    record = next(
        item
        for item in records
        if isinstance(item, dict) and item.get("candidate_token") == candidate_token
    )
    if _workspace_candidate_token(record) != candidate_token:
        raise ValueError("WORKSPACE_AUDIT_BINDING_INVALID")
    input_path, expected_dir = _workspace_audit_record_paths(store, state, record)
    input_identity = identify_input_path(input_path)
    validation = validate_workspace(expected_dir, tool.workspace_contract)
    if not validation.ok or validation.manifest is None:
        raise ValueError("WORKSPACE_AUDIT_EXPECTED_CONTRACT_DRIFT")
    if (
        input_identity.sha256 != record.get("input_sha256")
        or validation.manifest.tree_sha256 != record.get("expected_tree_sha256")
    ):
        raise ValueError("WORKSPACE_AUDIT_CONTENT_DRIFT")
    return input_path, expected_dir, record, tool.workspace_contract


def workspace_audit_candidate_preview(
    tool_name: str,
    *,
    dest_root: Path,
    expected_task_id: str,
    candidate_token: str,
) -> dict:
    """Project a bounded input/output tree without exposing managed paths."""

    try:
        input_path, expected_dir, record, contract = _load_workspace_audit_candidate(
            tool_name,
            dest_root=dest_root,
            expected_task_id=expected_task_id,
            candidate_token=candidate_token,
        )
        input_tree = (
            _workspace_tree_projection(input_path)
            if input_path.is_dir()
            else {
                "ok": True,
                "entries": [
                    {"path": input_path.name, "size": input_path.stat().st_size}
                ],
                "file_count": 1,
                "total_bytes": input_path.stat().st_size,
                "tree_sha256": str(record["input_sha256"]),
            }
        )
        expected_tree = _workspace_tree_projection(expected_dir, contract=contract)
        previews: list[dict[str, str]] = []
        entries = expected_tree.get("entries")
        for item in entries if isinstance(entries, list) else []:
            if len(previews) >= 8 or int(item.get("size") or 0) > 16_384:
                continue
            path = expected_dir / str(item.get("path") or "")
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            previews.append({"path": str(item["path"]), "text": text[:2000]})
        return {
            "ok": bool(input_tree.get("ok") and expected_tree.get("ok")),
            "input_tree": input_tree,
            "expected_tree": expected_tree,
            "text_previews": previews,
        }
    except (
        OSError,
        StopIteration,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ToolPathError,
    ) as exc:
        return {
            "ok": False,
            "error": f"WORKSPACE_AUDIT_CANDIDATE_INVALID: {exc}",
            "failure_owner": "HARNESS",
            "reason_codes": ["WORKSPACE_AUDIT_CANDIDATE_INVALID"],
        }


def materialize_workspace_audit_candidate(
    tool_name: str,
    *,
    dest_root: Path,
    expected_task_id: str,
    candidate_token: str,
) -> dict:
    """Return an exact managed directory pair after revalidating frozen truth."""

    try:
        input_path, expected_dir, record, _contract = _load_workspace_audit_candidate(
            tool_name,
            dest_root=dest_root,
            expected_task_id=expected_task_id,
            candidate_token=candidate_token,
        )
        return {
            "ok": True,
            "input": str(input_path),
            "expected": str(expected_dir),
            "input_sha256": record["input_sha256"],
            "expected_tree_sha256": record["expected_tree_sha256"],
        }
    except (
        OSError,
        StopIteration,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ToolPathError,
    ) as exc:
        return {
            "ok": False,
            "error": f"Fresh workspace 候选受管证据核验失败：{exc}",
            "failure_owner": "HARNESS",
            "reason_codes": ["WORKSPACE_AUDIT_CANDIDATE_INVALID"],
            "recommended_action": "丢弃旧候选并重新生成；不要手工搬运期望目录。",
        }


def propose_audit_candidates(
    tool_name: str,
    *,
    dest_root: Path,
    expected_task_id: str,
    n: int = 4,
    offline: bool = False,
) -> dict:
    """给「新输入抽查」出候选:输入由模型出,**期望值由冻结的 reference 真跑**。

    用户原话:"我可能给出颜色的名字,但是希望得到的预期输出不一定知道"——
    让人从零手写一个逐字节正确的期望值门槛太高,写错还会误撤回一个好工具
    (2026-08-28 实录)。

    **红线**:期望值绝不能来自**被测工具自己** —— 那样抽查就成了自证,
    永远通过,也就永远抓不出 pyspellchecker 那类 false-success。这里用的是
    `controls/<task>/reference/impl.py`:出题期冻结的参考实现,按纪律必须
    真 import 钉版上游,与交付物是两条独立实现路径,所以"工具输出 == 参考
    输出"仍有判别力。最后仍由人逐条确认 —— 系统只把"从零创造"降成"看一眼"。
    """
    import shutil
    import tempfile
    from contextlib import ExitStack

    from repoproof.adoption.intake.example_proposer import (
        ExampleProposalError,
        ProposalBatch,
        ReferenceEnvironmentError,
        mine_evidence_literals,
        prepared_reference_environment,
        propose_inputs,
        reference_wheelhouse_runtime_identity,
        run_reference_on_candidates,
    )
    from repoproof.adoption.intake.tool_drafter import DraftError, FakeDrafter, online_drafter
    from repoproof.ui.services.product_mode import list_tools, project_root

    try:
        name = validate_tool_name(tool_name)
    except ToolPathError as exc:
        return {"ok": False, "error": str(exc)}
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": path_error}
    expected_task_id = str(expected_task_id or "").strip()
    if not expected_task_id:
        return {"ok": False, "error": "Journey 没有绑定 task_id，不能生成 Fresh audit 真值。"}
    root = project_root()
    library = list_tools(checked_root)
    if library.get("registry_error") or library.get("release_error"):
        return {
            "ok": False,
            "error": library.get("registry_error") or library.get("release_error"),
            "failure_owner": "HARNESS",
            "reason_codes": ["TOOL_REGISTRY_UNREADABLE"],
            "recommended_action": "修复工具 registry 或 release ledger 后重试；本次没有调用模型。",
        }
    entry = next((r for r in library["tools"] if r["name"] == name), None)
    task_id = str((entry or {}).get("task_id") or "")
    if not task_id:
        return {"ok": False, "error": f"找不到 {name} 的冻结任务,无法出候选。"}
    if task_id != expected_task_id:
        return {
            "ok": False,
            "error": (
                f"Journey 绑定 {expected_task_id}，但当前 registry 指向 {task_id}；"
                "拒绝用另一个版本的 reference 生成真值。"
            ),
            "failure_owner": "HARNESS",
            "reason_codes": ["TASK_IDENTITY_MISMATCH"],
            "recommended_action": "返回最近任务并刷新状态；如已升级，请创建或选择对应的新 Journey。",
        }
    try:
        package_path = (entry or {}).get("path")
        if not isinstance(package_path, str) or not package_path:
            raise ToolPathError("Core registry 没有给出受管工具目录")
        tool_dir = Path(package_path)
        if tool_dir.resolve() != canonical_tool_path(checked_root, name).resolve():
            raise ToolPathError("Core registry 的工具目录与受管身份不一致")
        if tool_dir.is_symlink() or not tool_dir.is_dir():
            raise ToolPathError("受管工具目录缺失或是符号链接")
        ensure_safe_package_tree(tool_dir)
    except (OSError, ToolPathError, ValueError) as exc:
        return {
            "ok": False,
            "error": str(exc),
            "failure_owner": "HARNESS",
            "reason_codes": ["PACKAGE_IDENTITY_UNHEALTHY"],
            "recommended_action": "先修复或重新导出受管工具包，再生成 Fresh audit 候选。",
        }
    ref_impl = root / "controls" / task_id / "reference" / "impl.py"
    ref_lock = root / "controls" / task_id / "reference" / "requirements.lock.txt"
    upstream_commit = str((entry or {}).get("resolved_commit") or "")
    upstream = root / "upstream-cache" / f"upstream-{upstream_commit[:12]}"
    try:
        _verify_frozen_reference_identity(
            tool_dir=tool_dir,
            registry_entry=entry or {},
            task_id=task_id,
            tool_name=name,
            ref_impl=ref_impl,
            ref_lock=ref_lock,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return _reference_identity_error(exc)
    if entry is not None and str(entry.get("health") or "") != "OK":
        return {
            "ok": False,
            "error": (f"工具包健康状态为 {entry.get('health') or 'UNKNOWN'}，拒绝生成 Fresh audit 真值。"),
            "failure_owner": "HARNESS",
            "reason_codes": ["PACKAGE_IDENTITY_UNHEALTHY"],
            "recommended_action": "先修复或重新导出受管工具包，再生成 Fresh audit 候选。",
        }
    if not upstream.is_dir():
        return {"ok": False, "error": f"钉版上游树不在:{upstream}"}
    contract_path = root / "contracts" / f"{task_id}.yaml"

    tmp = Path(tempfile.mkdtemp(prefix="rp-audit-propose-"))
    try:
        from repoproof.domain.models import TaskContract

        contract, _contract_sha256 = TaskContract.load_frozen(
            contract_path,
            require_sidecar=True,
        )
        if contract.task_id != task_id:
            raise ValueError("冻结合同 task_id 与 Journey 不一致")
        if contract.source_repo.resolved_commit != upstream_commit:
            raise ValueError("冻结合同 upstream commit 与 registry 不一致")
        _verify_pinned_upstream_tree(upstream, upstream_commit)
        capability_goal = str(contract.capability.statement or "").strip()
        if not capability_goal:
            raise ValueError("冻结合同没有 capability statement")
        contract_tool = getattr(contract, "tool", None)
        if (
            contract_tool is not None
            and contract_tool.schema_version == 4
            and contract_tool.delivery_profile_id == "workspace_bundle_v1"
        ):
            return _propose_workspace_audit_candidates(
                name=name,
                task_id=task_id,
                checked_root=checked_root,
                root=root,
                contract=contract,
                ref_impl=ref_impl,
                ref_lock=ref_lock,
                upstream=upstream,
                n=n,
                offline=offline,
            )
        frozen_intent = contract.capability.intent_contract
        if frozen_intent is None or not frozen_intent.commitments:
            return {
                "ok": False,
                "error": "冻结合同缺少候选所需的公开承诺目录。",
                "failure_owner": "CONTRACT",
                "reason_codes": ["AUDIT_CANDIDATE_COMMITMENTS_MISSING"],
                "recommended_action": ("创建新的 task version；不要为历史合同静默补写行为绑定。"),
            }
        public_commitments = (
            [
                {
                    "commitment_id": item.commitment_id,
                    "public_text": item.public_text,
                }
                for item in frozen_intent.commitments
            ]
            if frozen_intent is not None
            else []
        )
        reference_import_module = str(contract.source_repo.import_module or "").strip()
        if not reference_import_module:
            raise ValueError("冻结合同没有 reference import_module")
        existing_inputs, existing_names = _public_example_inputs(tool_dir)
        # 组一个**临时 draft 束形态**给既有的执行器用:只读地拷一份冻结
        # reference,不碰任何冻结件(controls/ 是不可改写的证据面)。
        (tmp / "examples" / "inputs").mkdir(parents=True)
        shutil.copy2(ref_impl, tmp / "reference_impl.py")
        if ref_lock.is_file():
            shutil.copy2(ref_lock, tmp / "reference.lock.txt")
        stack = ExitStack()
        reference_python = stack.enter_context(
            prepared_reference_environment(
                tmp,
                wheelhouse_cache_root=ui_state_root() / "reference-wheelhouses",
            )
        )
        runtime_artifact_sha256 = reference_wheelhouse_runtime_identity(
            tmp / "reference.lock.txt",
            cache_root=ui_state_root() / "reference-wheelhouses",
        )
        # 在任何模型调用前验证依赖闭包与 reference 导入。环境/合同故障
        # 不应消耗一次候选生成调用，更不能伪装成 Agent repair。
        run_reference_on_candidates(
            ProposalBatch(candidates=[]),
            draft_dir=tmp,
            upstream_dir=upstream,
            python_exe=reference_python,
            isolation_required=True,
            import_module=reference_import_module,
            runtime_artifact_sha256=runtime_artifact_sha256,
        )
        drafter = FakeDrafter() if offline else online_drafter()
        batch = propose_inputs(
            goal=capability_goal[:6000],
            overview={
                "repository": str((entry or {}).get("source_url") or ""),
                "evidence_literals": mine_evidence_literals(upstream),
                "public_commitments": public_commitments,
            },
            drafter=drafter,
            n=n,
            existing_inputs=existing_inputs,
            existing_names=existing_names,
        )
        cands = run_reference_on_candidates(
            batch,
            draft_dir=tmp,
            upstream_dir=upstream,
            python_exe=reference_python,
            isolation_required=True,
            import_module=reference_import_module,
            runtime_artifact_sha256=runtime_artifact_sha256,
        )
        stack.close()
    except ReferenceEnvironmentError as exc:
        return {
            "ok": False,
            "error": _public_reference_environment_error(exc.reason_code),
            "failure_owner": "HARNESS",
            "reason_codes": [exc.reason_code],
            "recommended_action": "检查依赖锁与网络后重试；本次没有调用模型。",
        }
    except DraftError as exc:
        return {
            "ok": False,
            "error": _provider_hint(str(exc)),
            "failure_owner": "EXTERNAL",
            "reason_codes": ["DRAFTER_FAILED"],
            "recommended_action": "检查默认 API 网关后重新生成；这不会消耗 Agent repair 轮次。",
        }
    except (ExampleProposalError, OSError, UnicodeError, ValueError) as exc:
        return {
            "ok": False,
            "error": _provider_hint(str(exc)),
            "failure_owner": "HARNESS",
            "reason_codes": ["AUDIT_CANDIDATE_GENERATION_FAILED"],
            "recommended_action": "检查冻结 reference、公开样例和钉版上游后重试。",
        }
    except Exception as exc:  # noqa: BLE001 - UI service must fail closed, not crash Streamlit
        return {
            "ok": False,
            "error": f"Fresh audit 候选生成失败:{type(exc).__name__}",
            "failure_owner": "HARNESS",
            "reason_codes": ["AUDIT_CANDIDATE_UNEXPECTED_FAILURE"],
            "recommended_action": "查看 Studio 活动日志并修复 Harness 后再试。",
        }
    finally:
        if "stack" in locals():
            stack.close()
        shutil.rmtree(tmp, ignore_errors=True)

    # 候选是 pydantic 对象(CandidateExample),不是 dict —— 按 dict 取值会
    # 全部读空,于是"有候选"被悄悄变成"没候选"(2026-08-28 自查发现)。
    usable_objects = [candidate for candidate in cands.candidates if candidate.usable_as_golden]
    context = _audit_candidate_context(
        tool_name=name,
        task_id=task_id,
        dest_root=checked_root,
    )
    try:
        store = _managed_candidate_evidence_store(
            namespace="audit",
            context_identity=context,
            create=True,
        )
        _persist_managed_candidate_evidence_records(
            store=store,
            context_identity=context,
            candidates=list(usable_objects),
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "error": f"Fresh audit 候选逐条证据无法安全持久化：{exc}",
            "failure_owner": "HARNESS",
            "reason_codes": ["AUDIT_CANDIDATE_EVIDENCE_PERSIST_FAILED"],
            "recommended_action": "检查受管状态目录后重新生成；不要使用浏览器中的旧候选。",
        }
    usable: list[dict[str, object]] = []
    for candidate in usable_objects:
        usable.append(candidate.model_dump(mode="json"))
    return {
        "ok": True,
        "tool_name": name,
        "task_id": task_id,
        "dest_root": str(checked_root),
        "drafter": getattr(drafter, "name", "?"),
        "candidates": usable,
        "note": (
            "期望值来自**冻结的参考实现**(真调钉版上游),不是被测工具自己 —— 所以这次比较仍然有判别力。请逐条确认。"
        ),
    }


def materialize_audit_candidate(
    tool_name: str,
    *,
    candidate: object,
    dest_root: Path,
    expected_task_id: str,
) -> dict:
    """Confirm one generated audit pair through its server-owned signed evidence."""

    from repoproof.adoption.intake.example_proposer import (
        reference_wheelhouse_runtime_identity,
        upstream_runtime_identity,
    )
    from repoproof.domain.models import TaskContract
    from repoproof.ui.services.product_mode import list_tools, project_root

    try:
        name = validate_tool_name(tool_name)
        task_id = validate_tool_task_id(name, expected_task_id)
    except ToolPathError as exc:
        return {"ok": False, "error": str(exc)}
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": path_error}
    library = list_tools(checked_root)
    if library.get("registry_error") or library.get("release_error"):
        return {
            "ok": False,
            "error": library.get("registry_error") or library.get("release_error"),
            "failure_owner": "HARNESS",
            "reason_codes": ["TOOL_REGISTRY_UNREADABLE"],
        }
    entry = next((row for row in library.get("tools") or [] if row.get("name") == name), None)
    if entry is None or str(entry.get("task_id") or "") != task_id:
        return {
            "ok": False,
            "error": "当前 registry 工具版本与 Journey 不一致。",
            "failure_owner": "HARNESS",
            "reason_codes": ["TASK_IDENTITY_MISMATCH"],
        }
    try:
        package_path = entry.get("path")
        if not isinstance(package_path, str) or not package_path:
            raise ToolPathError("Core registry 没有给出受管工具目录")
        tool_dir = Path(package_path)
        if tool_dir.resolve() != canonical_tool_path(checked_root, name).resolve():
            raise ToolPathError("Core registry 的工具目录与受管身份不一致")
        ensure_safe_package_tree(tool_dir)
        if str(entry.get("health") or "") != "OK":
            raise ToolPathError("工具包当前健康状态不是 OK")

        root = project_root()
        ref_impl = root / "controls" / task_id / "reference" / "impl.py"
        ref_lock = root / "controls" / task_id / "reference" / "requirements.lock.txt"
        _verify_frozen_reference_identity(
            tool_dir=tool_dir,
            registry_entry=entry,
            task_id=task_id,
            tool_name=name,
            ref_impl=ref_impl,
            ref_lock=ref_lock,
        )
        contract, _contract_sha = TaskContract.load_frozen(
            root / "contracts" / f"{task_id}.yaml",
            require_sidecar=True,
        )
        if contract.task_id != task_id:
            raise ValueError("冻结合同 task_id 与 Journey 不一致")
        commit = str(entry.get("resolved_commit") or "")
        if contract.source_repo.resolved_commit != commit:
            raise ValueError("冻结合同 upstream commit 与 registry 不一致")
        import_module = str(contract.source_repo.import_module or "").strip()
        if not import_module:
            raise ValueError("冻结合同没有 reference import_module")
        upstream = root / "upstream-cache" / f"upstream-{commit[:12]}"
        _verify_pinned_upstream_tree(upstream, commit)

        context = _audit_candidate_context(
            tool_name=name,
            task_id=task_id,
            dest_root=checked_root,
        )
        store = _managed_candidate_evidence_store(
            namespace="audit",
            context_identity=context,
            create=False,
        )
        stored = _load_managed_candidate_evidence_record(
            store=store,
            context_identity=context,
            browser_candidate=candidate,
        )
        evidence = stored.truth_evidence
        if evidence is None:  # pragma: no cover - generic loader rejects it
            raise ValueError("CANDIDATE_TRUTH_EVIDENCE_MISSING")
        if hashlib.sha256(ref_impl.read_bytes()).hexdigest() != evidence.reference_sha256:
            raise ValueError("CANDIDATE_REFERENCE_IDENTITY_CHANGED")
        if import_module != evidence.import_module:
            raise ValueError("CANDIDATE_UPSTREAM_IDENTITY_CHANGED")
        source_only_identity = upstream_runtime_identity(
            upstream,
            import_module=import_module,
        )
        if source_only_identity != evidence.upstream_identity_sha256:
            runtime_artifact_sha256 = reference_wheelhouse_runtime_identity(
                ref_lock,
                cache_root=ui_state_root() / "reference-wheelhouses",
            )
            if (
                upstream_runtime_identity(
                    upstream,
                    import_module=import_module,
                    runtime_artifact_sha256=runtime_artifact_sha256,
                )
                != evidence.upstream_identity_sha256
            ):
                raise ValueError("CANDIDATE_UPSTREAM_IDENTITY_CHANGED")

        safe_input = Path(stored.input_name).name
        if safe_input in {"", ".", ".."} or safe_input != stored.input_name:
            raise ValueError("Fresh audit 候选文件名无效")
        if stored.upstream_output is None:
            raise ValueError("Fresh audit 候选没有可确认的上游输出")
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}"
        audit_root = ui_state_root() / "audits"
        if _path_has_symlink(audit_root):
            raise ValueError("Fresh audit 受管目录不能包含 symlink")
        audit_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        out = audit_root / f"{name}-{stamp}"
        out.mkdir(parents=True, exist_ok=False)
        input_path = out / safe_input
        expected_path = out / f"{Path(safe_input).stem}.expected.txt"
        input_path.write_text(stored.input_text, encoding="utf-8")
        expected_path.write_text(stored.upstream_output, encoding="utf-8")
        (out / "candidate-evidence.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "candidate_evidence_id": evidence.evidence_id,
                    "candidate_truth_binding_sha256": evidence.truth_binding_sha256,
                    "reference_sha256": evidence.reference_sha256,
                    "upstream_identity_sha256": evidence.upstream_identity_sha256,
                    "input_sha256": evidence.input_sha256,
                    "output_sha256": evidence.result_sha256,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "input": str(input_path),
            "expected": str(expected_path),
            "candidate_evidence_id": evidence.evidence_id,
            "candidate_truth_binding_sha256": evidence.truth_binding_sha256,
        }
    except (OSError, UnicodeError, TypeError, ValueError, ToolPathError) as exc:
        return {
            "ok": False,
            "error": f"Fresh audit 候选受管证据核验失败：{exc}",
            "failure_owner": "HARNESS",
            "reason_codes": ["AUDIT_CANDIDATE_MANAGED_EVIDENCE_INVALID"],
            "recommended_action": "丢弃浏览器中的旧候选并重新生成；不要手工复制系统真值。",
        }


def materialize_audit_pair(tool_name: str, input_text: str, expected_text: str) -> dict:
    """把「直接填的」抽查内容落成文件 → {ok, input, expected}。

    抽查的判据是**逐字节比对**,所以这里原样写入、不加尾换行、不做任何
    规范化 —— 悄悄补一个 \n 就会让一次本该通过的抽查莫名其妙地失败。
    落在受管目录下(带时间戳),事后可追溯这次抽查到底喂了什么。
    """
    from repoproof.runner.tool_paths import ToolPathError, validate_tool_name

    try:
        name = validate_tool_name(tool_name)
    except ToolPathError as exc:
        return {"ok": False, "error": str(exc)}
    if not str(input_text).strip() or not str(expected_text).strip():
        return {"ok": False, "error": "输入与期望输出都不能为空。"}
    stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}"
    out = ui_state_root() / "audits" / f"{name}-{stamp}"
    try:
        out.mkdir(parents=True, exist_ok=True)
        (out / "input.txt").write_text(input_text, encoding="utf-8")
        (out / "expected.txt").write_text(expected_text, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": f"无法写入抽查材料:{exc}"}
    return {"ok": True, "input": str(out / "input.txt"), "expected": str(out / "expected.txt")}


def materialize_audit_files(
    tool_name: str,
    *,
    input_name: str,
    input_bytes: bytes,
    expected_name: str,
    expected_bytes: bytes,
) -> dict:
    """Persist one user-supplied fresh audit pair below the managed root."""

    try:
        name = validate_tool_name(tool_name)
    except ToolPathError as exc:
        return {"ok": False, "error": str(exc)}
    safe_input = Path(input_name).name
    safe_expected = Path(expected_name).name
    if safe_input in {"", ".", ".."} or safe_expected in {"", ".", ".."}:
        return {"ok": False, "error": "抽查文件名无效。"}
    if not input_bytes or not expected_bytes:
        return {"ok": False, "error": "新鲜输入和期望输出都不能为空。"}
    stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns()}"
    out = ui_state_root() / "audits" / f"{name}-{stamp}"
    try:
        out.mkdir(parents=True, exist_ok=False)
        input_path = out / safe_input
        expected_path = out / safe_expected
        input_path.write_bytes(input_bytes)
        expected_path.write_bytes(expected_bytes)
    except OSError as exc:
        return {"ok": False, "error": f"无法写入抽查材料：{exc}"}
    return {"ok": True, "input": str(input_path), "expected": str(expected_path)}


def start_tool_audit(
    name: str,
    input_path: Path,
    expected_path: Path,
    dest_root: Path,
    *,
    expected_task_id: str,
    journey_id: str = "",
) -> dict:
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": path_error}
    dest_root = checked_root  # 判空后再回赋,同上
    try:
        name = validate_tool_name(name)
        expected_task_id = str(expected_task_id or "").strip()
        validate_tool_task_id(name, expected_task_id)
    except ToolPathError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        manifest_path = dest_root / name / "tool.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        workspace_profile = bool(
            isinstance(manifest, dict)
            and manifest.get("contract_schema_version") == 4
            and manifest.get("delivery_profile_id") == "workspace_bundle_v1"
        )
    except (OSError, UnicodeError, ValueError):
        return {"ok": False, "error": "无法确认已安装工具的交付 profile。"}
    input_ok = not input_path.is_symlink() and (input_path.is_file() or (workspace_profile and input_path.is_dir()))
    expected_ok = not expected_path.is_symlink() and (
        expected_path.is_dir() if workspace_profile else expected_path.is_file()
    )
    if not input_ok or not expected_ok:
        expected_kind = "目录" if workspace_profile else "文件"
        return {
            "ok": False,
            "error": f"新鲜输入或期望{expected_kind}不存在/类型不安全。",
        }
    root = _product_root()
    return _start_product_job(
        [
            _product_python(root),
            "-m",
            "repoproof.cli",
            "tool",
            "audit",
            name,
            "--input",
            str(input_path),
            "--expected-file",
            str(expected_path),
            "--expected-task-id",
            expected_task_id,
            "--dest-root",
            str(dest_root),
            "--project-root",
            str(root),
            # Exported Local Tools intentionally do not ship their opaque
            # .venv. Studio asks for the reproducible build before its managed
            # audit. Core checks expected_task_id under the install lock before
            # build.sh can run, so stale truth cannot touch an upgraded package.
            "--build",
        ],
        kind="tool-audit",
        label=f"审核 {name}",
        expected_artifact=Path(dest_root) / ".repoproof-release-decisions.jsonl",
        journey_id=journey_id,
        metadata={
            "tool_name": name,
            "task_id": expected_task_id,
            "dest_root": str(dest_root),
            "journey_stage": 5,
        },
    )


def start_tool_withdraw(
    name: str,
    reason: str,
    dest_root: Path,
    *,
    journey_id: str = "",
) -> dict:
    if not reason.strip():
        return {"ok": False, "error": "请填写撤回原因。"}
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": path_error}
    dest_root = checked_root  # 判空后再回赋,同上
    try:
        name = validate_tool_name(name)
    except ToolPathError as exc:
        return {"ok": False, "error": str(exc)}
    root = _product_root()
    return _start_product_job(
        [
            _product_python(root),
            "-m",
            "repoproof.cli",
            "tool",
            "withdraw",
            name,
            "--reason",
            reason.strip(),
            "--dest-root",
            str(dest_root),
        ],
        kind="tool-withdraw",
        label=f"撤回 {name}",
        expected_artifact=Path(dest_root) / ".repoproof-release-decisions.jsonl",
        journey_id=journey_id,
        metadata={"tool_name": name, "dest_root": str(dest_root)},
    )


# ------------------------------------------------------------ 仓库概览 + 样例助手
#
# 两件都是"降低上手门槛"的辅助件,共享一条纪律:**它们不产出判据**。
# 概览是展示件(不进 draft、不填能力描述);样例助手只出候选,真值要人
# 逐条确认。详见 adoption/analysis/repo_overview.py 与
# adoption/intake/example_proposer.py 的模块注释。


def provider_configured() -> bool:
    """当前在线起草通道是否就绪；检查不发模型请求。"""
    return bool(online_drafter_status().get("ready"))


def online_drafter_status() -> dict:
    from repoproof.adoption.intake.tool_drafter import online_drafter_status as _status

    return _status()


def _provider_hint(raw: str) -> str:
    """把起草通道失败翻成人话；不把失败静默降级成离线。"""
    if provider_configured():
        return f"模型调用失败:{raw}"
    state = online_drafter_status()
    return (
        f"在线起草通道不可用:{state.get('label')}。"
        "可先勾选离线模板(零模型调用),或完成 Codex CLI 登录后重试。"
        f"(原始信息:{raw})"
    )


def _public_reference_environment_error(reason_code: str) -> str:
    """Project a stable error without subprocess output or private paths."""

    messages = {
        "REFERENCE_RUNTIME_ISOLATION_UNAVAILABLE": ("当前主机没有受支持的离线 reference 隔离后端；本次没有调用模型。"),
        "REFERENCE_WHEELHOUSE_MATERIALIZATION_FAILED": (
            "参考依赖 wheelhouse 暂时无法建立；请检查包索引网络后重试。本次没有调用模型。"
        ),
        "REFERENCE_WHEELHOUSE_INTEGRITY_FAILED": (
            "参考依赖 wheelhouse 身份校验失败；请人工检查受管缓存。本次没有调用模型。"
        ),
        "REFERENCE_OFFLINE_INSTALL_FAILED": (
            "参考依赖无法从已验证 wheelhouse 离线安装；请检查依赖锁的完整性。本次没有调用模型。"
        ),
        "REFERENCE_ENVIRONMENT_SETUP_FAILED": ("参考环境无法安全建立；本次没有调用模型。"),
    }
    return messages.get(
        str(reason_code),
        "参考环境在模型调用前失败；本次没有调用模型。",
    )


def _candidate_generation_error_result(exc: Exception) -> dict[str, object]:
    """Project candidate-authoring failures with one stable owner and action.

    Provider/schema diagnostics are not a public contract and may contain
    transport details.  The UI therefore receives only an allow-listed reason
    code plus an owner-specific recovery action.  In particular, a broken
    public commitment catalogue is a CONTRACT defect, while a model response
    that ignores the supplied catalogue is an EXTERNAL drafter defect; neither
    is an Agent-adapter repair.
    """

    from repoproof.adoption.intake.tool_drafter import DraftError

    raw = str(exc).strip()
    token = raw.partition(":")[0].strip()
    contract_codes = {
        "CANDIDATE_COMMITMENT_CATALOG_MISSING",
        "CANDIDATE_COMMITMENT_CATALOG_INVALID",
    }
    drafter_codes = {
        "CANDIDATE_EXPECTED_BEHAVIOR_INVALID",
        "CANDIDATE_COMMITMENT_BINDING_MISSING",
        "CANDIDATE_COMMITMENT_BINDING_INVALID",
    }
    if token in contract_codes:
        return {
            "ok": False,
            "error": "草稿的公开承诺目录缺失或无效，不能为候选绑定可审阅语义。",
            "failure_owner": "CONTRACT",
            "reason_codes": [token],
            "recommended_action": (
                "先修正当前未冻结草稿的公开承诺；若合同已冻结，请创建新的 task "
                "version。本次失败不消耗 Coding Agent repair 轮次。"
            ),
        }
    if token in drafter_codes or isinstance(exc, DraftError):
        reason_code = (
            token
            if token in drafter_codes
            else "CANDIDATE_DRAFTER_SCHEMA_INVALID"
            if "INVALID_DOCUMENT" in raw
            else "CANDIDATE_DRAFTER_FAILED"
        )
        return {
            "ok": False,
            "error": "模型返回的候选没有通过行为与公开承诺绑定校验。",
            "failure_owner": "EXTERNAL",
            "reason_codes": [reason_code],
            "recommended_action": (
                "重新生成候选；若同一错误持续出现，请检查网关的结构化输出支持。"
                "不要修改合同、reference 或 golden 来迁就这次模型响应。"
            ),
        }
    return {
        "ok": False,
        "error": "候选生成未通过 Core 的确定性校验。",
        "failure_owner": "HARNESS",
        "reason_codes": ["CANDIDATE_GENERATION_FAILED"],
        "recommended_action": (
            "查看 Studio 活动日志并修复候选生成链路后重试；不要把本次失败计入 Coding Agent repair。"
        ),
    }


def read_repo_overview(repo: str, revision: str | None = None) -> dict:
    """匿名浅克隆 + 静态分析 → 仓库概览(零模型;永不执行仓库代码)。"""
    from repoproof.adoption.analysis.repo_overview import build_repo_overview
    from repoproof.adoption.analysis.repository_analyzer import analyze_repository
    from repoproof.ui.services.product_mode import project_root

    if not _valid_public_github_repo(repo):
        return {"ok": False, "error": "当前只支持公开 GitHub 仓库地址。"}
    try:
        report = analyze_repository(repo, revision or None, cache_root=project_root() / "upstream-cache")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"读取失败:{exc}"}
    if report.is_public.value is False:
        return {"ok": False, "error": "无法匿名克隆(仓库不存在、私有,或网络到 github.com 被打断)。"}
    return {"ok": True, "overview": build_repo_overview(report), "admission_hint": report.risks[:3]}


def summarize_repo_overview(
    overview: dict,
    *,
    offline: bool,
    capability_goal: str = "",
) -> dict:
    """可选的模型摘要/能力分析。产物**只进展示层**,与事实分开标注。"""
    from repoproof.adoption.delivery.product_profile import CLI_V2_PROFILE_ID
    from repoproof.adoption.intake.tool_drafter import (
        DraftError,
        FakeDrafter,
        online_drafter,
        validate_repo_summary_document,
    )

    try:
        drafter = FakeDrafter() if offline else online_drafter()
        doc = drafter.summarize_repo(
            {
                "repository": overview.get("repository", ""),
                "headline": overview.get("headline", ""),
                "prose": (overview.get("prose") or "")[:1500],
                "surfaces": [s.get("value") for s in (overview.get("surfaces") or [])][:15],
                "capability_goal": capability_goal.strip()[:2000],
            }
        )
        # Summary-only stubs and persisted fixtures predate structured advice.
        # Keep their display path alive, but never synthesize an adoptable brief.
        doc = validate_repo_summary_document(doc, allow_legacy=True, allow_projected=True)
    except DraftError as exc:
        code = str(exc).split(":", 1)[0]
        if code in {
            "DRAFTER_TIMEOUT",
            "DRAFTER_CONNECTIVITY_ERROR",
            "DRAFTER_TIMEOUT_CONFIG_INVALID",
            "DRAFTER_STRUCTURED_OUTPUT_UNSUPPORTED",
        }:
            return {
                "ok": False,
                "error": _provider_hint(code),
                "failure_owner": ("HARNESS" if code == "DRAFTER_TIMEOUT_CONFIG_INVALID" else "EXTERNAL"),
                "reason_codes": [code],
                "recommended_action": (
                    "为默认网关启用 JSON Schema structured output，或显式切换"
                    "到支持同一 schema 的起草通道；本次没有创建 Journey，"
                    "也不消耗 Agent repair 轮次。"
                    if code == "DRAFTER_STRUCTURED_OUTPUT_UNSUPPORTED"
                    else "检查默认 API 网关连通性后重试；本次没有创建 Journey，也不消耗 Agent repair 轮次。"
                ),
            }
        return {"ok": False, "error": _provider_hint(str(exc))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"模型摘要失败:{exc}"}
    return {
        "ok": True,
        "summary": str(doc.get("summary") or ""),
        "requirement_briefs": list(doc.get("requirement_briefs") or []),
        "recommended_brief_id": str(doc.get("recommended_brief_id") or ""),
        "delivery_profile": CLI_V2_PROFILE_ID,
        "drafter": getattr(drafter, "name", "unknown"),
    }


def _draft_upstream_dir(draft_dir: Path) -> tuple[Path | None, str]:
    """从 draft 束推出**钉版**上游目录(候选输出必须来自钉住的那一版)。"""
    from repoproof.runner.tool_pipeline import ensure_pinned_upstream
    from repoproof.ui.services.product_mode import project_root

    doc = yaml.safe_load((Path(draft_dir) / "draft.yaml").read_text(encoding="utf-8")) or {}
    src = doc.get("source_repo") or {}
    url, commit = str(src.get("url") or ""), str(src.get("resolved_commit") or "")
    if not (url and commit):
        return None, "draft 束里没有钉住的上游(url/resolved_commit 缺失)"
    try:
        return ensure_pinned_upstream(url, commit, project_root()), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"钉版上游不可用:{exc}"


def existing_example_inputs(draft_dir: Path) -> list[str]:
    """已放进 examples/inputs 的输入原文(去重闸与"别再给重复的"都要用)。"""
    out: list[str] = []
    for p in sorted((Path(draft_dir) / "examples" / "inputs").glob("*")):
        if p.is_file():
            try:
                out.append(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue  # 二进制样例不参与文本去重,如实跳过
    return out


def _confirmed_public_success_controls(
    draft_dir: Path,
) -> list[tuple[str, str, str]]:
    """Load manifest-bound public success inputs for reference control runs.

    Merely finding a file below ``examples/inputs`` is insufficient: stale or
    uncommitted files must not become a trust signal.  Only file inputs named
    by ``examples.yaml`` entries that also carry an expected result are used.
    Invalid, binary, traversing, or symlinked entries are ignored here; draft
    readiness remains responsible for reporting the underlying manifest error.
    """

    draft_dir = Path(draft_dir)
    manifest = draft_dir / "examples.yaml"
    try:
        document = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return []
    if not isinstance(document, dict) or not isinstance(
        document.get("examples"),
        list,
    ):
        return []

    examples_root = draft_dir / "examples"
    controls: list[tuple[str, str, str]] = []
    for item in document["examples"]:
        if not isinstance(item, dict):
            continue
        if item.get("truth_provenance") != UPSTREAM_CONFIRMED:
            continue
        raw_input = item.get("input_file")
        raw_expected = item.get("expected_file")
        has_inline_expected = isinstance(item.get("expected"), str)
        has_file_expected = isinstance(raw_expected, str)
        if not isinstance(raw_input, str) or (has_inline_expected == has_file_expected):
            continue
        relative = Path(raw_input)
        if (
            relative.is_absolute()
            or relative.parts[:1] != ("inputs",)
            or len(relative.parts) != 2
            or relative.name in {"", ".", ".."}
        ):
            continue
        input_path = examples_root / relative
        if input_path.is_symlink() or _path_has_symlink(input_path) or not input_path.is_file():
            continue
        if has_file_expected:
            assert isinstance(raw_expected, str)
            expected_relative = Path(raw_expected)
            if (
                expected_relative.is_absolute()
                or expected_relative.parts[:1] != ("expected",)
                or len(expected_relative.parts) != 2
                or expected_relative.name in {"", ".", ".."}
            ):
                continue
            expected_path = examples_root / expected_relative
            if expected_path.is_symlink() or _path_has_symlink(expected_path) or not expected_path.is_file():
                continue
        try:
            input_bytes = input_path.read_bytes()
            input_text = input_bytes.decode("utf-8")
            expected_bytes = (
                str(item["expected"]).encode("utf-8") if has_inline_expected else expected_path.read_bytes()
            )
            recorded_binding = str(item.get("truth_binding_sha256") or "")
            if re.fullmatch(r"[0-9a-f]{64}", recorded_binding) is None or recorded_binding != truth_binding_sha256(
                input_bytes, expected_bytes
            ):
                continue

            evidence_id = item.get("candidate_evidence_id")
            evidence_binding = item.get("candidate_truth_binding_sha256")
            if (evidence_id is None) != (evidence_binding is None):
                continue
            if evidence_id is not None:
                if (
                    re.fullmatch(r"[0-9a-f]{64}", str(evidence_id)) is None
                    or re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(evidence_binding),
                    )
                    is None
                    or not _managed_candidate_control_matches(
                        draft_dir=draft_dir,
                        evidence_id=str(evidence_id),
                        evidence_binding=str(evidence_binding),
                        input_name=relative.name,
                        input_text=input_text,
                        expected_text=expected_bytes.decode("utf-8"),
                    )
                ):
                    continue
            controls.append((relative.name, input_text, expected_bytes.decode("utf-8")))
        except (OSError, UnicodeError):
            continue
    return controls


def _existing_example_names(draft_dir: Path) -> list[str]:
    """Reserve persisted golden filenames so regenerated candidates never collide."""

    return [p.name for p in sorted((Path(draft_dir) / "examples" / "inputs").glob("*")) if p.is_file()]


def _managed_candidate_evidence_store(
    *,
    namespace: str,
    context_identity: str,
    create: bool,
) -> Path:
    """Return one server-owned candidate store for an opaque Core context."""

    if re.fullmatch(r"[a-z][a-z0-9-]{0,31}", namespace) is None:
        raise ValueError("候选证据 namespace 无效")
    state_root = ui_state_root().expanduser()
    if _path_has_symlink(state_root):
        raise ValueError("候选证据受管根目录不能包含 symlink")
    if create:
        state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not state_root.is_dir() or state_root.is_symlink():
        raise ValueError("候选证据受管根目录不可用")
    key = hashlib.sha256(context_identity.encode("utf-8")).hexdigest()
    store = state_root / "candidate-evidence" / namespace / key
    if create:
        store.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not store.is_dir() or store.is_symlink() or _path_has_symlink(store):
        raise ValueError("候选证据目录不可用或包含 symlink")
    return store


def _verify_candidate_receipt_bytes(
    payload: bytes,
    secret: str,
    module: str,
    min_calls: int,
) -> dict:
    import tempfile

    from repoproof.execution.import_hook import verify_import_receipts

    with tempfile.TemporaryDirectory(prefix="rp-candidate-receipt-") as temp:
        receipt_path = Path(temp) / "receipt.jsonl"
        receipt_path.write_bytes(payload)
        return verify_import_receipts(
            receipt_path,
            secret,
            module=module,
            min_calls=min_calls,
        )


def _persist_managed_candidate_evidence_records(
    *,
    store: Path,
    context_identity: str,
    candidates: Sequence[object],
) -> None:
    """Persist signed receipts before a public projection reaches the UI."""

    from repoproof.adoption.intake.example_proposer import (
        CandidateExample,
        validate_candidate_truth_evidence,
    )

    store_fd = _open_absolute_directory(store)
    try:
        for value in candidates:
            candidate = CandidateExample.model_validate(value)
            evidence = candidate.truth_evidence
            managed = candidate.managed_runtime_evidence
            if evidence is None or managed is None:
                raise ValueError("CANDIDATE_TRUTH_EVIDENCE_MISSING")
            ledger = str(managed.get("ledger") or "")
            secret = str(managed.get("secret") or "")
            if hashlib.sha256(ledger.encode("utf-8")).hexdigest() != evidence.runtime_receipt_sha256:
                raise ValueError("CANDIDATE_RUNTIME_RECEIPT_HASH_MISMATCH")
            if candidate.usable_as_golden:
                validate_candidate_truth_evidence(candidate)

            verified = _verify_candidate_receipt_bytes(
                ledger.encode("utf-8"),
                secret,
                evidence.import_module,
                1 if evidence.result_kind == "output" else 0,
            )
            if (
                not verified["ok"]
                or int(verified["imports"]) != evidence.imports
                or int(verified["calls"]) != evidence.calls
            ):
                raise ValueError("CANDIDATE_RUNTIME_RECEIPT_INVALID")

            receipt_name = f"{evidence.evidence_id}.receipt.jsonl"
            record_name = f"{evidence.evidence_id}.json"
            # Verify once more at the durable-store boundary.  The receipt and
            # secret never enter ``candidate.model_dump()`` and therefore never
            # cross the browser trust boundary.
            _write_new_file_at(store_fd, receipt_name, ledger.encode("utf-8"))
            try:
                record = {
                    "schema_version": 1,
                    "context_identity_sha256": hashlib.sha256(context_identity.encode("utf-8")).hexdigest(),
                    "candidate": candidate.model_dump(mode="json"),
                    "receipt_secret": secret,
                }
                _write_new_file_at(
                    store_fd,
                    record_name,
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode("utf-8"),
                )
            except BaseException:
                try:
                    os.unlink(receipt_name, dir_fd=store_fd)
                except FileNotFoundError:
                    pass
                raise
    finally:
        os.close(store_fd)


def _load_managed_candidate_evidence_record(
    *,
    store: Path,
    context_identity: str,
    browser_candidate: object,
):
    """Resolve a browser evidence id to an immutable signed server record."""

    from repoproof.adoption.intake.example_proposer import (
        CandidateExample,
        validate_candidate_truth_evidence,
    )

    projected = CandidateExample.model_validate(browser_candidate)
    projected_evidence = projected.truth_evidence
    if projected_evidence is None:
        raise ValueError("CANDIDATE_TRUTH_EVIDENCE_MISSING")
    evidence_id = projected_evidence.evidence_id
    store_fd = _open_absolute_directory(store)
    try:
        raw_record = _read_file_at(store_fd, f"{evidence_id}.json")
        raw_receipt = _read_file_at(store_fd, f"{evidence_id}.receipt.jsonl")
    finally:
        os.close(store_fd)
    record = json.loads(raw_record.decode("utf-8"))
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ValueError("CANDIDATE_TRUTH_EVIDENCE_RECORD_INVALID")
    if record.get("context_identity_sha256") != hashlib.sha256(context_identity.encode("utf-8")).hexdigest():
        raise ValueError("CANDIDATE_TRUTH_EVIDENCE_CONTEXT_MISMATCH")
    stored = CandidateExample.model_validate(record.get("candidate"))
    evidence = stored.truth_evidence
    if evidence is None or evidence.evidence_id != evidence_id:
        raise ValueError("CANDIDATE_TRUTH_EVIDENCE_ID_MISMATCH")
    # Browser data is display state, never the source of truth.  Require it to
    # match the server projection, then continue exclusively with ``stored``.
    if projected.model_dump(mode="json") != stored.model_dump(mode="json"):
        raise ValueError("CANDIDATE_BROWSER_PROJECTION_MISMATCH")
    if hashlib.sha256(raw_receipt).hexdigest() != evidence.runtime_receipt_sha256:
        raise ValueError("CANDIDATE_RUNTIME_RECEIPT_HASH_MISMATCH")
    verified = _verify_candidate_receipt_bytes(
        raw_receipt,
        str(record.get("receipt_secret") or ""),
        evidence.import_module,
        1,
    )
    if not verified["ok"] or int(verified["imports"]) != evidence.imports or int(verified["calls"]) != evidence.calls:
        raise ValueError("CANDIDATE_RUNTIME_RECEIPT_INVALID")
    validate_candidate_truth_evidence(stored)
    return stored


def _managed_candidate_control_matches(
    *,
    draft_dir: Path,
    evidence_id: str,
    evidence_binding: str,
    input_name: str,
    input_text: str,
    expected_text: str,
) -> bool:
    """Verify a v2 candidate receipt before it can authorize control repair."""

    try:
        context = _draft_candidate_context(draft_dir)
        store = _managed_candidate_evidence_store(
            namespace="draft",
            context_identity=context,
            create=False,
        )
        store_fd = _open_absolute_directory(store)
        try:
            raw_record = _read_file_at(store_fd, f"{evidence_id}.json")
        finally:
            os.close(store_fd)
        record = json.loads(raw_record.decode("utf-8"))
        if not isinstance(record, dict):
            return False
        stored = _load_managed_candidate_evidence_record(
            store=store,
            context_identity=context,
            browser_candidate=record.get("candidate"),
        )
        evidence = stored.truth_evidence
        return bool(
            evidence is not None
            and evidence.schema_version == 2
            and evidence.evidence_id == evidence_id
            and evidence.truth_binding_sha256 == evidence_binding
            and stored.input_name == input_name
            and stored.input_text == input_text
            and stored.upstream_output == expected_text
            and stored.upstream_error is None
            and stored.expected_behavior == "success"
            and stored.admission_status == "ADMITTED"
        )
    except (OSError, UnicodeError, TypeError, ValueError, RuntimeError):
        return False


def _draft_candidate_context(draft_dir: Path) -> str:
    return "draft-v1:" + str(Path(draft_dir).resolve())


def _persist_candidate_evidence_records(
    draft_dir: Path,
    candidates: Sequence[object],
) -> None:
    """Persist signed candidate receipts below the draft's server context."""

    checked_dir, path_error = _validated_draft_dir(
        Path(draft_dir),
        require_existing=True,
    )
    if checked_dir is None:
        raise ValueError(path_error or "草稿目录不可用")
    context = _draft_candidate_context(checked_dir)
    store = _managed_candidate_evidence_store(
        namespace="draft",
        context_identity=context,
        create=True,
    )
    _persist_managed_candidate_evidence_records(
        store=store,
        context_identity=context,
        candidates=candidates,
    )


def _load_managed_candidate_for_confirmation(
    draft_dir: Path,
    browser_candidate: object,
):
    """Resolve a draft candidate and recheck current reference/upstream identity."""

    from repoproof.adoption.intake.example_proposer import (
        reference_wheelhouse_runtime_identity,
        upstream_runtime_identity,
    )

    checked_dir, path_error = _validated_draft_dir(
        Path(draft_dir),
        require_existing=True,
    )
    if checked_dir is None:
        raise ValueError(path_error or "草稿目录不可用")
    context = _draft_candidate_context(checked_dir)
    store = _managed_candidate_evidence_store(
        namespace="draft",
        context_identity=context,
        create=False,
    )
    stored = _load_managed_candidate_evidence_record(
        store=store,
        context_identity=context,
        browser_candidate=browser_candidate,
    )
    evidence = stored.truth_evidence
    if evidence is None:  # pragma: no cover - generic loader already rejects it
        raise ValueError("CANDIDATE_TRUTH_EVIDENCE_MISSING")
    current_reference = hashlib.sha256((checked_dir / "reference_impl.py").read_bytes()).hexdigest()
    if current_reference != evidence.reference_sha256:
        raise ValueError("CANDIDATE_REFERENCE_IDENTITY_CHANGED")
    draft = yaml.safe_load((checked_dir / "draft.yaml").read_text(encoding="utf-8")) or {}
    import_module = str((draft.get("source_repo") or {}).get("import_module") or "").strip()
    if import_module != evidence.import_module:
        raise ValueError("CANDIDATE_UPSTREAM_IDENTITY_CHANGED")
    upstream, upstream_error = _draft_upstream_dir(checked_dir)
    if upstream is None:
        raise ValueError(upstream_error)
    source_only_identity = upstream_runtime_identity(
        upstream,
        import_module=import_module,
    )
    if source_only_identity != evidence.upstream_identity_sha256:
        runtime_artifact_sha256 = reference_wheelhouse_runtime_identity(
            checked_dir / "reference.lock.txt",
            cache_root=ui_state_root() / "reference-wheelhouses",
        )
        if (
            upstream_runtime_identity(
                upstream,
                import_module=import_module,
                runtime_artifact_sha256=runtime_artifact_sha256,
            )
            != evidence.upstream_identity_sha256
        ):
            raise ValueError("CANDIDATE_UPSTREAM_IDENTITY_CHANGED")
    return stored


def example_input_mode(draft_dir: Path) -> dict:
    """Project the typed input representation into the sample-authoring flow.

    Whether a sample can be model-authored is a property of the admitted
    delivery contract.  Human labels such as ``DOCX`` or ``report`` are never
    interpreted here: doing so would make a growing keyword table an accidental
    second contract.  Drafts without the current typed intent fail closed and
    remain review-only instead of being guessed into a mode.
    """

    def incompatible(code: str, message: str) -> dict:
        return {
            "ok": False,
            "error": message,
            "failure_owner": "CONTRACT",
            "reason_codes": [code],
            "recommended_action": (
                "重新从当前 Studio 创建任务，让交付合同明确声明输入表示；不要根据文件名或格式文字猜测。"
            ),
        }

    try:
        raw = (Path(draft_dir) / "draft.yaml").read_text(encoding="utf-8")
        doc = yaml.safe_load(raw) or {}
    except (OSError, yaml.YAMLError) as exc:
        return incompatible("DRAFT_DOCUMENT_UNREADABLE", f"草稿输入合同不可读:{exc}")
    raw_schema_version = (doc.get("tool") or {}).get("schema_version")
    try:
        tool_schema_version = int(raw_schema_version) if isinstance(raw_schema_version, (str, int)) else 0
    except ValueError:
        tool_schema_version = 0
    if tool_schema_version != 3:
        return incompatible(
            "TYPED_INPUT_REPRESENTATION_UNAVAILABLE",
            "该旧草稿没有当前版本的类型化输入表示，不能安全生成新样例。",
        )
    try:
        intent = IntentContractDraftV1.model_validate(doc.get("_intent_contract"))
    except ValueError:
        return incompatible(
            "INTENT_CONTRACT_INVALID",
            "草稿的意图合同缺失或损坏，不能决定样例输入方式。",
        )
    if intent.delivery is None or len(intent.delivery.requirements.inputs) != 1:
        return incompatible(
            "DELIVERY_INPUT_REPRESENTATION_MISSING",
            "交付合同尚未声明唯一输入及其表示，不能决定样例输入方式。",
        )
    input_requirement = intent.delivery.requirements.inputs[0]
    input_format = input_requirement.format_label.strip()
    requires_upload = input_requirement.representation == "binary"
    suggestion_source = raw
    examples_path = Path(draft_dir) / "examples.yaml"
    if examples_path.is_file() and not examples_path.is_symlink():
        try:
            suggestion_source += "\n" + examples_path.read_text(encoding="utf-8")
        except OSError:
            pass
    suggestions = []
    for line in suggestion_source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#   - "):
            suggestion = stripped.removeprefix("#   - ").strip()
            suggestion = re.sub(r"\s*\((?:contains|exact_file)\)\s*$", "", suggestion)
            if suggestion and suggestion not in suggestions:
                suggestions.append(suggestion)
    return {
        "ok": True,
        "format": input_format or "UNKNOWN",
        "representation": input_requirement.representation,
        "requires_upload": requires_upload,
        "suggestions": suggestions[:8],
    }


class _CandidateAdmissionError(RuntimeError):
    """A generic candidate-screen mechanism could not make a safe decision."""

    def __init__(
        self,
        *,
        owner: str,
        reason_codes: list[str],
        message: str,
        diagnostics: tuple[str, ...] = (),
    ):
        self.owner = owner
        self.reason_codes = reason_codes
        self.diagnostics = diagnostics
        super().__init__(message)


def _redacted_line_shape(value: str) -> str:
    """Describe syntax without transmitting candidate/upstream text values."""

    shaped: list[str] = []
    previous = ""
    for character in value[:160]:
        if "A" <= character <= "Z":
            token = "A"
        elif "a" <= character <= "z":
            token = "a"
        elif character.isdigit():
            token = "0"
        elif character.isalpha():
            token = "U"
        elif character in {" ", "\t"}:
            token = character
        elif character.isprintable():
            token = character
        else:
            token = "?"
        # Collapse value-bearing character runs while keeping delimiters and
        # whitespace exact enough to diagnose producer framing.
        if token in {"A", "a", "0", "U"} and token == previous:
            continue
        shaped.append(token)
        previous = token
    return "".join(shaped)[:160]


def _public_output_contract_diagnostics(
    errors: Sequence[str],
    *,
    output_text: str = "",
) -> tuple[str, ...]:
    """Keep model-facing diagnostics structural and free of content values."""

    projected: list[str] = []
    for error in errors:
        clean = re.sub(r"[^A-Za-z0-9_:=., -]", "?", str(error))[:200].strip()
        if clean and clean not in projected:
            projected.append(clean)
        match = re.search(r"\bline=(\d+)\b", clean)
        if match and output_text:
            line_number = int(match.group(1))
            lines = output_text.splitlines()
            if 1 <= line_number <= len(lines):
                shape = _redacted_line_shape(lines[line_number - 1])
                diagnostic = f"invalid_line_shape[{line_number}]={shape}"
                if shape and diagnostic not in projected:
                    projected.append(diagnostic)
    return tuple(projected[:8])


def _source_defines_sync_function(source: str, name: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(isinstance(node, ast.FunctionDef) and node.name == name for node in tree.body)


def _uniform_internal_reference_failure(
    batch,
) -> tuple[str, str] | None:
    """Return one safe code-site identity shared by the complete batch.

    Messages are deliberately ignored.  The isolated runner derives the
    local-only fingerprint from reference identity and traceback code sites;
    historical rows without that identity fail closed.
    """

    candidates = list(getattr(batch, "candidates", []) or [])
    if not candidates or any(candidate.upstream_output is not None for candidate in candidates):
        return None
    errors = [str(candidate.upstream_error or "") for candidate in candidates]
    if any(not error for error in errors):
        return None
    exception_types = {error.partition(":")[0].strip().rsplit(".", 1)[-1] for error in errors}
    if len(exception_types) != 1 or exception_types == {"UserInputError"}:
        return None
    exception_type = next(iter(exception_types))
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", exception_type) is None:
        exception_type = "UNKNOWN"
    fingerprints = {str(getattr(candidate, "upstream_error_fingerprint", "") or "") for candidate in candidates}
    fingerprint = next(iter(fingerprints), "")
    if len(fingerprints) != 1 or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        return None
    return exception_type, fingerprint


def _uniform_internal_reference_exception(batch) -> str | None:
    failure = _uniform_internal_reference_failure(batch)
    return failure[0] if failure is not None else None


_CONTROL_ALL_SUCCEEDED = "ALL_SUCCEEDED"
_CONTROL_ALL_SAME_INTERNAL_EXCEPTION = "ALL_SAME_INTERNAL_EXCEPTION"
_CONTROL_FAILED_OR_MIXED = "FAILED_OR_MIXED"


@dataclass(frozen=True)
class _PositiveControlRun:
    batch: object
    expected_outputs: tuple[str, ...]


def _positive_control_verdict(control_run) -> tuple[str, str | None]:
    """Classify every positive-control result without treating errors as PASS."""

    if not isinstance(control_run, _PositiveControlRun):
        return _CONTROL_FAILED_OR_MIXED, None
    controls = list(getattr(control_run.batch, "candidates", []) or [])
    if not controls or len(controls) != len(control_run.expected_outputs):
        return _CONTROL_FAILED_OR_MIXED, None
    if all(
        candidate.upstream_output is not None
        and candidate.upstream_error is None
        and not candidate.upstream_output_truncated
        and candidate.upstream_output == expected_output
        for candidate, expected_output in zip(
            controls,
            control_run.expected_outputs,
            strict=True,
        )
    ):
        return _CONTROL_ALL_SUCCEEDED, None
    failure = _uniform_internal_reference_failure(control_run.batch)
    if failure is not None:
        return _CONTROL_ALL_SAME_INTERNAL_EXCEPTION, failure[0]
    return _CONTROL_FAILED_OR_MIXED, None


def _reference_batch_control_failure(
    batch,
    *,
    positive_control_batch=None,
) -> _CandidateAdmissionError | None:
    """Classify a uniform internal crash using a confirmed success control.

    A model can generate an entire batch outside the public input domain.  The
    candidate batch alone therefore cannot prove that the reference control is
    broken.  Automatic control repair is permitted only when at least one
    manifest-bound public success example exists and *all* such controls
    reproduce the same internal exception.  The optional keyword preserves the
    historical one-argument helper API while making that path fail closed.
    """

    candidate_failure = _uniform_internal_reference_failure(batch)
    if candidate_failure is None:
        return None
    exception_type, failure_fingerprint = candidate_failure

    controls = (
        list(getattr(positive_control_batch.batch, "candidates", []) or [])
        if isinstance(positive_control_batch, _PositiveControlRun)
        else []
    )
    if not controls:
        return _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["REFERENCE_OR_INPUT_DOMAIN_REVIEW_REQUIRED"],
            message=(
                "所有公开候选均触发同一种 reference 内部异常，"
                "但没有已确认的公开成功样例可作正控；"
                "无法安全区分 reference 故障与候选输入域错误。"
            ),
            diagnostics=(
                f"all_candidates_exception_type={exception_type}",
                "positive_control=missing",
            ),
        )

    control_verdict, control_exception_type = _positive_control_verdict(positive_control_batch)
    control_failure = (
        _uniform_internal_reference_failure(positive_control_batch.batch)
        if isinstance(positive_control_batch, _PositiveControlRun)
        else None
    )
    if (
        control_verdict == _CONTROL_ALL_SAME_INTERNAL_EXCEPTION
        and control_exception_type == exception_type
        and control_failure is not None
        and secrets.compare_digest(control_failure[1], failure_fingerprint)
    ):
        return _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["REFERENCE_IMPLEMENTATION_EXECUTION_FAILED"],
            message=(
                "所有公开候选与已确认的公开成功正控均触发"
                "同一种 reference 内部异常；这是草稿生产者故障，"
                "不应消耗候选输入 repair。"
            ),
            diagnostics=(
                f"all_candidates_exception_type={exception_type}",
                (f"positive_control_verdict={_CONTROL_ALL_SAME_INTERNAL_EXCEPTION}"),
            ),
        )
    if control_verdict == _CONTROL_ALL_SUCCEEDED:
        return _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["CANDIDATE_INPUT_DOMAIN_REVIEW_REQUIRED"],
            message=(
                "所有公开候选均触发同一种 reference 内部异常，"
                "但已确认的公开成功样例未复现该异常；"
                "应审查候选输入域，不得自动修改正确的控制面。"
            ),
            diagnostics=(
                f"all_candidates_exception_type={exception_type}",
                f"positive_control_verdict={_CONTROL_ALL_SUCCEEDED}",
            ),
        )

    return _CandidateAdmissionError(
        owner="CONTRACT",
        reason_codes=["REFERENCE_POSITIVE_CONTROL_FAILED_OR_MIXED"],
        message=("已确认的公开成功正控未全部成功，且没有全部复现候选的同一种内部异常；当前无法安全授权控制面 repair。"),
        diagnostics=(
            f"all_candidates_exception_type={exception_type}",
            f"positive_control_verdict={control_verdict}",
            *(
                ("positive_control_failure_match=false",)
                if control_verdict == _CONTROL_ALL_SAME_INTERNAL_EXCEPTION
                else ()
            ),
        ),
    )


_CONTROL_ROLLBACK_FILES = (
    "draft.yaml",
    "reference_impl.py",
    "semantic_verifier.py",
    "reference.lock.txt",
)


def _snapshot_draft_control_state(draft_dir: Path) -> dict[str, bytes | None]:
    """Capture every file the repair saver may replace."""

    draft_fd = _open_absolute_directory(draft_dir)
    try:
        snapshot: dict[str, bytes | None] = {}
        for name in _CONTROL_ROLLBACK_FILES:
            try:
                snapshot[name] = _read_file_at(draft_fd, name)
            except FileNotFoundError:
                snapshot[name] = None
        return snapshot
    finally:
        os.close(draft_fd)


def _begin_draft_control_repair(draft_dir: Path) -> None:
    """Durably mark the four-file control bundle unavailable before mutation."""

    draft_fd = _open_absolute_directory(draft_dir)
    try:
        _write_new_file_at(
            draft_fd,
            _CONTROL_REPAIR_MARKER,
            (
                json.dumps(
                    {
                        "schema_version": 1,
                        "state": "INCOMPLETE",
                        "started_at_ns": time.time_ns(),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("utf-8"),
        )
        os.fsync(draft_fd)
    finally:
        os.close(draft_fd)


def _finish_draft_control_repair(draft_dir: Path) -> None:
    """Commit or finish rollback by removing the fail-closed marker last."""

    draft_fd = _open_absolute_directory(draft_dir)
    try:
        os.unlink(_CONTROL_REPAIR_MARKER, dir_fd=draft_fd)
        os.fsync(draft_fd)
    finally:
        os.close(draft_fd)


def _restore_draft_control_state(
    draft_dir: Path,
    snapshot: dict[str, bytes | None],
) -> None:
    """Atomically replace each repaired control with its pre-repair bytes."""

    if set(snapshot) != set(_CONTROL_ROLLBACK_FILES):
        raise ValueError("DRAFT_CONTROL_REPAIR_ROLLBACK_SNAPSHOT_INVALID")
    draft_fd = _open_absolute_directory(draft_dir)
    try:
        for name in _CONTROL_ROLLBACK_FILES:
            payload = snapshot[name]
            if payload is None:
                try:
                    os.unlink(name, dir_fd=draft_fd)
                except FileNotFoundError:
                    pass
            else:
                _replace_file_at(draft_fd, name, payload)
        os.fsync(draft_fd)
    finally:
        os.close(draft_fd)


def _repair_draft_controls_after_contract_mismatch(
    *,
    draft_dir: Path,
    overview_doc: dict,
    drafter,
    failure_reason_code: str,
    diagnostics: tuple[str, ...],
) -> dict[str, str]:
    """Repair unfrozen reference/verifier controls without changing semantics.

    The two sources are repaired through separate model calls and contexts.
    The verifier never receives the reference source, candidate bodies or
    reference output, preserving the independent-judgement boundary.
    """

    reference_path = draft_dir / "reference_impl.py"
    verifier_path = draft_dir / "semantic_verifier.py"
    for path in (reference_path, verifier_path):
        if path.is_symlink() or not path.is_file():
            raise _CandidateAdmissionError(
                owner="CONTRACT",
                reason_codes=["DRAFT_CONTROL_REPAIR_INPUT_MISSING"],
                message="草稿控制面缺失，无法安全执行修复。",
            )
    lock_text = resolved_dependency_lock(
        overview_doc,
        draft_dir,
        project_root=_product_root(),
    )
    if not lock_text:
        raise _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["DEPENDENCY_LOCK_MISSING"],
            message="草稿依赖锁无法从用户文件或钉版上游事实中解析。",
        )
    current_reference = reference_path.read_text(encoding="utf-8")
    current_verifier = verifier_path.read_text(encoding="utf-8")
    output = ((overview_doc.get("tool") or {}).get("interface") or {}).get("output") or {}
    intent = IntentContractDraftV1.model_validate(overview_doc.get("_intent_contract"))
    if intent.delivery is None:
        raise _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["DELIVERY_INTENT_MISSING"],
            message="草稿没有可修复的交付意图。",
        )
    if failure_reason_code not in {
        "REFERENCE_ERROR_MASKING_INVALID",
        "REFERENCE_OUTPUT_CONTRACT_MISMATCH",
        "REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT",
    }:
        raise _CandidateAdmissionError(
            owner="HARNESS",
            reason_codes=["DRAFT_CONTROL_REPAIR_REASON_UNSUPPORTED"],
            message="草稿控制面收到不支持的修复责任类型。",
        )
    public_contract = {
        "user_goal": intent.user_goal,
        "semantic_commitments": [item.model_dump(mode="json") for item in intent.commitments],
        "artifact_protocol": (
            intent.artifact_protocol.model_dump(mode="json") if intent.artifact_protocol is not None else None
        ),
        "delivery_requirements": intent.delivery.requirements.model_dump(mode="json"),
        "output_contract": output.get("contract") or {},
        "upstream_public_info": {
            key: str((overview_doc.get("source_repo") or {}).get(key) or "")
            for key in (
                "url",
                "resolved_commit",
                "distribution",
                "import_module",
                "license",
            )
        },
        "authoring_failure": {
            "reason_code": failure_reason_code,
            "validator_diagnostics": list(diagnostics),
        },
    }
    from repoproof.adoption.assembly.output_contract import (
        public_validation_profile_spec,
    )

    public_contract["output_validation_profile_spec"] = public_validation_profile_spec(
        (output.get("contract") or {}).get("validation_profile")
    )
    from repoproof.adoption.intake.tool_drafter import DraftError

    before_reference = hashlib.sha256(current_reference.encode("utf-8")).hexdigest()
    before_verifier = hashlib.sha256(current_verifier.encode("utf-8")).hexdigest()
    repaired_reference = current_reference
    repaired_verifier = current_verifier
    reference_attempts = 0
    verifier_attempts = 0
    try:
        if failure_reason_code != "REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT":
            # The authoritative Core output validator identified the producer.
            # Do not mutate the independent judge at this stage.
            for reference_attempts in (1, 2):
                reference_context = {
                    **public_contract,
                    "current_reference_impl": current_reference,
                    "repair_attempt": reference_attempts,
                }
                if reference_attempts == 2:
                    reference_context["previous_public_failure"] = {
                        "reason_code": "DRAFT_REFERENCE_REPAIR_NO_PROGRESS",
                        "detail": (
                            "The previous repair returned byte-identical reference "
                            "source. Produce a real adapter change for the fixed "
                            "public contract; do not change semantics."
                        ),
                    }
                reference_result = drafter.repair_reference(reference_context)
                repaired_reference = str(reference_result.get("reference_impl") or "")
                if not _source_defines_sync_function(repaired_reference, "extract"):
                    raise _CandidateAdmissionError(
                        owner="CONTRACT",
                        reason_codes=["DRAFT_REFERENCE_REPAIR_INVALID"],
                        message="修复后的 reference 没有有效的同步 extract。",
                    )
                after_reference = hashlib.sha256(repaired_reference.encode("utf-8")).hexdigest()
                if after_reference != before_reference:
                    break
            else:
                raise _CandidateAdmissionError(
                    owner="CONTRACT",
                    reason_codes=["DRAFT_REFERENCE_REPAIR_NO_PROGRESS"],
                    message=("责任生产者 reference 连续两次没有产生代码变化，已停止且未改写独立 verifier。"),
                )
        else:
            # Core already admitted the producer's output contract. The judge
            # is the only responsible control in this phase. If it believes the
            # producer is semantically wrong, it may stay unchanged and the
            # no-progress stop will ask for human review rather than weakening
            # either side or oscillating them together.
            for verifier_attempts in (1, 2):
                verifier_context = {
                    **public_contract,
                    "current_semantic_verifier": current_verifier,
                    "repair_attempt": verifier_attempts,
                }
                if verifier_attempts == 2:
                    verifier_context["previous_public_failure"] = {
                        "reason_code": "DRAFT_VERIFIER_REPAIR_NO_PROGRESS",
                        "detail": (
                            "The previous repair returned byte-identical verifier "
                            "source. Correct the fixed-public-contract judgement "
                            "without seeing or inferring reference artifacts."
                        ),
                    }
                verifier_result = drafter.repair_verifier(verifier_context)
                repaired_verifier = str(verifier_result.get("semantic_verifier") or "")
                if not _source_defines_sync_function(repaired_verifier, "verify"):
                    raise _CandidateAdmissionError(
                        owner="CONTRACT",
                        reason_codes=["DRAFT_VERIFIER_REPAIR_INVALID"],
                        message="修复后的 verifier 没有有效的同步 verify。",
                    )
                after_verifier = hashlib.sha256(repaired_verifier.encode("utf-8")).hexdigest()
                if after_verifier != before_verifier:
                    break
            else:
                raise _CandidateAdmissionError(
                    owner="CONTRACT",
                    reason_codes=["DRAFT_VERIFIER_REPAIR_NO_PROGRESS"],
                    message=("责任判卷器 verifier 连续两次没有产生代码变化，已停止且未改写 reference。"),
                )
    except _CandidateAdmissionError:
        raise
    except DraftError as exc:
        raise _CandidateAdmissionError(
            owner="EXTERNAL",
            reason_codes=["DRAFT_CONTROL_REPAIR_DRAFTER_FAILED"],
            message="在线起草器未能生成合规的草稿控制面修复。",
        ) from exc
    except (AttributeError, TypeError) as exc:
        raise _CandidateAdmissionError(
            owner="HARNESS",
            reason_codes=["DRAFT_CONTROL_REPAIR_INTERFACE_MISSING"],
            message="当前起草后端不支持隔离的草稿控制面修复。",
        ) from exc
    if not _source_defines_sync_function(repaired_reference, "extract"):
        raise _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["DRAFT_REFERENCE_REPAIR_INVALID"],
            message="修复后的 reference 没有有效的同步 extract。",
        )
    if not _source_defines_sync_function(repaired_verifier, "verify"):
        raise _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["DRAFT_VERIFIER_REPAIR_INVALID"],
            message="修复后的 verifier 没有有效的同步 verify。",
        )
    after_reference = hashlib.sha256(repaired_reference.encode("utf-8")).hexdigest()
    after_verifier = hashlib.sha256(repaired_verifier.encode("utf-8")).hexdigest()
    interface = (overview_doc.get("tool") or {}).get("interface") or {}
    source_repo = overview_doc.get("source_repo") or {}
    save_result = save_draft_review(
        draft_dir,
        tool_name=str((overview_doc.get("tool") or {}).get("name") or ""),
        summary=str((overview_doc.get("tool") or {}).get("summary") or ""),
        statement=str((overview_doc.get("capability") or {}).get("statement") or ""),
        semantic_commitments=[item.public_text for item in intent.commitments],
        input_format=str((interface.get("input") or {}).get("format") or ""),
        input_representation=intent.delivery.requirements.inputs[0].representation,
        output_format=str(output.get("format") or ""),
        output_schema=str((overview_doc.get("capability") or {}).get("output_schema") or ""),
        reference_impl=repaired_reference,
        semantic_verifier=repaired_verifier,
        output_contract=dict(output.get("contract") or {}),
        distribution=str(source_repo.get("distribution") or ""),
        import_module=str(source_repo.get("import_module") or ""),
        license_id=str(source_repo.get("license") or ""),
        reference_lock=lock_text,
        _control_repair_transaction=True,
    )
    if not save_result.get("ok"):
        raise _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["DRAFT_CONTROL_REPAIR_SAVE_FAILED"],
            message="修复后的草稿控制面未能通过安全保存。",
        )
    return {
        "reason_code": failure_reason_code,
        "reference_before_sha256": before_reference,
        "reference_after_sha256": after_reference,
        "reference_attempts": str(reference_attempts),
        "verifier_before_sha256": before_verifier,
        "verifier_after_sha256": after_verifier,
        "verifier_attempts": str(verifier_attempts),
    }


def _admit_candidate_pair(
    candidate,
    *,
    output_contract: dict,
    semantic_verifier: Path | None,
    required_commitment_ids: tuple[str, ...],
    reference_python: str | None,
    upstream: Path,
    import_module: str,
    execute_installed_upstream: bool = False,
):
    """Apply repository-agnostic output and semantic gates to one proposal."""

    from repoproof.adoption.assembly.output_contract import validate_output_text
    from repoproof.verification.semantic_artifact import (
        SemanticVerifierError,
        screen_semantic_candidate,
    )

    # The pinned-reference behavior gate runs before output/semantic admission.
    # Never let a later successful parser/verifier overwrite its fail-closed
    # rejection (for example, a candidate declared ``user_error`` whose
    # reference unexpectedly produced a perfectly parseable artifact).
    if candidate.admission_status == "REJECTED":
        return candidate
    if candidate.upstream_output is None or candidate.upstream_error is not None:
        return candidate
    contract_errors = validate_output_text(candidate.upstream_output, output_contract)
    if contract_errors:
        raise _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["REFERENCE_OUTPUT_CONTRACT_MISMATCH"],
            message=("固定上游 reference 返回成功，但产物违反机器输出合同；这是草稿控制面故障，不是候选输入失败。"),
            diagnostics=_public_output_contract_diagnostics(
                contract_errors,
                output_text=candidate.upstream_output,
            ),
        )
    # Historical/non-current drafts remain reviewable.  Current v3 readiness
    # separately requires a verifier before confirmation/freeze.
    if semantic_verifier is None:
        return candidate.model_copy(update={"admission_status": "ADMITTED"})
    if not required_commitment_ids:
        raise _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["SEMANTIC_COMMITMENTS_MISSING"],
            message="独立语义预筛缺少公开 commitment 身份。",
        )
    with tempfile.TemporaryDirectory(prefix="rp-candidate-admission-") as temp:
        root = Path(temp)
        input_path = root / "input"
        artifact_path = root / "artifact"
        input_path.write_text(candidate.input_text, encoding="utf-8")
        artifact_path.write_text(candidate.upstream_output, encoding="utf-8")
        try:
            screen = screen_semantic_candidate(
                verifier_source=semantic_verifier,
                input_path=input_path,
                artifact_path=artifact_path,
                python_exe=reference_python or sys.executable,
                upstream_dir=upstream,
                import_module=import_module,
                required_commitment_ids=required_commitment_ids,
                execute_installed_upstream=execute_installed_upstream,
                isolation_required=True,
            )
        except SemanticVerifierError as exc:
            raise _CandidateAdmissionError(
                owner="HARNESS",
                reason_codes=["SEMANTIC_CANDIDATE_SCREEN_EXECUTION_FAILED"],
                message="独立语义预筛无法在受控环境中执行。",
            ) from exc
    if not screen.mechanism_ok:
        raise _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=list(screen.reason_codes) or ["SEMANTIC_VERIFIER_MECHANISM_INVALID"],
            message="独立语义验证器无法完整证明自己声明的检查。",
        )
    if not screen.passed:
        public_reasons = tuple(
            str(code) for code in screen.reason_codes if re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", str(code)) is not None
        )
        raise _CandidateAdmissionError(
            owner="CONTRACT",
            reason_codes=["REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"],
            message=(
                "固定上游 reference 已成功且通过输出合同，但独立 verifier "
                "拒绝同一产物；这是草稿控制面分歧，不是候选输入失败。"
            ),
            diagnostics=public_reasons[:8] or ("SEMANTIC_DISAGREEMENT",),
        )
    return candidate.model_copy(update={"admission_status": "ADMITTED"})


def propose_example_candidates(draft_dir: Path, *, n: int, offline: bool) -> dict:
    """Generate ``n`` usable candidates with at most two bounded repair rounds.

    A candidate that makes pinned upstream fail remains visible as behavior
    evidence, but does not consume one of the requested usable-output slots.
    Persisted golden examples are read-only inputs to this operation.
    """
    from contextlib import ExitStack

    from repoproof.adoption.intake.example_proposer import (
        CandidateExample,
        ExampleProposalError,
        ProposalBatch,
        ReferenceEnvironmentError,
        mine_evidence_literals,
        prepared_reference_environment,
        propose_inputs,
        public_candidate_failure,
        reference_wheelhouse_runtime_identity,
        run_reference_on_candidates,
    )
    from repoproof.adoption.intake.tool_drafter import (
        DraftError,
        FakeDrafter,
        online_drafter,
    )

    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=True)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir
    if _control_repair_incomplete(draft_dir):
        return {
            "ok": False,
            "error": "草稿存在未完成的控制面修复事务，已拒绝继续生成候选。",
            "failure_owner": "HARNESS",
            "reason_codes": ["DRAFT_CONTROL_REPAIR_INCOMPLETE"],
            "recommended_action": (
                "从 repair 前快照恢复该草稿，或创建新 task version；不要在混合控制束上继续调用模型。"
            ),
        }

    overview_doc = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8")) or {}
    goal = str(
        (overview_doc.get("capability") or {}).get("statement") or (overview_doc.get("tool") or {}).get("summary") or ""
    )
    requested = max(1, min(int(n), 8))
    mode = example_input_mode(draft_dir)
    if not mode.get("ok"):
        return {"ok": False, "error": mode.get("error") or "草稿输入格式不可读。"}
    if mode.get("requires_upload"):
        fresh_review = read_managed_draft_review(draft_dir)
        return {
            "ok": True,
            "drafter": "saved-draft-suggestions",
            "note": (
                f"输入格式 {mode.get('format')} 是二进制文件；系统不会把模型文本伪装成真实文件。"
                "请按建议场景上传实际文件，固定版本上游会在确认前给出实际输出。"
            ),
            "requested": requested,
            "usable_count": 0,
            "rejected_count": 0,
            "shortfall": 0,
            "rounds": 0,
            "evidence_probes": 0,
            "confirmed_count": (len(fresh_review.get("examples") or []) if fresh_review.get("ok") else None),
            "manual_upload_required": True,
            "suggestions": list(mode.get("suggestions") or []),
            "candidates": [],
        }
    reference_import_module = str((overview_doc.get("source_repo") or {}).get("import_module") or "").strip()
    if not reference_import_module:
        return {
            "ok": False,
            "error": "草稿没有声明 reference import_module。",
            "failure_owner": "CONTRACT",
            "reason_codes": ["REFERENCE_IMPORT_MODULE_MISSING"],
            "recommended_action": "先修正仓库身份与参考实现，再重新生成候选；本次没有调用模型。",
        }
    upstream, up_err = _draft_upstream_dir(draft_dir)
    if upstream is None:
        return {"ok": False, "error": up_err}

    output_contract = (((overview_doc.get("tool") or {}).get("interface") or {}).get("output") or {}).get("contract")
    if not isinstance(output_contract, dict):
        return {
            "ok": False,
            "error": "草稿没有机器可执行输出合同。",
            "failure_owner": "CONTRACT",
            "reason_codes": ["OUTPUT_CONTRACT_MISSING"],
        }
    raw_intent = overview_doc.get("_intent_contract") or {}
    required_commitment_ids = tuple(
        str(item.get("commitment_id") or "") for item in (raw_intent.get("commitments") or []) if isinstance(item, dict)
    )
    public_commitments = [
        {
            "commitment_id": str(item.get("commitment_id") or ""),
            "public_text": str(item.get("public_text") or ""),
        }
        for item in (raw_intent.get("commitments") or [])
        if isinstance(item, dict)
        and str(item.get("commitment_id") or "").strip()
        and str(item.get("public_text") or "").strip()
    ]
    verifier_path = draft_dir / "semantic_verifier.py"
    semantic_verifier = verifier_path if verifier_path.is_file() and not verifier_path.is_symlink() else None

    persisted_inputs = existing_example_inputs(draft_dir)
    persisted_names = _existing_example_names(draft_dir)
    confirmed_success_controls = _confirmed_public_success_controls(draft_dir)
    attempted_inputs: list[str] = []
    attempted_names: list[str] = []
    usable: list[CandidateExample] = []
    rejected: list[CandidateExample] = []
    failed_attempts: list[dict[str, str]] = []
    repair_stopped = ""
    rounds = 0
    control_repair_events: list[dict[str, str]] = []
    last_control_failure_fingerprint = ""
    # Retained in the result schema for historical UI compatibility.  Untyped
    # README/test literals are prompt hints only and are never executed as if
    # they were complete input files.
    evidence_probes = 0
    stack = ExitStack()
    try:
        lock_text = resolved_dependency_lock(
            overview_doc,
            draft_dir,
            project_root=_product_root(),
        )
        if not lock_text:
            raise _CandidateAdmissionError(
                owner="HARNESS",
                reason_codes=["DEPENDENCY_LOCK_MISSING"],
                message=("固定上游依赖锁尚未成立；候选生成已在模型调用前停止。"),
            )
        reference_python = stack.enter_context(
            prepared_reference_environment(
                draft_dir,
                wheelhouse_cache_root=ui_state_root() / "reference-wheelhouses",
                resolved_lock_text=lock_text,
            )
        )
        reference_lock = draft_dir / "reference.lock.txt"
        runtime_artifact_sha256 = (
            reference_wheelhouse_runtime_identity(
                reference_lock,
                cache_root=ui_state_root() / "reference-wheelhouses",
            )
            if reference_lock.is_file()
            else None
        )
        # 强制零模型预检：依赖闭包、钉版源码优先级和 reference 导入必须
        # 先成立。失败就归 HARNESS/CONTRACT，不让 LLM 猜环境问题。
        run_reference_on_candidates(
            ProposalBatch(candidates=[]),
            draft_dir=draft_dir,
            upstream_dir=upstream,
            python_exe=reference_python,
            isolation_required=True,
            import_module=reference_import_module,
            runtime_artifact_sha256=runtime_artifact_sha256,
        )
        drafter = FakeDrafter() if offline else online_drafter()
        from repoproof.adoption.intake.tool_drafter import (
            reference_source_policy_errors,
        )

        def run_confirmed_success_controls():
            if not confirmed_success_controls:
                return None
            batch = run_reference_on_candidates(
                ProposalBatch(
                    candidates=[
                        CandidateExample(
                            input_name=name,
                            input_text=input_text,
                            why="manifest-bound public success control",
                        )
                        for name, input_text, _expected_text in confirmed_success_controls
                    ],
                    drafter="confirmed-public-success-control",
                    note="manifest-bound public success controls",
                ),
                draft_dir=draft_dir,
                upstream_dir=upstream,
                python_exe=reference_python,
                isolation_required=True,
                import_module=reference_import_module,
                runtime_artifact_sha256=runtime_artifact_sha256,
            )
            return _PositiveControlRun(
                batch=batch,
                expected_outputs=tuple(
                    expected_text for _name, _input_text, expected_text in confirmed_success_controls
                ),
            )

        def repair_controls_with_postcheck(
            *,
            failure_reason_code: str,
            diagnostics: tuple[str, ...],
        ):
            # Snapshot every possible write before the durable marker is
            # created.  The marker stays visible until either the repaired
            # bundle and post-checks commit, or the complete snapshot is
            # restored.  A crash/partial rollback therefore remains
            # fail-closed instead of exposing a mixed four-file bundle.
            snapshot = _snapshot_draft_control_state(draft_dir)
            _begin_draft_control_repair(draft_dir)
            try:
                repaired = _repair_draft_controls_after_contract_mismatch(
                    draft_dir=draft_dir,
                    overview_doc=overview_doc,
                    drafter=drafter,
                    failure_reason_code=failure_reason_code,
                    diagnostics=diagnostics,
                )
                post_controls = run_confirmed_success_controls()
                if confirmed_success_controls:
                    verdict, _exception_type = _positive_control_verdict(post_controls)
                    if verdict != _CONTROL_ALL_SUCCEEDED:
                        raise _CandidateAdmissionError(
                            owner="CONTRACT",
                            reason_codes=["REFERENCE_POSITIVE_CONTROL_POST_REPAIR_FAILED"],
                            message=("控制面 repair 后，已确认的公开成功正控没有全部成功；本轮修复已撤销。"),
                            diagnostics=(f"positive_control_verdict={verdict}",),
                        )
                _finish_draft_control_repair(draft_dir)
                return repaired, post_controls
            except BaseException:
                try:
                    _restore_draft_control_state(draft_dir, snapshot)
                    _finish_draft_control_repair(draft_dir)
                except (OSError, TypeError, ValueError) as rollback_exc:
                    raise _CandidateAdmissionError(
                        owner="HARNESS",
                        reason_codes=["DRAFT_CONTROL_REPAIR_ROLLBACK_FAILED"],
                        message=(
                            "控制面修复失败，且无法安全恢复 repair 前状态；事务标记已保留，后续操作将 fail closed。"
                        ),
                    ) from rollback_exc
                raise

        positive_control_batch = None
        reference_source = (draft_dir / "reference_impl.py").read_text(encoding="utf-8")
        source_policy_errors = reference_source_policy_errors(reference_source)
        if source_policy_errors:
            if offline:
                raise _CandidateAdmissionError(
                    owner="CONTRACT",
                    reason_codes=["REFERENCE_ERROR_MASKING_INVALID"],
                    message=("reference 使用了会掩盖内部故障的异常处理；离线模板不能自动修复。"),
                    diagnostics=tuple(source_policy_errors),
                )
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "reason_codes": ["REFERENCE_ERROR_MASKING_INVALID"],
                        "diagnostics": source_policy_errors,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            event, positive_control_batch = repair_controls_with_postcheck(
                failure_reason_code="REFERENCE_ERROR_MASKING_INVALID",
                diagnostics=tuple(source_policy_errors),
            )
            event["failure_fingerprint"] = fingerprint
            control_repair_events.append(event)
            last_control_failure_fingerprint = fingerprint

        # Execute controls lazily: ordinary mixed/successful candidate batches
        # need no extra subprocesses.  A uniform internal crash, however, must
        # never be interpreted without this independent positive control.
        evidence_literals = mine_evidence_literals(
            upstream,
            import_module_names=[str((overview_doc.get("source_repo") or {}).get("import_module") or "")],
        )
        # Initial generation + two bounded repair rounds. Each repair sees only
        # model-safe failure categories/fingerprints; failed input bodies and
        # raw reference exceptions remain local to the Harness.
        for _round_index in range(3):
            remaining = requested - len(usable)
            if remaining <= 0:
                break
            try:
                batch = propose_inputs(
                    goal=goal,
                    overview={
                        "repository": str((overview_doc.get("source_repo") or {}).get("url") or ""),
                        "evidence_literals": evidence_literals,
                        "failed_attempts": failed_attempts,
                        "public_commitments": public_commitments,
                    },
                    drafter=drafter,
                    n=remaining,
                    existing_inputs=[*persisted_inputs, *attempted_inputs],
                    existing_names=[*persisted_names, *attempted_names],
                )
                batch = run_reference_on_candidates(
                    batch,
                    draft_dir=draft_dir,
                    upstream_dir=upstream,
                    python_exe=reference_python,
                    isolation_required=True,
                    import_module=reference_import_module,
                    runtime_artifact_sha256=runtime_artifact_sha256,
                )
                while True:
                    try:
                        if _uniform_internal_reference_exception(batch) is not None and positive_control_batch is None:
                            positive_control_batch = run_confirmed_success_controls()
                        reference_failure = _reference_batch_control_failure(
                            batch,
                            positive_control_batch=positive_control_batch,
                        )
                        if reference_failure is not None:
                            raise reference_failure
                        batch = batch.model_copy(
                            update={
                                "candidates": [
                                    _admit_candidate_pair(
                                        candidate,
                                        output_contract=output_contract,
                                        semantic_verifier=semantic_verifier,
                                        required_commitment_ids=required_commitment_ids,
                                        reference_python=reference_python,
                                        upstream=upstream,
                                        import_module=reference_import_module,
                                        execute_installed_upstream=(runtime_artifact_sha256 is not None),
                                    )
                                    for candidate in batch.candidates
                                ]
                            }
                        )
                        break
                    except _CandidateAdmissionError as exc:
                        repairable = (
                            exc.owner == "CONTRACT"
                            and exc.reason_codes
                            in (
                                ["REFERENCE_OUTPUT_CONTRACT_MISMATCH"],
                                ["REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"],
                            )
                            and not offline
                        )
                        if not repairable:
                            raise
                        fingerprint = hashlib.sha256(
                            json.dumps(
                                {
                                    "reason_codes": exc.reason_codes,
                                    "diagnostics": exc.diagnostics,
                                },
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        if fingerprint == last_control_failure_fingerprint:
                            raise _CandidateAdmissionError(
                                owner="CONTRACT",
                                reason_codes=["DRAFT_CONTROL_REPAIR_REPEATED_FAILURE"],
                                message=("草稿控制面修复后再次出现相同公开失败，已按无进展规则停止。"),
                            ) from exc
                        # Control authoring is separate from Coding-Agent repair.
                        # One task may legitimately expose, in order: error
                        # masking, an invalid upstream call, output framing, and
                        # finally an independent-verifier disagreement.  Give
                        # each owner one bounded event; repeated fingerprints
                        # still stop immediately above.
                        if len(control_repair_events) >= 4:
                            raise _CandidateAdmissionError(
                                owner="CONTRACT",
                                reason_codes=["DRAFT_CONTROL_REPAIR_LIMIT_REACHED"],
                                message="草稿控制面达到有界修复上限。",
                            ) from exc
                        event, positive_control_batch = repair_controls_with_postcheck(
                            failure_reason_code=exc.reason_codes[0],
                            diagnostics=exc.diagnostics,
                        )
                        event["failure_fingerprint"] = fingerprint
                        control_repair_events.append(event)
                        last_control_failure_fingerprint = fingerprint
                        # Re-run the SAME public candidates through the repaired
                        # controls. Do not spend another candidate-generation call
                        # or let the candidate model guess a contract-authoring bug.
                        batch = run_reference_on_candidates(
                            ProposalBatch(
                                candidates=[
                                    CandidateExample(
                                        input_name=item.input_name,
                                        input_text=item.input_text,
                                        why=item.why,
                                        expected_behavior=item.expected_behavior,
                                        covered_commitment_ids=(item.covered_commitment_ids),
                                    )
                                    for item in batch.candidates
                                ],
                                drafter=batch.drafter,
                                note=batch.note,
                            ),
                            draft_dir=draft_dir,
                            upstream_dir=upstream,
                            python_exe=reference_python,
                            isolation_required=True,
                            import_module=reference_import_module,
                            runtime_artifact_sha256=runtime_artifact_sha256,
                        )
            except (DraftError, ExampleProposalError) as exc:
                if not usable and not rejected:
                    raise
                repair_stopped = str(exc)
                break
            rounds += 1
            for candidate in batch.candidates:
                attempted_inputs.append(candidate.input_text)
                attempted_names.append(candidate.input_name)
                if candidate.usable_as_golden:
                    usable.append(candidate)
                else:
                    rejected.append(candidate)
                    failed_attempts.append(public_candidate_failure(candidate))
    except _CandidateAdmissionError as exc:
        prior_repair_note = (
            f"此前已完成 {len(control_repair_events)} 次控制面 repair；当前停止未新增修改。"
            if control_repair_events
            else "当前停止前没有修改 reference/verifier。"
        )
        if "DEPENDENCY_LOCK_MISSING" in exc.reason_codes:
            recommended_action = (
                "固定公开发布版本并重新加载草稿；Core 必须先从钉版源码或"
                "与 commit 一致的发布 tag 派生精确依赖锁。本次没有调用模型。"
            )
        elif "REFERENCE_OR_INPUT_DOMAIN_REVIEW_REQUIRED" in exc.reason_codes:
            recommended_action = (
                f"先确认至少一条公开成功样例，或人工核对候选输入是否属于公开有效域。{prior_repair_note}"
            )
        elif "CANDIDATE_INPUT_DOMAIN_REVIEW_REQUIRED" in exc.reason_codes:
            recommended_action = (
                f"已确认正控未复现异常；请检查候选输入是否属于公开有效域并重新生成。{prior_repair_note}"
            )
        elif "REFERENCE_POSITIVE_CONTROL_FAILED_OR_MIXED" in exc.reason_codes:
            recommended_action = (
                f"已确认正控自身不是全成功，也未与候选复现同一内部异常；请人工检查草稿与输入域。{prior_repair_note}"
            )
        elif "REFERENCE_POSITIVE_CONTROL_POST_REPAIR_FAILED" in exc.reason_codes:
            recommended_action = (
                f"repair 后正控未全部成功，本轮控制面写入已恢复；请人工审查，不要继续自动 repair。{prior_repair_note}"
            )
        else:
            recommended_action = "修正通用输出合同或独立 verifier 后创建新任务版本；不要确认当前浏览器中的候选。"
        return {
            "ok": False,
            "error": str(exc),
            "failure_owner": exc.owner,
            "reason_codes": exc.reason_codes,
            "recommended_action": recommended_action,
        }
    except ReferenceEnvironmentError as exc:
        return {
            "ok": False,
            "error": _public_reference_environment_error(exc.reason_code),
            "failure_owner": "HARNESS",
            "reason_codes": [exc.reason_code],
            "recommended_action": "检查依赖锁与网络后重试；本次没有调用模型。",
        }
    except (DraftError, ExampleProposalError) as exc:
        return _candidate_generation_error_result(exc)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"候选生成失败:{exc}"}
    finally:
        stack.close()

    final_usable = usable[:requested]
    shortfall = requested - len(final_usable)
    note = (
        f"请求 {requested} 条；得到 {len(final_usable)} 条可确认输出，"
        f"{len(rejected)} 条未通过候选准入；共运行 {rounds} 个模型轮次"
    )
    if evidence_probes:
        note += f"，并探测 {evidence_probes} 条钉版上游证据输入"
    if control_repair_events:
        note += f"；草稿控制面自修复 {len(control_repair_events)} 轮"
    if shortfall:
        note += f"。达到修复上限后仍缺 {shortfall} 条"
    if repair_stopped:
        note += f"；补候选提前停止:{repair_stopped}"
    fresh_review = read_managed_draft_review(draft_dir)
    returned_candidates = [*final_usable, *rejected]
    try:
        _persist_candidate_evidence_records(draft_dir, returned_candidates)
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "error": f"候选逐条证据无法安全持久化：{exc}",
            "failure_owner": "HARNESS",
            "reason_codes": ["CANDIDATE_EVIDENCE_PERSIST_FAILED"],
            "recommended_action": "检查受管状态目录后重新生成；不要确认浏览器里这批候选。",
        }
    return {
        "ok": True,
        "drafter": str(getattr(drafter, "name", "unknown")),
        "note": note,
        "requested": requested,
        "usable_count": len(final_usable),
        "rejected_count": len(rejected),
        "shortfall": shortfall,
        "rounds": rounds,
        "control_repairs": control_repair_events,
        "evidence_probes": evidence_probes,
        "confirmed_count": (len(fresh_review.get("examples") or []) if fresh_review.get("ok") else None),
        "candidates": [c.model_dump(mode="json") for c in returned_candidates],
    }


def confirm_candidate_as_example(draft_dir: Path, candidate: dict, *, expected_text: str, input_text: str) -> dict:
    """③ 人闸:确认一条候选 → 落成 golden 样例文件。

    一次一条,没有批量口子(与计划确认逐项同律)。
    """
    from repoproof.adoption.intake.example_proposer import (
        ExampleProposalError,
        confirm_candidate,
    )

    try:
        # Resolve the evidence id through the server store first.  The browser
        # projection and text-area values are comparison inputs only; neither
        # is allowed to self-attest a new golden truth.
        c = _load_managed_candidate_for_confirmation(draft_dir, candidate)
        if input_text != c.input_text or expected_text != c.upstream_output:
            return {
                "ok": False,
                "error": (
                    "候选输入或钉版上游输出已变化，拒绝把修改后的内容标成上游派生真值。"
                    "如需自定义样例，请使用手工样例入口并按用户提供的真值处理。"
                ),
                "failure_owner": "USER_INPUT",
                "reason_codes": ["CANDIDATE_TRUTH_BINDING_MISMATCH"],
                "recommended_action": "恢复候选原值后确认，或改用手工样例入口。",
            }
        done = confirm_candidate(c)
    except ExampleProposalError as exc:
        return {"ok": False, "error": str(exc)}
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            "ok": False,
            "error": f"候选受管证据核验失败：{exc}",
            "failure_owner": "HARNESS",
            "reason_codes": ["CANDIDATE_MANAGED_EVIDENCE_INVALID"],
            "recommended_action": "丢弃浏览器中的旧候选并重新生成；不要手工复制候选真值。",
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"确认失败:{exc}"}

    stem = Path(done.input_name).stem or "case"
    result = add_golden_example(
        draft_dir,
        input_name=done.input_name,
        input_bytes=done.input_text.encode("utf-8"),
        expected_name=f"{stem}.expected.txt",
        expected_bytes=(done.upstream_output or "").encode("utf-8"),
        truth_provenance="UPSTREAM_DERIVED_USER_CONFIRMED",
        candidate_evidence_id=(done.truth_evidence.evidence_id if done.truth_evidence is not None else None),
        candidate_truth_binding_sha256=(
            done.truth_evidence.truth_binding_sha256 if done.truth_evidence is not None else None
        ),
    )
    if result.get("ok"):
        result["truth_provenance"] = done.truth_provenance()
    return result
