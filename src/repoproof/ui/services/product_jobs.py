"""Bounded Product Mode jobs and draft editing for RepoProof Studio.

Product state lives below ``REPOPROOF_UI_STATE_ROOT`` (``~/.repoproof`` by
default).  This service never writes Benchmark Lab ``runs/``, benchmarks or
evidence, and every CLI launch uses an argv list rather than a shell.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from repoproof.adoption.assembly.tool_assembler import next_tool_task_id
from repoproof.execution.core_execution import (
    LEGACY_LAB_STATE,
    RUNNING,
    legacy_state_blocker,
    read_durable_job_state,
    start_durable_job,
)
from repoproof.execution.product_action import read_product_action_result
from repoproof.runner.tool_paths import ToolPathError, validate_tool_name
from repoproof.ui.services.product_mode import ui_state_root

PRODUCT_LOCK = "product-job.json"
_EXACT_PIN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9._+!-]*")


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


def read_managed_draft_review(value: Path) -> dict:
    """Read the bounded review surface without following optional symlinks."""

    draft_dir, error = validate_managed_draft_dir(value)
    if draft_dir is None:
        return {"ok": False, "error": error}
    draft_fd: int | None = None
    try:
        draft_fd = _open_absolute_directory(draft_dir)
        raw_draft = _read_file_at(draft_fd, "draft.yaml").decode("utf-8")
        raw_examples = _read_file_at(draft_fd, "examples.yaml").decode("utf-8")
        reference = _read_file_at(draft_fd, "reference_impl.py").decode("utf-8")
        draft = yaml.safe_load(raw_draft) or {}
        examples_doc = yaml.safe_load(raw_examples) or {}
        if not isinstance(draft, dict) or not isinstance(examples_doc, dict):
            raise TypeError("draft.yaml/examples.yaml 根节点必须是对象")
        try:
            gaps = _read_file_at(draft_fd, "GAPS.md").decode("utf-8")
        except FileNotFoundError:
            gaps = ""
        return {
            "ok": True,
            "draft_dir": draft_dir,
            "draft": draft,
            "raw_draft": raw_draft,
            "examples": examples_doc.get("examples") or [],
            "reference_impl": reference,
            "gaps": gaps,
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
    if fake_drafter:
        argv.append("--fake-drafter")
    return argv


def tool_build_argv(
    root: Path,
    *,
    draft_dir: Path,
    dest_root: Path,
    rehearsal_only: bool,
    agent_backend: str = "codex-cli",
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
    journey_id: str = "",
    metadata: dict | None = None,
) -> dict:
    # 判定器是 **fail-closed** 的:退出码 0 但没形成"预期产物"一律记 FAILED
    # (`test_exit_zero_without_expected_artifact_is_failed` 钉着这条,是有意的
    # ——证明不了产出就不许算成功)。因此**漏给 expected_artifact 是调用方的
    # 缺陷**,而它的表现极具误导性:2026-08-28 用户的续跑真发跑出
    # PASS_ADAPTED、工具都装进了 ~/tools,界面却写"失败:未形成预期产物"。
    # 与其让人等几分钟再吃一个假失败,不如在这里当场拒绝。
    if expected_artifact is None:
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
        expected_artifact=expected_artifact,
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
        result = read_product_action_result(resolved)
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
    task_id: str, dest_root: Path, agent_backend: str = "codex-cli", journey_id: str = "", rehearsal_only: bool = False
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
    expected = frozen_contract if rehearsal_only else None
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
    return _start_product_job(
        argv,
        kind="tool-build",
        label=("重新运行零模型演练" if rehearsal_only else "真实构建") + f" {clean}（已冻结任务续跑）",
        expected_artifact=expected,
        journey_id=journey_id,
        metadata={
            "task_id": clean,
            "dest_root": str(checked_root),
            "journey_stage": 3 if rehearsal_only else 4,
        },
    )


def start_tool_build(
    *,
    draft_dir: Path,
    dest_root: Path,
    rehearsal_only: bool,
    agent_backend: str = "codex-cli",
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
    input_format: str,
    output_format: str,
    output_schema: str,
    reference_impl: str,
    output_contract: dict | None = None,
    # intake 把这三个标为 owner=USER(提取不到时要人来定),但审核页一直
    # 没有入口、本函数也不收 —— 声明了责任却没有履行路径,Studio 用户
    # 只能去手改 YAML(2026-08-28 AUTO/USER 全量核账发现的第二笔账)。
    distribution: str | None = None,
    import_module: str | None = None,
    license_id: str | None = None,
    reference_lock: str | None = None,
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
            )
            if not str(new_value or "").strip() and str(old_value or "").strip()
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
        if output_contract is not None:
            draft["tool"]["interface"]["output"]["contract"] = output_contract
        draft["capability"]["statement"] = statement.strip()
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
        draft["tool"]["interface"]["usage"] = f"{clean_name} <input> [--out FILE]"
        _replace_file_at(
            draft_fd,
            "reference_impl.py",
            reference_impl.encode("utf-8"),
        )
        _replace_file_at(
            draft_fd,
            "draft.yaml",
            yaml.safe_dump(draft, allow_unicode=True, sort_keys=False).encode("utf-8"),
        )
        if normalized_lock is not None:
            _replace_file_at(draft_fd, "reference.lock.txt", normalized_lock.encode("utf-8"))
        return {"ok": True, "note": "审核修改已保存；冻结前仍会经过确定性检查。"}
    except (OSError, UnicodeError, KeyError, TypeError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"保存失败：{exc}"}
    finally:
        if draft_fd is not None:
            os.close(draft_fd)


def add_golden_example(
    draft_dir: Path,
    *,
    input_name: str,
    input_bytes: bytes,
    expected_name: str,
    expected_bytes: bytes,
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
        doc.setdefault("examples", []).append({"input_file": str(input_rel), "expected_file": str(expected_rel)})
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


def propose_audit_candidates(tool_name: str, *, n: int = 4, offline: bool = False) -> dict:
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
        run_reference_on_candidates,
    )
    from repoproof.adoption.intake.tool_drafter import FakeDrafter, online_drafter
    from repoproof.runner.tool_paths import ToolPathError, validate_tool_name
    from repoproof.ui.services.product_mode import list_tools, project_root

    try:
        name = validate_tool_name(tool_name)
    except ToolPathError as exc:
        return {"ok": False, "error": str(exc)}
    root = project_root()
    entry = next((r for r in list_tools()["tools"] if r["name"] == name), None)
    task_id = str((entry or {}).get("task_id") or "")
    if not task_id:
        return {"ok": False, "error": f"找不到 {name} 的冻结任务,无法出候选。"}
    ref_impl = root / "controls" / task_id / "reference" / "impl.py"
    ref_lock = root / "controls" / task_id / "reference" / "requirements.lock.txt"
    upstream_commit = str((entry or {}).get("resolved_commit") or "")
    upstream = root / "upstream-cache" / f"upstream-{upstream_commit[:12]}"
    if not ref_impl.is_file():
        return {"ok": False, "error": f"找不到冻结的参考实现:{ref_impl} —— 没有独立真值源,不能替你出期望值。"}
    if not upstream.is_dir():
        return {"ok": False, "error": f"钉版上游树不在:{upstream}"}

    tmp = Path(tempfile.mkdtemp(prefix="rp-audit-propose-"))
    try:
        # 组一个**临时 draft 束形态**给既有的执行器用:只读地拷一份冻结
        # reference,不碰任何冻结件(controls/ 是不可改写的证据面)。
        (tmp / "examples" / "inputs").mkdir(parents=True)
        shutil.copy2(ref_impl, tmp / "reference_impl.py")
        if ref_lock.is_file():
            shutil.copy2(ref_lock, tmp / "reference.lock.txt")
        stack = ExitStack()
        reference_python = stack.enter_context(prepared_reference_environment(tmp))
        # 在任何模型调用前验证依赖闭包与 reference 导入。环境/合同故障
        # 不应消耗一次候选生成调用，更不能伪装成 Agent repair。
        run_reference_on_candidates(
            ProposalBatch(candidates=[]),
            draft_dir=tmp,
            upstream_dir=upstream,
            python_exe=reference_python,
        )
        drafter = FakeDrafter() if offline else online_drafter()
        batch = propose_inputs(
            goal=str((entry or {}).get("summary") or name),
            overview={
                "repository": str((entry or {}).get("source_url") or ""),
                "evidence_literals": mine_evidence_literals(upstream),
            },
            drafter=drafter,
            n=n,
            existing_inputs=[],
        )
        cands = run_reference_on_candidates(
            batch,
            draft_dir=tmp,
            upstream_dir=upstream,
            python_exe=reference_python,
        )
        stack.close()
    except ReferenceEnvironmentError as exc:
        return {
            "ok": False,
            "error": _provider_hint(str(exc)),
            "failure_owner": "HARNESS",
            "reason_codes": [exc.reason_code],
            "recommended_action": "检查依赖锁与网络后重试；本次没有调用模型。",
        }
    except (ExampleProposalError, OSError, ValueError) as exc:
        return {"ok": False, "error": _provider_hint(str(exc))}
    finally:
        if "stack" in locals():
            stack.close()
        shutil.rmtree(tmp, ignore_errors=True)

    # 候选是 pydantic 对象(CandidateExample),不是 dict —— 按 dict 取值会
    # 全部读空,于是"有候选"被悄悄变成"没候选"(2026-08-28 自查发现)。
    usable = [
        {"input_name": c.input_name, "input_text": c.input_text, "why": c.why, "expected": c.upstream_output}
        for c in cands.candidates
        if c.upstream_output and not c.upstream_error
    ]
    return {
        "ok": True,
        "drafter": getattr(drafter, "name", "?"),
        "candidates": usable,
        "note": (
            "期望值来自**冻结的参考实现**(真调钉版上游),不是被测工具自己 —— 所以这次比较仍然有判别力。请逐条确认。"
        ),
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
    journey_id: str = "",
) -> dict:
    if not input_path.is_file() or not expected_path.is_file():
        return {"ok": False, "error": "新鲜输入和期望输出文件都必须存在。"}
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
            "audit",
            name,
            "--input",
            str(input_path),
            "--expected-file",
            str(expected_path),
            "--dest-root",
            str(dest_root),
            # Exported Local Tools intentionally do not ship their opaque
            # .venv.  A Product fresh audit is the first local invocation, so
            # it must reconstruct the package from build.sh + wheelhouse
            # before executing bin/<tool>.  The CLI keeps --build explicit for
            # backwards compatibility; Studio's managed journey always asks
            # for the reproducible build.
            "--build",
        ],
        kind="tool-audit",
        label=f"审核 {name}",
        expected_artifact=Path(dest_root) / ".repoproof-release-decisions.jsonl",
        journey_id=journey_id,
        metadata={"tool_name": name, "dest_root": str(dest_root), "journey_stage": 5},
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
    from repoproof.adoption.intake.tool_drafter import (
        DraftError,
        FakeDrafter,
        online_drafter,
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
    except DraftError as exc:
        return {"ok": False, "error": _provider_hint(str(exc))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"模型摘要失败:{exc}"}
    return {"ok": True, "summary": str(doc.get("summary") or ""), "drafter": getattr(drafter, "name", "unknown")}


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


def _existing_example_names(draft_dir: Path) -> list[str]:
    """Reserve persisted golden filenames so regenerated candidates never collide."""

    return [p.name for p in sorted((Path(draft_dir) / "examples" / "inputs").glob("*")) if p.is_file()]


_BINARY_EXAMPLE_FORMATS = frozenset({
    "7Z",
    "AVI",
    "BMP",
    "DB",
    "DOC",
    "DOCX",
    "GIF",
    "GZ",
    "JPEG",
    "JPG",
    "MKV",
    "MOV",
    "MP3",
    "MP4",
    "ODS",
    "ODT",
    "PDF",
    "PNG",
    "PPT",
    "PPTX",
    "RAR",
    "SQLITE",
    "TAR",
    "TIFF",
    "WAV",
    "WEBP",
    "XLS",
    "XLSX",
    "ZIP",
})


def example_input_mode(draft_dir: Path) -> dict:
    """Describe whether candidate inputs can safely be represented as UTF-8 text.

    The LLM candidate protocol deliberately emits text only. Feeding that text
    to a DOCX/ZIP/PDF reference implementation creates a misleading upstream or
    dependency failure, so binary formats must go through the real file-upload
    path. The saved LLM draft suggestions remain useful as scenario guidance.
    """

    try:
        raw = (Path(draft_dir) / "draft.yaml").read_text(encoding="utf-8")
        doc = yaml.safe_load(raw) or {}
    except (OSError, yaml.YAMLError) as exc:
        return {"ok": False, "error": f"草稿输入格式不可读:{exc}"}
    interface_input = (((doc.get("tool") or {}).get("interface") or {}).get("input") or {})
    input_format = str(interface_input.get("format") or "").strip()
    normalized = input_format.upper().replace(".", " ").replace("/", " ").replace("-", " ")
    tokens = {token for token in normalized.split() if token}
    requires_upload = bool(tokens & _BINARY_EXAMPLE_FORMATS)
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
        "requires_upload": requires_upload,
        "suggestions": suggestions[:8],
    }


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
    upstream, up_err = _draft_upstream_dir(draft_dir)
    if upstream is None:
        return {"ok": False, "error": up_err}

    persisted_inputs = existing_example_inputs(draft_dir)
    persisted_names = _existing_example_names(draft_dir)
    attempted_inputs: list[str] = []
    attempted_names: list[str] = []
    usable: list[CandidateExample] = []
    rejected: list[CandidateExample] = []
    failed_attempts: list[dict[str, str]] = []
    repair_stopped = ""
    rounds = 0
    evidence_probes = 0
    stack = ExitStack()
    try:
        reference_python = stack.enter_context(prepared_reference_environment(draft_dir))
        # 强制零模型预检：依赖闭包、钉版源码优先级和 reference 导入必须
        # 先成立。失败就归 HARNESS/CONTRACT，不让 LLM 猜环境问题。
        run_reference_on_candidates(
            ProposalBatch(candidates=[]),
            draft_dir=draft_dir,
            upstream_dir=upstream,
            python_exe=reference_python,
        )
        drafter = FakeDrafter() if offline else online_drafter()
        evidence_literals = mine_evidence_literals(
            upstream,
            import_module_names=[str((overview_doc.get("source_repo") or {}).get("import_module") or "")],
        )
        # Initial generation + two bounded repair rounds. Each repair sees the
        # exact inputs/errors that failed and must propose distinct replacements.
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
                    failed_attempts.append(
                        {
                            "input_name": candidate.input_name,
                            "input_text": candidate.input_text[:500],
                            "upstream_error": str(candidate.upstream_error or "NO_OUTPUT")[:800],
                        }
                    )
            # Before spending another model round, probe author-supplied README
            # or upstream-test literals. These remain candidates (not truth),
            # and their outputs still come from the same pinned reference run.
            if _round_index == 0 and len(usable) < requested and evidence_literals:
                evidence_rows: list[CandidateExample] = []
                evidence_seen = {
                    str(value).strip()
                    for value in [
                        *persisted_inputs,
                        *attempted_inputs,
                    ]
                }
                reserved_names = {
                    name.casefold()
                    for name in [
                        *persisted_names,
                        *attempted_names,
                    ]
                }
                for index, value in enumerate(evidence_literals, start=1):
                    text = str(value)
                    if text.strip() in evidence_seen:
                        continue
                    base = f"upstream-evidence-{index}"
                    name = f"{base}.txt"
                    serial = 2
                    while name.casefold() in reserved_names:
                        name = f"{base}-{serial}.txt"
                        serial += 1
                    evidence_seen.add(text.strip())
                    reserved_names.add(name.casefold())
                    evidence_rows.append(
                        CandidateExample(
                            input_name=name,
                            input_text=text,
                            why="来自钉版上游 README/测试的现成输入",
                        )
                    )
                    if len(evidence_rows) >= 8:
                        break
                if evidence_rows:
                    evidence_batch = run_reference_on_candidates(
                        ProposalBatch(
                            candidates=evidence_rows,
                            drafter="pinned-upstream-evidence",
                            note="",
                        ),
                        draft_dir=draft_dir,
                        upstream_dir=upstream,
                        python_exe=reference_python,
                    )
                    evidence_probes = len(evidence_rows)
                    for candidate in evidence_batch.candidates:
                        if len(usable) >= requested:
                            break
                        attempted_inputs.append(candidate.input_text)
                        attempted_names.append(candidate.input_name)
                        if candidate.usable_as_golden:
                            usable.append(candidate)
                        else:
                            rejected.append(candidate)
                            failed_attempts.append(
                                {
                                    "input_name": candidate.input_name,
                                    "input_text": candidate.input_text[:500],
                                    "upstream_error": str(candidate.upstream_error or "NO_OUTPUT")[:800],
                                }
                            )
    except ReferenceEnvironmentError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "failure_owner": "HARNESS",
            "reason_codes": [exc.reason_code],
            "recommended_action": "检查依赖锁与网络后重试；本次没有调用模型。",
        }
    except (DraftError, ExampleProposalError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"候选生成失败:{exc}"}
    finally:
        stack.close()

    final_usable = usable[:requested]
    shortfall = requested - len(final_usable)
    note = (
        f"请求 {requested} 条；得到 {len(final_usable)} 条可确认输出，"
        f"{len(rejected)} 条上游失败；共运行 {rounds} 个模型轮次"
    )
    if evidence_probes:
        note += f"，并探测 {evidence_probes} 条钉版上游证据输入"
    if shortfall:
        note += f"。达到修复上限后仍缺 {shortfall} 条"
    if repair_stopped:
        note += f"；补候选提前停止:{repair_stopped}"
    fresh_review = read_managed_draft_review(draft_dir)
    return {
        "ok": True,
        "drafter": str(getattr(drafter, "name", "unknown")),
        "note": note,
        "requested": requested,
        "usable_count": len(final_usable),
        "rejected_count": len(rejected),
        "shortfall": shortfall,
        "rounds": rounds,
        "evidence_probes": evidence_probes,
        "confirmed_count": (len(fresh_review.get("examples") or []) if fresh_review.get("ok") else None),
        "candidates": [c.model_dump() for c in [*final_usable, *rejected]],
    }


def confirm_candidate_as_example(draft_dir: Path, candidate: dict, *, expected_text: str, input_text: str) -> dict:
    """③ 人闸:确认一条候选 → 落成 golden 样例文件。

    一次一条,没有批量口子(与计划确认逐项同律)。
    """
    from repoproof.adoption.intake.example_proposer import (
        CandidateExample,
        ExampleProposalError,
        confirm_candidate,
    )

    try:
        c = CandidateExample.model_validate({**candidate, "input_text": input_text})
        done = confirm_candidate(c, expected_text=expected_text)
    except ExampleProposalError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"确认失败:{exc}"}

    stem = Path(done.input_name).stem or "case"
    result = add_golden_example(
        draft_dir,
        input_name=done.input_name,
        input_bytes=done.input_text.encode("utf-8"),
        expected_name=f"{stem}.expected.txt",
        expected_bytes=(done.upstream_output or "").encode("utf-8"),
    )
    if result.get("ok"):
        result["truth_provenance"] = done.truth_provenance()
    return result
