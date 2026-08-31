"""LOCAL-TOOL 确认流(M2-b · RFC-010 [G1] 的人闸与冻结)。

工作流:
    tool-intake --draft-out <dir>   → draft 束(draft.yaml / GAPS.md /
                                      examples/ / examples.yaml /
                                      reference_impl.py 骨架)
    人(或 M2-d 起草层)补缺        → 填 LLM/USER 字段、放样例文件、写 reference
    tool-confirm --draft-dir <dir>  → D 系确认闸(一次报全) → 装配
                                      (assemble_tool_task) → adequacy T 闸
                                      全绿 → 冻结契约落仓,返回 next 命令

[G1] 边界在此闭合:冻结后 LLM 不再触碰题面;确认闸与 adequacy 全为
确定性检查;样例真值(examples/ 文件与期望)只能来自人放置的文件。
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

import yaml
from pydantic import ValidationError

from repoproof.adoption.assembly.example_compiler import CompileError
from repoproof.adoption.assembly.tool_assembler import assemble_tool_task
from repoproof.adoption.intake.draft_readiness import (
    DRAFT_YAML,
    EXAMPLES_YAML,
    REFERENCE_LOCK,
    REFERENCE_PY,
    SEMANTIC_VERIFIER_PY,
    draft_completion_problems,
    evaluate_draft_readiness,
    resolved_dependency_lock,
)
from repoproof.adoption.intake.intent_contract import (
    IntentContractError,
    confirm_intent_contract,
    frozen_intent_snapshot,
)
from repoproof.domain.models import TaskContract, ToolSpec
from repoproof.harness.contract_adequacy import evaluate_adequacy
from repoproof.harness.requirement_spec import load_requirement_spec

_REFERENCE_SKELETON = '''"""reference:真调 pinned 上游的参考实现(出题人提供,绝不交付)。

补完后删除本注释与 NotImplementedError。约定:
  - extract(input_path) -> str;
  - 必须 import 并调用 pinned 上游(弱档采纳执法的通关正控);
  - 坏输入抛 UserInputError(骨架转 exit 1)。
"""
from pathlib import Path

# TODO: import <上游模块>


class UserInputError(ValueError):
    pass


def extract(input_path: Path) -> str:
    raise NotImplementedError("TODO: 真调上游实现能力")
'''

_SEMANTIC_VERIFIER_SKELETON = '''"""task-authored semantic verifier(oracle only, never delivered).

Implement ``verify(input_path, artifact_path)`` returning exactly ``ok``,
``reason_codes`` and ``checked_commitment_ids``. Recompute the public semantic
commitments through the pinned upstream. The verdict must consume values
returned by real upstream calls; a decorative call followed by a local
reimplementation is not verification. Do not import reference_impl and do not
embed any public or held-out sample body/expected value.
"""
from pathlib import Path

# TODO: import <上游模块>


def verify(input_path: Path, artifact_path: Path) -> dict:
    raise NotImplementedError("TODO: independent semantic verification")
'''

_EXAMPLES_SKELETON = """# golden 样例声明(验收真值,owner=USER)。
# 每项:input(argv 字符串)或 input_file(相对 examples/ 的路径)二选一;
#       expected("contains:X" 或全等串)或 expected_file 二选一。
# 纪律:>=3 组、至少一个文件样例;尾部按每 4 留 1 切 held-out
# (held-out 文件本体只进 oracle,agent 不可见——防硬编码层)。
examples: []
"""


class ConfirmError(RuntimeError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def confirm_tool_intent_file(draft_dir: Path) -> dict:
    """Atomically bind the current public semantics without following symlinks."""

    draft_dir = Path(draft_dir).expanduser()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_fd: int | None = None
    source_fd: int | None = None
    temporary = f".{DRAFT_YAML}.{secrets.token_hex(12)}.tmp"
    try:
        directory_fd = os.open(draft_dir, flags | nofollow)
        source_fd = os.open(DRAFT_YAML, os.O_RDONLY | nofollow, dir_fd=directory_fd)
        chunks: list[bytes] = []
        while chunk := os.read(source_fd, 1024 * 1024):
            chunks.append(chunk)
        draft = yaml.safe_load(b"".join(chunks).decode("utf-8")) or {}
        if not isinstance(draft, dict):
            raise IntentContractError("DRAFT_DOCUMENT_INVALID")
        readiness = evaluate_draft_readiness(draft, draft_dir)
        if not readiness.compatible or not readiness.current:
            raise IntentContractError(
                readiness.reason_codes[0] if readiness.reason_codes else "DRAFT_INCOMPATIBLE"
            )
        confirm_intent_contract(draft)
        payload = yaml.safe_dump(
            draft,
            allow_unicode=True,
            sort_keys=False,
        ).encode("utf-8")
        target_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        try:
            with os.fdopen(target_fd, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(target_fd)
        os.replace(
            temporary,
            DRAFT_YAML,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
        return frozen_intent_snapshot(draft)
    except (IntentContractError, OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfirmError([f"语义确认失败:{exc}"]) from exc
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if directory_fd is not None:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)


# ------------------------------------------------------------ draft 束落盘

def write_draft_bundle(report, dest: Path) -> Path:
    """ToolIntakeReport → 可编辑的 draft 束。目标已存在则拒绝。"""
    dest = Path(dest)
    if dest.exists():
        raise ConfirmError([f"draft 目标已存在,拒绝覆盖:{dest}"])
    (dest / "examples").mkdir(parents=True)
    (dest / DRAFT_YAML).write_text(
        yaml.safe_dump(report.draft, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    gaps_md = ["# 草稿缺口清单(补完后跑 tool-confirm)", "",
               f"- admission:{report.admission.status}", ""]
    for g in report.draft_gaps:
        gaps_md.append(f"- [ ] `{g.field}`(owner={g.owner}):{g.why}")
    gaps_md += ["", "## admission 待答(NEED_INFORMATION 时)", ""]
    gaps_md += [f"- [ ] {q}" for q in report.admission.questions] or ["(无)"]
    (dest / "GAPS.md").write_text("\n".join(gaps_md) + "\n", encoding="utf-8")
    (dest / EXAMPLES_YAML).write_text(_EXAMPLES_SKELETON, encoding="utf-8")
    (dest / REFERENCE_PY).write_text(_REFERENCE_SKELETON, encoding="utf-8")
    (dest / SEMANTIC_VERIFIER_PY).write_text(
        _SEMANTIC_VERIFIER_SKELETON,
        encoding="utf-8",
    )
    reference_lock = str(getattr(report, "reference_lock", "") or "")
    if reference_lock.strip():
        (dest / REFERENCE_LOCK).write_text(reference_lock, encoding="utf-8")
    return dest


# ------------------------------------------------------- D 系确认闸(一次报全)

def check_draft_complete(
    draft: dict,
    draft_dir: Path,
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Compatibility wrapper over the Core-owned structured readiness."""

    return draft_completion_problems(
        draft,
        draft_dir,
        project_root=project_root,
    )


