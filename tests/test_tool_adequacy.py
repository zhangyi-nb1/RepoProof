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
from repoproof.domain.models import (
    TaskContract,
    ToolInterface,
    ToolInterfaceIO,
    ToolOutputContract,
    ToolSpec,
)
from repoproof.harness.contract_adequacy import evaluate_adequacy
from repoproof.harness.requirement_spec import load_requirement_spec

_SPEC = ToolSpec(name="pdf-table", summary="s", interface=ToolInterface(
    usage="pdf-table <in>", input=ToolInterfaceIO(kind="file", format="PDF"),
    output=ToolInterfaceIO(kind="stdout", format="markdown-table"),
    exit_codes={"0": "success", "1": "user_error", "2": "internal_error"}))

_REFERENCE_IMPL = (
    "\"\"\"reference:真 import 上游的参考实现(出题人提供,绝不交付)。\"\"\"\n"
    "import pdfplumber  # noqa: F401 — 弱档采纳执法的正控锚\n"
    "from pathlib import Path\n\n\n"
    "class UserInputError(ValueError):\n    pass\n\n\n"
    "def extract(input_path: Path) -> str:\n"
    "    raise NotImplementedError(\'E2E 合成任务另供 reference\')\n")

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
        tool=_SPEC, examples=_EXAMPLES, example_src_dir=src,
        reference_impl=_REFERENCE_IMPL)
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
                 "tool_package_not_shadowing_upstream": True,
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


def test_t5_package_shadowing_upstream_is_caught(assembled):
    """m3 集成实测:工具包名与上游模块同名 → src/ 遮蔽上游,必须硬拒。"""
    root, info, contract = assembled
    broken = contract.model_copy(deep=True)
    broken.tool.name = "pdfplumber"
    broken.target_project.entry_point = "pdfplumber"
    res = _evaluate(root, info, broken)
    assert res.checked["tool_package_not_shadowing_upstream"] is False
    assert any("collides" in f for f in res.failures)


def test_t5b_distribution_name_collision_is_caught(assembled):
    """M4 slugify 实测:分发名规范化撞(python_slugify ≡ python-slugify)
    → pip -e . 与上游互顶卸载,同键硬拒。"""
    root, info, contract = assembled
    broken = contract.model_copy(deep=True)
    broken.tool.name = "pdfplumber-tool"
    broken.target_project.entry_point = "pdfplumber-tool"
    broken.source_repo.distribution = "pdfplumber-tool"   # 合成同名分发
    res = _evaluate(root, info, broken)
    assert res.checked["tool_package_not_shadowing_upstream"] is False
    assert any("PEP 503" in f for f in res.failures)


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
                      "tool_name_matches_entry_point",
                      "tool_package_not_shadowing_upstream"}


# ------------------------------------------ M5 v2 JSON output contract controls

_JSON_CONTRACT = ToolOutputContract(
    media_type="application/json",
    root_type="object",
    required={"language": "string", "token_count": "integer"},
)
_JSON_SPEC = ToolSpec(
    schema_version=2,
    name="json-report",
    summary="s",
    interface=ToolInterface(
        usage="json-report <in>",
        input=ToolInterfaceIO(kind="file", format="TXT"),
        output=ToolInterfaceIO(kind="stdout", format="JSON", contract=_JSON_CONTRACT),
        exit_codes={"0": "success", "1": "user_error", "2": "internal_error"},
    ),
)


def _assemble_json(tmp: Path) -> tuple[Path, dict, TaskContract]:
    src = tmp / "json_examples"
    (src / "inputs").mkdir(parents=True)
    (src / "expected").mkdir(parents=True)
    for name in "abc":
        (src / "inputs" / f"{name}.txt").write_text(name, encoding="utf-8")
        (src / "expected" / f"{name}.json").write_text(
            json.dumps({"language": name, "token_count": 1}), encoding="utf-8")
    info = assemble_tool_task(
        tmp,
        goal="g",
        repo_url="u",
        resolved_commit="c",
        distribution="d",
        import_module="d_mod",
        license_id="MIT",
        tool=_JSON_SPEC,
        examples=[
            {"input_file": "inputs/a.txt", "expected_file": "expected/a.json"},
            {"input_file": "inputs/b.txt", "expected_file": "expected/b.json"},
            {"input_file": "inputs/c.txt", "expected_file": "expected/c.json"},
        ],
        example_src_dir=src,
        reference_impl=_REFERENCE_IMPL,
        capability_output_schema="LanguageTokenReport",
    )
    contract, _ = TaskContract.load_frozen(
        tmp / "contracts" / f"{info['task_id']}.yaml", require_sidecar=True)
    return tmp, info, contract


@pytest.fixture()
def json_assembled(tmp_path):
    return _assemble_json(tmp_path)


