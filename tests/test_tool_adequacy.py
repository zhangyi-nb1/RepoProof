"""adequacy 闸 T1–T4 扩条的自证(M1 第 5 步 · TOOL_CONTRACT_SCHEMA §六)。

纪律:每条新检查先喂一个违反,证明它查得出,再谈守真任务。断言只看
T 键(checked/failures 前缀),与 C 系 13 条解耦 —— 这里给的
prompt/nodes 是空壳,C 系怎么红不在本文件关心范围。
旧谱系零触发单独钉死(task_family != LOCAL-TOOL 不得多出任何 T 键)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.adoption.assembly.tool_assembler import assemble_tool_task
from repoproof.domain.models import TaskContract, ToolInterface, ToolInterfaceIO, ToolSpec
from repoproof.harness.contract_adequacy import evaluate_adequacy
from repoproof.harness.requirement_spec import load_requirement_spec

_SPEC = ToolSpec(name="pdf-table", summary="s", interface=ToolInterface(
    usage="pdf-table <in>", input=ToolInterfaceIO(kind="file", format="PDF"),
    output=ToolInterfaceIO(kind="stdout", format="markdown-table"),
    exit_codes={"0": "success", "1": "user_error", "2": "internal_error"}))

_EXAMPLES = [
    {"input": "--help", "expected": "contains:usage"},
    {"input_file": "inputs/a.pdf", "expected": "contains:| A |"},
    {"input_file": "inputs/b.pdf", "expected": "contains:| B |"},
    {"input_file": "inputs/c.pdf", "expected": "contains:| C |"},
]


def _assemble(tmp: Path) -> tuple[Path, dict]:
    src = tmp / "src_examples"
    (src / "inputs").mkdir(parents=True)
    for n in "abc":
        (src / "inputs" / f"{n}.pdf").write_text(f"fake {n}", encoding="utf-8")
    info = assemble_tool_task(
        tmp, goal="g", repo_url="https://github.com/jsvine/pdfplumber",
        resolved_commit="deadbeef", distribution="pdfplumber",
        import_module="pdfplumber", license_id="MIT",
        tool=_SPEC, examples=_EXAMPLES, example_src_dir=src)
    return tmp, info


def _tkeys(res) -> dict[str, bool]:
    return {k: v for k, v in res.checked.items() if k.startswith("tool_")}


def _evaluate(root: Path, info: dict, contract: TaskContract, *, with_docs=True):
    spec, _ = load_requirement_spec(
        root / "contracts" / f"{info['task_id']}.requirements.yaml")
    return evaluate_adequacy(
        spec=spec, capability_nodes=[], regression_nodes=[], rendered_prompt="",
        contract=contract,
        tool_example_docs_dir=(root / "oracle" / info["task_id"] / "fixtures"
                               if with_docs else None))


@pytest.fixture()
def assembled(tmp_path):
    root, info = _assemble(tmp_path)
    contract, _ = TaskContract.load_frozen(
        root / "contracts" / f"{info['task_id']}.yaml", require_sidecar=True)
    return root, info, contract


def test_assembled_task_passes_all_t_checks(assembled):
    root, info, contract = assembled
    t = _tkeys(_evaluate(root, info, contract))
    assert t == {"tool_section_present": True, "tool_exit_codes_complete": True,
                 "tool_name_matches_entry_point": True,
                 "tool_example_fixtures_exist": True,
                 "tool_examples_sufficient": True}


def test_legacy_lineage_triggers_zero_t_checks(assembled):
    """task_family != LOCAL-TOOL:一个 T 键都不许出现(旧谱系零变化)。"""
    root, info, contract = assembled
    legacy = contract.model_copy(deep=True)
    legacy.task_family = ""
    assert _tkeys(_evaluate(root, info, legacy)) == {}


def test_t1a_missing_tool_section_is_caught(assembled):
    root, info, contract = assembled
    broken = contract.model_copy(deep=True)
    broken.tool = None
    res = _evaluate(root, info, broken)
    assert res.checked["tool_section_present"] is False
    assert any("missing the `tool` section" in f for f in res.failures)


def test_t1b_incomplete_exit_codes_is_caught(assembled):
    root, info, contract = assembled
    broken = contract.model_copy(deep=True)
    broken.tool.interface.exit_codes.pop("2")
    res = _evaluate(root, info, broken)
    assert res.checked["tool_exit_codes_complete"] is False


def test_t2_name_entry_point_fork_is_caught(assembled):
    root, info, contract = assembled
    broken = contract.model_copy(deep=True)
    broken.tool.name = "pdf-tables"          # 与 entry_point 劈叉
    res = _evaluate(root, info, broken)
    assert res.checked["tool_name_matches_entry_point"] is False


def test_t3_missing_example_file_is_caught(assembled):
    root, info, contract = assembled
    (root / "oracle" / info["task_id"] / "fixtures" / "inputs" / "b.pdf").unlink()
    res = _evaluate(root, info, contract)
    assert res.checked["tool_example_fixtures_exist"] is False
    assert any("inputs/b.pdf" in f for f in res.failures)


def test_t4_empty_held_out_is_caught(assembled):
    root, info, contract = assembled
    held = root / "oracle" / info["task_id"] / "fixtures" / "held_out_documents.json"
    held.write_text(json.dumps({"examples": []}), encoding="utf-8")
    res = _evaluate(root, info, contract)
    assert res.checked["tool_examples_sufficient"] is False


def test_docs_dir_omitted_skips_only_example_checks(assembled):
    """未给样例文档目录:T1/T2 照查,T3/T4 不触发(不造假绿也不误红)。"""
    root, info, contract = assembled
    t = _tkeys(_evaluate(root, info, contract, with_docs=False))
    assert set(t) == {"tool_section_present", "tool_exit_codes_complete",
                      "tool_name_matches_entry_point"}