# ------------------------------------------------------------------ 确认入口

def confirm_tool_draft(draft_dir: Path, project_root: Path) -> dict:
    """→ {task_id, files, public, held, next}。任何一道闸不过即 ConfirmError。"""
    draft_dir = Path(draft_dir)
    draft_p = draft_dir / DRAFT_YAML
    if not draft_p.is_file():
        raise ConfirmError([f"{DRAFT_YAML} 不存在:{draft_p}"])
    draft = yaml.safe_load(draft_p.read_text(encoding="utf-8")) or {}

    problems = check_draft_complete(
        draft,
        draft_dir,
        project_root=project_root,
    )
    if problems:
        raise ConfirmError(problems)

    try:
        spec = ToolSpec.model_validate(draft["tool"])
    except ValidationError as e:
        raise ConfirmError([f"tool 分节非法:{e}"]) from e
    examples = (yaml.safe_load((draft_dir / EXAMPLES_YAML)
                               .read_text(encoding="utf-8")) or {})["examples"]
    sr = draft["source_repo"]
    # 输入扩展名从首个文件样例推导(接口契约 malformed fixture 同后缀)
    first_file = next((e.get("input_file") for e in examples
                       if e.get("input_file")), None)
    input_ext = Path(first_file).suffix if first_file else ".dat"

    try:
        intent_contract = frozen_intent_snapshot(draft)
        info = assemble_tool_task(
            Path(project_root),
            goal=draft["capability"]["statement"],
            repo_url=sr["url"], resolved_commit=sr["resolved_commit"],
            distribution=sr["distribution"], import_module=sr["import_module"],
            license_id=sr["license"], tool=spec, examples=examples,
            example_src_dir=draft_dir / "examples",
            reference_impl=(draft_dir / REFERENCE_PY).read_text(encoding="utf-8"),
            semantic_verifier_source=(draft_dir / SEMANTIC_VERIFIER_PY).read_text(
                encoding="utf-8"
            ),
            # 草稿束写了就以人写的为准;没写就从钉版树派生 —— 这份锁
            # 缺席会让备轮漏装上游、positive 彩排也不预装,`import <上游>`
            # 必然在会话里失败；因此它不是可静默省略的输入。
            reference_lock=resolved_dependency_lock(
                draft,
                draft_dir,
                project_root=project_root,
            ),
            capability_output_schema=draft["capability"]["output_schema"],
            intent_contract=intent_contract,
            input_ext=input_ext,
            # 域适用性(M4 chardet):"全域合法输入"类工具声明豁免 malformed
            malformed_applicable=bool(
                draft["tool"].get("malformed_applicable", True)))
    except (CompileError, IntentContractError, ValidationError, OSError) as e:
        raise ConfirmError([f"装配失败:{e}"]) from e

    # adequacy T 闸(冻结后的独立复核;T 键必须全绿)
    contract_path = Path(project_root) / "contracts" / f"{info['task_id']}.yaml"
    contract, _ = TaskContract.load_frozen(
        contract_path,
        require_sidecar=True)
    rs, _ = load_requirement_spec(
        Path(project_root) / "contracts" / f"{info['task_id']}.requirements.yaml")
    res = evaluate_adequacy(
        spec=rs, capability_nodes=[], regression_nodes=[], rendered_prompt="",
        contract_path=contract_path,
        contract=contract,
        tool_example_docs_dir=(Path(project_root) / "oracle" / info["task_id"]
                               / "fixtures"))
    tkeys = {k: v for k, v in res.checked.items() if k.startswith("tool_")}
    bad = sorted(k for k, v in tkeys.items() if not v)
    if not tkeys or bad:
        raise ConfirmError([f"adequacy T 闸未全绿:{bad or 'T 键缺席'};"
                            f"failures={[f for f in res.failures if 'tool' in f]}"])
    return info
