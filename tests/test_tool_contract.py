"""LOCAL-TOOL 谱系 · M1 第 1–2 步的钉死(TOOL_CONTRACT_SCHEMA §三/§四)。

- ToolSpec 是 TaskContract 的**可选**分节:旧契约零破坏(实载一份冻结
  契约验证 tool is None,sha256 原样通过);
- Example 双源二选一的校验必须真的拒绝混用;
- CLI 编译器产出的是**检查代码**,按"检查器先自证"纪律喂合成正反例:
  假工具输出对 → 编译出的测试全绿;输出错/退出码错 → 必须红。
  不自证判别力的编译器,产出的验收就是墙纸。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from repoproof.adoption.assembly.example_compiler import (
    CompileError,
    Example,
    compile_pytest,
)
from repoproof.domain.models import TaskContract, ToolInterface, ToolInterfaceIO, ToolSpec

REPO = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------ ToolSpec 模型

def test_toolspec_parses_from_contract_yaml_shape():
    c = TaskContract.model_validate({
        "task_id": "tool-x-v1",
        "source_repo": {"url": "https://github.com/a/b", "revision": "guided",
                        "resolved_commit": "deadbeef", "license": "MIT",
                        "distribution": "b", "import_module": "b"},
        "target_project": {"kind": "local_tool", "path": "fixtures/tool_skeleton_x",
                           "package": "x_tool", "entry_point": "x"},
        "task_family": "LOCAL-TOOL",
        "adoption_shape": "TOOL_ONBOARDING",
        "tool": {"name": "x", "summary": "s",
                 "interface": {"usage": "x <in>",
                               "input": {"kind": "file", "format": "PDF"},
                               "output": {"kind": "stdout", "format": "markdown-table"},
                               "exit_codes": {"0": "success", "1": "user_error",
                                              "2": "internal_error"}}},
        "capability": {"statement": "s", "output_schema": "O"},
        "environment": {}, "constraints": {}, "budgets": {},
        "acceptance": {"capability_command": ["pytest"], "regression_command": ["pytest"]},
    })
    assert c.tool is not None and c.tool.name == "x"
    assert c.tool.interface.exit_codes["1"] == "user_error"
    assert c.task_family == "LOCAL-TOOL"


def test_frozen_legacy_contract_loads_with_tool_none():
    """旧谱系冻结契约:加字段后 sha256 sidecar 原样通过,tool is None。"""
    path = REPO / "contracts" / "adopt-thefuzz-guided-v1.yaml"
    c, _digest = TaskContract.load_frozen(path, require_sidecar=True)
    assert c.tool is None
    assert c.task_family == ""          # 旧契约未归族,语义不被新字段改写


def test_toolspec_roundtrip_dump():
    spec = ToolSpec(name="t", summary="s", interface=ToolInterface(
        usage="t <in>", input=ToolInterfaceIO(kind="file", format="PDF"),
        output=ToolInterfaceIO(kind="stdout", format="md"),
        exit_codes={"0": "success", "1": "user_error", "2": "internal_error"}))
    again = ToolSpec.model_validate(spec.model_dump())
    assert again == spec


# ------------------------------------------------------------ Example 双源

def test_example_rejects_zero_and_double_input_sources():
    with pytest.raises(ValidationError):
        Example(expected="x")                                   # 无输入源
    with pytest.raises(ValidationError):
        Example(input="a", input_file="f", expected="x")        # 双输入源
    with pytest.raises(ValidationError):
        Example(input="a")                                      # 无期望源
    with pytest.raises(ValidationError):
        Example(input="a", expected="x", expected_file="f")     # 双期望源


def test_example_legacy_string_shape_still_works():
    e = Example(input="周合", expected="contains:周会纪要")
    assert e.input_file is None and e.expected_file is None


def test_seam_mode_refuses_file_examples():
    with pytest.raises(CompileError):
        compile_pytest([Example(input_file="f.pdf", expected="x")], header="h")


def test_seam_mode_output_unchanged_for_legacy_examples():
    """seam 编译对旧样例逐字节稳定 —— 旧谱系装配的回归锚。"""
    out = compile_pytest([Example(input="a", expected="contains:b")], header="H")
    assert "from user_capability import run" in out
    assert "def test_example_1():" in out
    assert "assert 'b' in out" in out


# ------------------------------------------------- CLI 编译:喂合成正反例

_GOOD_TOOL = """#!/usr/bin/env python3
import sys
args = sys.argv[1:]
if args == ["--help"]:
    print("usage: faketool <input>"); sys.exit(0)
print("| A | B |")
print("|---|---|")
print("| 1 | 2 |")
"""

_BAD_TOOL = """#!/usr/bin/env python3
print("totally wrong output")
"""

_EXAMPLES = [
    Example(input_file="inputs/t.pdf", expected="contains:| A | B |"),
    Example(input_file="inputs/t.pdf", expected_file="expected/t.md"),
    Example(input="--help", expected="contains:usage: faketool"),
]


def _materialize(tmp: Path, tool_src: str) -> tuple[Path, Path]:
    tool = tmp / "faketool.py"
    tool.write_text(tool_src, encoding="utf-8")
    tool.chmod(0o755)
    tdir = tmp / "tests"
    (tdir / "fixtures" / "inputs").mkdir(parents=True)
    (tdir / "fixtures" / "expected").mkdir(parents=True)
    (tdir / "fixtures" / "inputs" / "t.pdf").write_bytes(b"%PDF-fake")
    (tdir / "fixtures" / "expected" / "t.md").write_text(
        "| A | B |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    (tdir / "test_cli_compiled.py").write_text(
        compile_pytest(_EXAMPLES, header="CLI 编译自证", mode="cli"), encoding="utf-8")
    return tool, tdir


def _run_compiled(tool: Path, tdir: Path) -> int:
    env = dict(os.environ, REPOPROOF_TOOL_BIN=str(tool))
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(tdir / "test_cli_compiled.py")],
        capture_output=True, text=True, env=env, timeout=180).returncode


def test_cli_compiled_tests_pass_against_correct_tool(tmp_path: Path):
    tool, tdir = _materialize(tmp_path, _GOOD_TOOL)
    assert _run_compiled(tool, tdir) == 0


def test_cli_compiled_tests_fail_against_wrong_output(tmp_path: Path):
    """反例一:输出内容错 → 编译出的验收必须红(否则是墙纸)。"""
    tool, tdir = _materialize(tmp_path, _BAD_TOOL)
    assert _run_compiled(tool, tdir) != 0


def test_cli_compiled_tests_fail_against_nonzero_exit(tmp_path: Path):
    """反例二:内容对但退出码非零 → 必须红(exit code 是接口契约)。"""
    crashing = _GOOD_TOOL.replace("print(\"| 1 | 2 |\")",
                                  "print(\"| 1 | 2 |\"); sys.exit(2)")
    tool, tdir = _materialize(tmp_path, crashing)
    assert _run_compiled(tool, tdir) != 0


def test_cli_mode_normalizes_line_endings_for_expected_file(tmp_path: Path):
    """expected_file 走规范化行尾比对:尾随空白/末行换行差异不误杀。"""
    trailing = _GOOD_TOOL.replace("print(\"| 1 | 2 |\")", "print(\"| 1 | 2 |  \")")
    tool, tdir = _materialize(tmp_path, trailing)
    assert _run_compiled(tool, tdir) == 0
