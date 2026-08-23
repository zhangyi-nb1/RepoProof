"""LOCAL-TOOL 装配器的钉死(M1 第 3 步 · TOOL_READY_GATE §五控制矩阵)。

核心是**真跑级自证**:装配出的每个控制变体接进骨架,跑装配出的验收
(capability + 接口契约),断言它死在声明的那一处、且只死在那一处附近
—— 检查器(这里是"装配出的验收测试")必须先被合成缺陷证明查得出。

NC_reimpl 在 oracle 上全绿是**设计使然**(它的判死属 provenance 层),
本文件喂它给 check_upstream_provenance 证明那一层真的抓得住。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from repoproof.adoption.assembly.example_compiler import CompileError
from repoproof.adoption.assembly.tool_assembler import assemble_tool_task
from repoproof.domain.models import TaskContract, ToolInterface, ToolInterfaceIO, ToolSpec
from repoproof.verification.provenance import check_upstream_provenance

_SPEC = ToolSpec(name="pdf-table", summary="从 PDF 提取表格输出 Markdown",
                 interface=ToolInterface(
                     usage="pdf-table <input.pdf> [--out FILE]",
                     input=ToolInterfaceIO(kind="file", format="PDF"),
                     output=ToolInterfaceIO(kind="stdout", format="markdown-table"),
                     exit_codes={"0": "success", "1": "user_error", "2": "internal_error"}))

# 顺序刻意:文件样例压尾部,保证 held-out(取尾部)是文件样例 ——
# held 若是 --help 这类骨架层样例,NC_hardcode 就杀不动了。
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
    {"input_file": "inputs/b.pdf", "expected_file": "expected/b.md"},
    {"input_file": "inputs/c.pdf", "expected": "contains:| C |"},
]


def _make_src(tmp: Path) -> Path:
    src = tmp / "example_src"
    (src / "inputs").mkdir(parents=True)
    (src / "expected").mkdir(parents=True)
    (src / "inputs" / "a.pdf").write_text("fake-pdf A", encoding="utf-8")
    (src / "inputs" / "b.pdf").write_text("fake-pdf B", encoding="utf-8")
    (src / "inputs" / "c.pdf").write_text("fake-pdf C", encoding="utf-8")
    (src / "expected" / "b.md").write_text("| B |\n|---|\n| 2 |\n", encoding="utf-8")
    return src


@pytest.fixture(scope="module")
def assembled(tmp_path_factory) -> tuple[Path, dict]:
    tmp = tmp_path_factory.mktemp("tool_asm")
    info = assemble_tool_task(
        tmp, goal="把 pdfplumber 的表格提取能力包装为本地 CLI 工具",
        repo_url="https://github.com/jsvine/pdfplumber", resolved_commit="deadbeef",
        distribution="pdfplumber", import_module="pdfplumber", license_id="MIT",
        tool=_SPEC, examples=_EXAMPLES, example_src_dir=_make_src(tmp),
        reference_impl=_REFERENCE_IMPL, reference_lock="pdfplumber==0.11.0\n")
    return tmp, info


# ------------------------------------------------------------------ 完整性

def test_contract_frozen_and_tool_section_parses(assembled):
    root, info = assembled
    c, _ = TaskContract.load_frozen(
        root / "contracts" / f"{info['task_id']}.yaml", require_sidecar=True)
    assert c.task_family == "LOCAL-TOOL" and c.adoption_shape == "TOOL_ONBOARDING"
    assert c.tool is not None and c.tool.name == "pdf-table"
    assert c.target_project.kind == "local_tool"
    assert c.constraints.editable_zones == ["tool"]


def test_skeleton_layout_complete(assembled):
    root, info = assembled
    skel = root / "fixtures" / "tool_skeleton_pdf-table"
    for rel in ("tool.json", "README.md", "bin/pdf-table", "build.sh",
                "pyproject.toml", "requirements.lock.txt",
                "src/pdf_table/__init__.py", "src/pdf_table/__main__.py",
                "src/pdf_table/main.py", "src/pdf_table/impl.py",
                "public_examples/truth_table.json",
                "public_tests/test_public_contract.py"):
        assert (skel / rel).is_file(), f"骨架缺 {rel}"
    m = json.loads((skel / "tool.json").read_text(encoding="utf-8"))
    assert m["verification"] is None, "骨架 manifest 的 verification 必须为 null(harness 后填)"
    assert m["interface"] == _SPEC.interface.model_dump(), "manifest 与契约 ToolSpec 必须同源"


def test_held_out_example_files_only_in_oracle(assembled):
    """文件样例的 held-out 隐藏 = 文件本体只进 oracle(G2 第一层)。"""
    root, info = assembled
    pub_fix = root / "fixtures" / "tool_skeleton_pdf-table" / "public_tests" / "fixtures"
    assert (pub_fix / "inputs" / "a.pdf").is_file()
    assert not (pub_fix / "inputs" / "c.pdf").exists(), "held-out 样例文件泄进公开区"
    ora_fix = root / "oracle" / info["task_id"] / "fixtures"
    assert (ora_fix / "inputs" / "c.pdf").is_file()
    pub_reg = root / "fixtures" / "tool_skeleton_pdf-table" / "public_tests"
    assert (pub_reg / "test_interface_contract.py").is_file()
    assert (ora_fix / "malformed.pdf").is_file()


def test_malformed_not_applicable_domain(tmp_path):
    """M4 chardet 实测:编码检测器对任意字节流都合法 —— 豁免开关下
    malformed 节点/fixture/NC_badexit 全部不生成,requirements 一致。"""
    from repoproof.harness.requirement_spec import load_requirement_spec

    src = _make_src(tmp_path)
    info = assemble_tool_task(
        tmp_path, goal="g", repo_url="u", resolved_commit="c",
        distribution="d", import_module="d_mod", license_id="MIT", tool=_SPEC,
        examples=_EXAMPLES, example_src_dir=src,
        reference_impl=_REFERENCE_IMPL, malformed_applicable=False)
    cap = (tmp_path / "oracle" / info["task_id"] / "test_capability.py").read_text(
        encoding="utf-8")
    assert "test_malformed_input_is_user_error" not in cap
    assert "test_deterministic_output" in cap
    assert not (tmp_path / "oracle" / info["task_id"] / "fixtures"
                / "malformed.pdf").exists()
    assert not (tmp_path / "controls" / info["task_id"]
                / "negative_badexit").exists()
    spec, _ = load_requirement_spec(
        tmp_path / "contracts" / f"{info['task_id']}.requirements.yaml")
    nodes = " ".join(n for r in spec.requirements for n in r.oracle_nodes)
    assert "malformed" not in nodes


def test_yaml_injection_safe_expected_strings(tmp_path):
    """M4 pyyaml 实测:断言串含引号+冒号(contains:\"greeting\": \"你好\")
    炸掉手拼 requirements.yaml —— 装配产物必须可加载。"""
    from repoproof.harness.requirement_spec import load_requirement_spec

    src = _make_src(tmp_path)
    info = assemble_tool_task(
        tmp_path, goal="g", repo_url="u", resolved_commit="c",
        distribution="d", import_module="d_mod", license_id="MIT", tool=_SPEC,
        examples=[
            {"input": "--help", "expected": "contains:usage"},
            {"input_file": "inputs/a.pdf",
             "expected": 'contains:"greeting": "你好"'},
            {"input_file": "inputs/b.pdf", "expected": "contains:| B |"},
            {"input_file": "inputs/c.pdf", "expected": "contains:x"},
        ],
        example_src_dir=src, reference_impl=_REFERENCE_IMPL)
    spec, _ = load_requirement_spec(
        tmp_path / "contracts" / f"{info['task_id']}.requirements.yaml")
    joined = " ".join(e for r in spec.requirements for e in r.examples)
    assert '"greeting": "你好"' in joined
    from repoproof.domain.models import TaskContract

    TaskContract.load_frozen(
        tmp_path / "contracts" / f"{info['task_id']}.yaml", require_sidecar=True)


def test_refuses_when_no_file_example_or_no_held_out(tmp_path):
    src = _make_src(tmp_path)
    with pytest.raises(CompileError):
        assemble_tool_task(
            tmp_path, goal="g", repo_url="u", resolved_commit="c",
            distribution="d", import_module="d", license_id="MIT", tool=_SPEC,
            examples=[{"input": "--help", "expected": "contains:u"}] * 3,
            example_src_dir=src, reference_impl=_REFERENCE_IMPL)


# ------------------------------------------------- 真跑:五变体红绿落点

def _session(root: Path, info: dict, tmp: Path, impl_variant: str | None) -> Path:
    """复制骨架为一个'会话',可选覆盖控制组 impl;返回工具 shim 路径。"""
    skel = root / "fixtures" / "tool_skeleton_pdf-table"
    sess = tmp / (impl_variant or "skeleton")
    shutil.copytree(skel, sess)
    if impl_variant:
        shutil.copy2(root / "controls" / info["task_id"] / impl_variant / "impl.py",
                     sess / "src" / "pdf_table" / "impl.py")
    shim = sess / "tool_shim.py"
    shim.write_text(f"""#!{sys.executable}
import sys
sys.path.insert(0, {str(sess / 'src')!r})
from pdf_table.main import cli
sys.exit(cli(sys.argv[1:]))
""", encoding="utf-8")
    shim.chmod(0o755)
    return shim


def _failed_nodes(shim: Path, test_file: Path) -> tuple[int, set[str]]:
    env = dict(os.environ, REPOPROOF_TOOL_BIN=str(shim))
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider",
         str(test_file)],
        capture_output=True, text=True, env=env, timeout=300)
    return r.returncode, set(re.findall(r"^FAILED .*::(\w+)", r.stdout, re.M))


@pytest.fixture(scope="module")
def matrix(assembled, tmp_path_factory):
    """五变体 × (capability, regression) 的失败节点矩阵,真跑一次共用。"""
    root, info = assembled
    tmp = tmp_path_factory.mktemp("sessions")
    ora = root / "oracle" / info["task_id"]
    out = {}
    for variant in ("positive", "negative_empty", "negative_hardcode",
                    "negative_reimpl", "negative_badexit"):
        shim = _session(root, info, tmp, variant)
        cap_rc, cap = _failed_nodes(shim, ora / "test_capability.py")
        reg_rc, reg = _failed_nodes(
            shim, shim.parent / "public_tests" / "test_interface_contract.py")
        out[variant] = {"cap_rc": cap_rc, "cap": cap, "reg_rc": reg_rc, "reg": reg}
    return out


def test_positive_control_all_green(matrix):
    m = matrix["positive"]
    assert (m["cap_rc"], m["reg_rc"]) == (0, 0), f"正控红了 —— 判据成墙:{m}"


def test_nc_empty_dies_on_public_examples(matrix):
    m = matrix["negative_empty"]
    assert {"test_example_2", "test_example_3",
            "test_held_example_1"} <= m["cap"], f"空实现竟然过样例:{m}"


def test_nc_hardcode_dies_exactly_on_held_out(matrix):
    """防硬编码层的存在理由:只背公开样例 → 公开全绿、held-out 必死。"""
    m = matrix["negative_hardcode"]
    assert m["cap"] == {"test_held_example_1"}, f"落点错:{m['cap']}"
    assert m["reg_rc"] == 0, f"接口契约不该红:{m['reg']}"


def test_nc_badexit_dies_exactly_on_malformed_contract(matrix):
    m = matrix["negative_badexit"]
    assert m["cap"] == {"test_malformed_input_is_user_error"}, f"落点错:{m['cap']}"
    assert m["reg_rc"] == 0, f"骨架半不该红:{m['reg']}"


def test_nc_reimpl_green_on_oracle_but_caught_by_provenance(assembled, matrix):
    """oracle 全绿是设计使然 —— 判死在 provenance 层,喂它证明那层有牙。"""
    root, info = assembled
    m = matrix["negative_reimpl"]
    assert (m["cap_rc"], m["reg_rc"]) == (0, 0), "NC_reimpl 本该在 oracle 全绿"
    ctrl = root / "controls" / info["task_id"] / "negative_reimpl"
    got = check_upstream_provenance(ctrl, ["impl.py"], "pdfplumber")
    assert got["ok"] is False and "UPSTREAM_CAPABILITY_REIMPLEMENTED" in got["reason"]


def test_provenance_accepts_real_import(tmp_path):
    """正例对照:真 import 上游的实现不得被 provenance 误杀。"""
    (tmp_path / "impl.py").write_text(
        "import pdfplumber\n\ndef extract(p):\n    return pdfplumber.open(p)\n",
        encoding="utf-8")
    assert check_upstream_provenance(tmp_path, ["impl.py"], "pdfplumber")["ok"] is True


def test_skeleton_initial_state_is_honest_internal_error(assembled, tmp_path):
    """骨架初始态(NotImplementedError)必须是 exit 2,不是假成功。"""
    root, info = assembled
    shim = _session(root, info, tmp_path, None)
    r = subprocess.run([sys.executable, str(shim),
                        str(root / "oracle" / info["task_id"] / "fixtures" / "inputs" / "a.pdf")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "internal error" in r.stderr