def test_pos_json_report_passes_t6_through_t9(json_assembled):
    root, info, contract = json_assembled
    t = _tkeys(_evaluate(root, info, contract))
    assert t["tool_output_contract_present"] is True
    assert t["tool_golden_output_parseable"] is True
    assert t["tool_exact_structured_golden_exists"] is True
    assert t["tool_schema_fields_agree"] is True


def test_t6_missing_v2_output_contract_is_caught(json_assembled):
    root, info, contract = json_assembled
    broken = contract.model_copy(deep=True)
    broken.tool.interface.output.contract = None
    res = _evaluate(root, info, broken)
    assert res.checked["tool_output_contract_present"] is False


@pytest.mark.parametrize("bad", [
    "helo\nwrld\n",                         # NC_json_plaintext
    '["helo"]',                              # NC_json_wrong_root
    '{"token_count":1}',                     # NC_json_missing_field
])
def test_t7_rejects_invalid_json_golden(json_assembled, bad: str):
    root, info, contract = json_assembled
    golden = (root / "oracle" / info["task_id"] / "fixtures"
              / "expected" / "a.json")
    golden.write_text(bad, encoding="utf-8")
    res = _evaluate(root, info, contract)
    assert res.checked["tool_golden_output_parseable"] is False


def test_t8_contains_only_cannot_prove_structured_golden(json_assembled):
    root, info, contract = json_assembled
    fixtures = root / "oracle" / info["task_id"] / "fixtures"
    for name in ("public_documents.json", "held_out_documents.json"):
        path = fixtures / name
        doc = json.loads(path.read_text(encoding="utf-8"))
        for example in doc["examples"]:
            example.pop("expected_file", None)
            example["expected"] = 'contains:"language"'
        path.write_text(json.dumps(doc), encoding="utf-8")
    res = _evaluate(root, info, contract)
    assert res.checked["tool_exact_structured_golden_exists"] is False


def test_t9_manifest_projection_or_schema_fork_is_caught(json_assembled):
    root, info, contract = json_assembled
    manifest = root / contract.target_project.path / "tool.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["interface"]["output"]["contract"]["root_type"] = "array"
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    res = _evaluate(root, info, contract)
    assert res.checked["tool_schema_fields_agree"] is False


def test_v1_json_without_contract_does_not_retroactively_trigger_t6_t9(assembled):
    """Historical v1 JSON contracts keep their original adequacy semantics."""
    root, info, contract = assembled
    old_json = contract.model_copy(deep=True)
    old_json.tool.interface.output.format = "JSON"
    old_json.tool.interface.output.contract = None
    t = _tkeys(_evaluate(root, info, old_json))
    assert not any(k in t for k in (
        "tool_output_contract_present",
        "tool_golden_output_parseable",
        "tool_exact_structured_golden_exists",
        "tool_schema_fields_agree",
    ))


def _remove_frozen_output_contract(root: Path, info: dict) -> Path:
    """Mutate only a temporary synthetic task and re-freeze its sidecar."""
    import hashlib

    import yaml

    contract_path = root / "contracts" / f"{info['task_id']}.yaml"
    doc = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    doc["tool"]["interface"]["output"].pop("contract")
    contract_path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
    Path(str(contract_path) + ".sha256").write_text(
        f"{digest}  {contract_path.name}\n", encoding="utf-8")
    return contract_path


def test_task_check_executes_v2_t6_gate(json_assembled):
    from repoproof.runner.scaffold import task_check

    root, info, _contract = json_assembled
    _remove_frozen_output_contract(root, info)
    result = task_check(root, info["task_id"])
    assert any("tool_output_contract_present" in gap for gap in result["gaps"])


def test_formal_run_adequacy_executes_v2_t6_gate(json_assembled, monkeypatch):
    """The official runner path must pass contract + tool fixtures to adequacy."""
    from types import SimpleNamespace

    from repoproof.harness import task_package
    from repoproof.harness.requirement_spec import load_requirement_spec
    from repoproof.runner import agent_run

    root, info, _contract = json_assembled
    contract_path = _remove_frozen_output_contract(root, info)
    spec, spec_sha = load_requirement_spec(
        root / "contracts" / f"{info['task_id']}.requirements.yaml")
    collection = {
        "capability_nodes": sorted(spec.all_oracle_nodes()),
        "regression_nodes": [],
    }
    task_package.collection_path_for(contract_path).write_text(
        json.dumps(collection), encoding="utf-8")
    monkeypatch.setattr(
        task_package,
        "load_and_verify",
        lambda *_a, **_kw: SimpleNamespace(
            environment_constraints=None, controls_summary=None),
    )
    monkeypatch.setattr(
        agent_run,
        "render_task_prompt",
        lambda *_a, **_kw: ("", spec, spec_sha),
    )
    result = agent_run.run_adequacy_gate(contract_path, root)
    assert any("tool_output_contract_present" in failure
               for failure in result["failures"])
