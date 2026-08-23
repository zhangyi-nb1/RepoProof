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

from pathlib import Path

import yaml
from pydantic import ValidationError

from repoproof.adoption.assembly.example_compiler import CompileError
from repoproof.adoption.assembly.tool_assembler import assemble_tool_task
from repoproof.domain.models import TaskContract, ToolSpec
from repoproof.harness.contract_adequacy import evaluate_adequacy
from repoproof.harness.requirement_spec import load_requirement_spec

DRAFT_YAML = "draft.yaml"
EXAMPLES_YAML = "examples.yaml"
REFERENCE_PY = "reference_impl.py"
REFERENCE_LOCK = "reference.lock.txt"

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
    return dest


# ------------------------------------------------------- D 系确认闸(一次报全)

def check_draft_complete(draft: dict, draft_dir: Path) -> list[str]:
    problems: list[str] = []

    def need(path: str, value) -> None:
        empty = (not value.strip()) if isinstance(value, str) else (not value)
        if empty:
            problems.append(f"D:{path} 为空 —— 见 GAPS.md 对应缺口")

    sr = draft.get("source_repo") or {}
    for k in ("distribution", "import_module", "resolved_commit", "license", "url"):
        need(f"source_repo.{k}", sr.get(k))
    tool = draft.get("tool") or {}
    need("tool.name", tool.get("name"))
    need("tool.summary", tool.get("summary"))
    iface = tool.get("interface") or {}
    need("tool.interface.input.format", (iface.get("input") or {}).get("format"))
    need("tool.interface.output.format", (iface.get("output") or {}).get("format"))
    cap = draft.get("capability") or {}
    need("capability.statement", cap.get("statement"))
    need("capability.output_schema", cap.get("output_schema"))

    ex_file = draft_dir / EXAMPLES_YAML
    examples: list = []
    if not ex_file.is_file():
        problems.append(f"D:{EXAMPLES_YAML} 缺失")
    else:
        examples = (yaml.safe_load(ex_file.read_text(encoding="utf-8"))
                    or {}).get("examples") or []
        if len(examples) < 3:
            problems.append(f"D:examples 仅 {len(examples)} 组(需 >=3,"
                            "含文件样例;尾部自动切 held-out)")

    ref = draft_dir / REFERENCE_PY
    if not ref.is_file():
        problems.append(f"D:{REFERENCE_PY} 缺失")
    else:
        text = ref.read_text(encoding="utf-8")
        if "TODO" in text or "NotImplementedError" in text:
            problems.append("D:reference_impl 仍是骨架(含 TODO/NotImplementedError)"
                            " —— 弱档执法下没有真 reference,fake 全链无正控")
        if sr.get("import_module") and f"import {sr['import_module']}" not in text:
            problems.append(f"D:reference_impl 未 import {sr['import_module']}"
                            " —— 通关正控必须真调 pinned 上游")
    return problems


# ------------------------------------------------------------------ 确认入口

def confirm_tool_draft(draft_dir: Path, project_root: Path) -> dict:
    """→ {task_id, files, public, held, next}。任何一道闸不过即 ConfirmError。"""
    draft_dir = Path(draft_dir)
    draft_p = draft_dir / DRAFT_YAML
    if not draft_p.is_file():
        raise ConfirmError([f"{DRAFT_YAML} 不存在:{draft_p}"])
    draft = yaml.safe_load(draft_p.read_text(encoding="utf-8")) or {}

    problems = check_draft_complete(draft, draft_dir)
    if problems:
        raise ConfirmError(problems)

    try:
        spec = ToolSpec.model_validate(draft["tool"])
    except ValidationError as e:
        raise ConfirmError([f"tool 分节非法:{e}"]) from e
    examples = (yaml.safe_load((draft_dir / EXAMPLES_YAML)
                               .read_text(encoding="utf-8")) or {})["examples"]
    ref_lock = draft_dir / REFERENCE_LOCK
    sr = draft["source_repo"]
    # 输入扩展名从首个文件样例推导(接口契约 malformed fixture 同后缀)
    first_file = next((e.get("input_file") for e in examples
                       if e.get("input_file")), None)
    input_ext = Path(first_file).suffix if first_file else ".dat"

    try:
        info = assemble_tool_task(
            Path(project_root),
            goal=draft["capability"]["statement"],
            repo_url=sr["url"], resolved_commit=sr["resolved_commit"],
            distribution=sr["distribution"], import_module=sr["import_module"],
            license_id=sr["license"], tool=spec, examples=examples,
            example_src_dir=draft_dir / "examples",
            reference_impl=(draft_dir / REFERENCE_PY).read_text(encoding="utf-8"),
            reference_lock=(ref_lock.read_text(encoding="utf-8")
                            if ref_lock.is_file() else ""),
            input_ext=input_ext)
    except (CompileError, ValidationError, OSError) as e:
        raise ConfirmError([f"装配失败:{e}"]) from e

    # adequacy T 闸(冻结后的独立复核;T 键必须全绿)
    contract, _ = TaskContract.load_frozen(
        Path(project_root) / "contracts" / f"{info['task_id']}.yaml",
        require_sidecar=True)
    rs, _ = load_requirement_spec(
        Path(project_root) / "contracts" / f"{info['task_id']}.requirements.yaml")
    res = evaluate_adequacy(
        spec=rs, capability_nodes=[], regression_nodes=[], rendered_prompt="",
        contract=contract,
        tool_example_docs_dir=(Path(project_root) / "oracle" / info["task_id"]
                               / "fixtures"))
    tkeys = {k: v for k, v in res.checked.items() if k.startswith("tool_")}
    bad = sorted(k for k, v in tkeys.items() if not v)
    if not tkeys or bad:
        raise ConfirmError([f"adequacy T 闸未全绿:{bad or 'T 键缺席'};"
                            f"failures={[f for f in res.failures if 'tool' in f]}"])
    return info
