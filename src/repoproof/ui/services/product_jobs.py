"""Bounded Product Mode jobs and draft editing for RepoProof Studio.

Product state lives below ``REPOPROOF_UI_STATE_ROOT`` (``~/.repoproof`` by
default).  This service never writes Benchmark Lab ``runs/``, benchmarks or
evidence, and every CLI launch uses an argv list rather than a shell.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
import subprocess
import sys
import time
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
from repoproof.runner.tool_paths import ToolPathError, validate_tool_name
from repoproof.ui.services.product_mode import ui_state_root

PRODUCT_LOCK = "product-job.json"


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
) -> dict:
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
    return start_durable_job(
        root=root,
        state_path=state_root / PRODUCT_LOCK,
        worker_python=_product_python(root),
        argv=argv,
        cwd=root,
        log_path=log,
        kind=kind,
        label=label,
        expected_artifact=expected_artifact,
    )


def start_tool_add(
    *,
    repo: str,
    capability: str,
    draft_dir: Path,
    revision: str | None = None,
    fake_drafter: bool = False,
) -> dict:
    if not _valid_public_github_repo(repo):
        return {"ok": False, "error": "当前只支持公开 GitHub 仓库地址。"}
    if len(capability.strip()) < 8:
        return {"ok": False, "error": "请用一句完整的话描述想要的能力。"}
    checked_dir, path_error = _validated_draft_dir(
        Path(draft_dir), require_existing=False
    )
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir       # 判空后再回赋:参数类型不被 None 污染
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
    )


def start_tool_build(
    *,
    draft_dir: Path,
    dest_root: Path,
    rehearsal_only: bool,
) -> dict:
    checked_dir, path_error = _validated_draft_dir(
        Path(draft_dir), require_existing=True
    )
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir       # 判空后再回赋:参数类型不被 None 污染
    checked_root, dest_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": dest_error}
    dest_root = checked_root      # 判空后再回赋,同上
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
    expected = (
        root / "contracts" / f"{predicted_task_id}.yaml"
        if rehearsal_only
        else dest_root / name / "tool.json"
    )
    return _start_product_job(
        tool_build_argv(
            root,
            draft_dir=draft_dir,
            dest_root=dest_root,
            rehearsal_only=rehearsal_only,
        ),
        kind="tool-build",
        label=("离线彩排" if rehearsal_only else "完整构建") + f" {name}",
        expected_artifact=expected,
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
) -> dict:
    checked_dir, path_error = _validated_draft_dir(
        Path(draft_dir), require_existing=True
    )
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir       # 判空后再回赋:参数类型不被 None 污染
    clean_name = tool_name.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", clean_name):
        return {"ok": False, "error": "工具名只能包含小写字母、数字和连字符。"}
    draft_fd: int | None = None
    try:
        draft_fd = _open_absolute_directory(draft_dir)
        draft = yaml.safe_load(
            _read_file_at(draft_fd, "draft.yaml").decode("utf-8")
        ) or {}
        draft["tool"]["name"] = clean_name
        draft["tool"]["summary"] = summary.strip()
        draft["tool"]["interface"]["input"]["format"] = input_format.strip()
        draft["tool"]["interface"]["output"]["format"] = output_format.strip()
        if output_contract is not None:
            draft["tool"]["interface"]["output"]["contract"] = output_contract
        draft["capability"]["statement"] = statement.strip()
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
            yaml.safe_dump(draft, allow_unicode=True, sort_keys=False).encode(
                "utf-8"
            ),
        )
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
    checked_dir, path_error = _validated_draft_dir(
        Path(draft_dir), require_existing=True
    )
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir       # 判空后再回赋:参数类型不被 None 污染
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
        doc = yaml.safe_load(
            _read_file_at(draft_fd, "examples.yaml").decode("utf-8")
        ) or {"examples": []}
        if not isinstance(doc, dict):
            raise TypeError("examples.yaml 根节点必须是对象")
        doc.setdefault("examples", []).append(
            {"input_file": str(input_rel), "expected_file": str(expected_rel)}
        )
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
    return {
        name
        for name in ("add", "build", "list", "mcp", "audit", "withdraw")
        if name in text
    }


def start_tool_mcp(name: str, dest_root: Path) -> dict:
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": path_error}
    dest_root = checked_root      # 判空后再回赋,同上
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
    )


def start_tool_audit(
    name: str,
    input_path: Path,
    expected_path: Path,
    dest_root: Path,
) -> dict:
    if not input_path.is_file() or not expected_path.is_file():
        return {"ok": False, "error": "新鲜输入和期望输出文件都必须存在。"}
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": path_error}
    dest_root = checked_root      # 判空后再回赋,同上
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
        ],
        kind="tool-audit",
        label=f"审核 {name}",
        expected_artifact=Path(dest_root) / ".repoproof-release-decisions.jsonl",
    )


def start_tool_withdraw(name: str, reason: str, dest_root: Path) -> dict:
    if not reason.strip():
        return {"ok": False, "error": "请填写撤回原因。"}
    checked_root, path_error = _validated_dest_root(Path(dest_root))
    if checked_root is None:
        return {"ok": False, "error": path_error}
    dest_root = checked_root      # 判空后再回赋,同上
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
    )


# ------------------------------------------------------------ 仓库概览 + 样例助手
#
# 两件都是"降低上手门槛"的辅助件,共享一条纪律:**它们不产出判据**。
# 概览是展示件(不进 draft、不填能力描述);样例助手只出候选,真值要人
# 逐条确认。详见 adoption/analysis/repo_overview.py 与
# adoption/intake/example_proposer.py 的模块注释。

def provider_configured() -> bool:
    """进程里有没有模型连接配置(只看在不在,**不读值**)。"""
    return bool(os.environ.get("REPOPROOF_API_KEY")
                and os.environ.get("REPOPROOF_API_BASE"))


def _provider_hint(raw: str) -> str:
    """把"起草通道未配置"翻成人话 + 明确出路(2026-08-27 用户实测)。"""
    if provider_configured():
        return f"模型调用失败:{raw}"
    return ("Studio 启动时没有加载模型连接配置,所以模型相关功能不可用。"
            "两条出路:①勾上「用离线模板(零模型调用)」先把流程走通;"
            "②用 `scripts/run_studio_live.sh` 重启 Studio(它会从 .env 注入连接配置)。"
            f"(原始信息:{raw})")


def read_repo_overview(repo: str, revision: str | None = None) -> dict:
    """匿名浅克隆 + 静态分析 → 仓库概览(零模型;永不执行仓库代码)。"""
    from repoproof.adoption.analysis.repo_overview import build_repo_overview
    from repoproof.adoption.analysis.repository_analyzer import analyze_repository
    from repoproof.ui.services.product_mode import project_root

    if not _valid_public_github_repo(repo):
        return {"ok": False, "error": "当前只支持公开 GitHub 仓库地址。"}
    try:
        report = analyze_repository(
            repo, revision or None,
            cache_root=project_root() / "upstream-cache")
    except Exception as exc:                                    # noqa: BLE001
        return {"ok": False, "error": f"读取失败:{exc}"}
    if report.is_public.value is False:
        return {"ok": False,
                "error": "无法匿名克隆(仓库不存在、私有,或网络到 github.com 被打断)。"}
    return {"ok": True, "overview": build_repo_overview(report),
            "admission_hint": report.risks[:3]}


def summarize_repo_overview(overview: dict, *, offline: bool) -> dict:
    """可选的模型摘要/翻译。产物**只进展示层**,与原文摘录分开标注。"""
    from repoproof.adoption.intake.tool_drafter import (
        DraftError,
        FakeDrafter,
        LiteLLMDrafter,
    )

    try:
        drafter = FakeDrafter() if offline else LiteLLMDrafter()
        doc = drafter.summarize_repo({
            "repository": overview.get("repository", ""),
            "headline": overview.get("headline", ""),
            "prose": (overview.get("prose") or "")[:1500],
            "surfaces": [s.get("value") for s in (overview.get("surfaces") or [])][:15],
        })
    except DraftError as exc:
        return {"ok": False, "error": _provider_hint(str(exc))}
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"模型摘要失败:{exc}"}
    return {"ok": True, "summary": str(doc.get("summary") or ""),
            "drafter": getattr(drafter, "name", "unknown")}


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
    except Exception as exc:                                     # noqa: BLE001
        return None, f"钉版上游不可用:{exc}"


def existing_example_inputs(draft_dir: Path) -> list[str]:
    """已放进 examples/inputs 的输入原文(去重闸与"别再给重复的"都要用)。"""
    out: list[str] = []
    for p in sorted((Path(draft_dir) / "examples" / "inputs").glob("*")):
        if p.is_file():
            try:
                out.append(p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue          # 二进制样例不参与文本去重,如实跳过
    return out


def propose_example_candidates(draft_dir: Path, *, n: int, offline: bool) -> dict:
    """① 模型出候选输入 → ② 钉版上游真跑出实际输出。**不产出真值**。"""
    from repoproof.adoption.intake.example_proposer import (
        ExampleProposalError,
        propose_inputs,
        run_reference_on_candidates,
    )
    from repoproof.adoption.intake.tool_drafter import (
        DraftError,
        FakeDrafter,
        LiteLLMDrafter,
    )

    checked_dir, path_error = _validated_draft_dir(Path(draft_dir), require_existing=True)
    if checked_dir is None:
        return {"ok": False, "error": path_error}
    draft_dir = checked_dir

    overview_doc = yaml.safe_load(
        (draft_dir / "draft.yaml").read_text(encoding="utf-8")) or {}
    goal = str((overview_doc.get("capability") or {}).get("statement")
               or (overview_doc.get("tool") or {}).get("summary") or "")
    upstream, up_err = _draft_upstream_dir(draft_dir)
    if upstream is None:
        return {"ok": False, "error": up_err}

    try:
        drafter = FakeDrafter() if offline else LiteLLMDrafter()
        batch = propose_inputs(
            goal=goal,
            overview={"repository": str((overview_doc.get("source_repo") or {}).get("url") or "")},
            drafter=drafter, n=n,
            existing_inputs=existing_example_inputs(draft_dir))
        batch = run_reference_on_candidates(
            batch, draft_dir=draft_dir, upstream_dir=upstream)
    except (DraftError, ExampleProposalError) as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "error": f"候选生成失败:{exc}"}

    return {"ok": True, "drafter": batch.drafter, "note": batch.note,
            "candidates": [c.model_dump() for c in batch.candidates]}


def confirm_candidate_as_example(draft_dir: Path, candidate: dict, *,
                                 expected_text: str, input_text: str) -> dict:
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
    except Exception as exc:                                     # noqa: BLE001
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
