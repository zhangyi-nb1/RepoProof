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
from repoproof.adoption.assembly.output_contract import validate_output_text
from repoproof.domain.models import (
    TaskContract,
    ToolInterface,
    ToolInterfaceIO,
    ToolOutputContract,
    ToolSpec,
)

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


def test_output_contract_is_additive_and_normalizes_json_root_aliases():
    """v1 stays loadable; v2 carries the executable contract as additive data."""
    legacy = ToolInterfaceIO(kind="stdout", format="JSON")
    assert legacy.contract is None

    contract = ToolOutputContract(
        media_type="application/json",
        root_type="json_object",
        required={"language": "string", "token_count": "integer"},
    )
    assert contract.root_type == "object"
    assert validate_output_text('{"language":"zh","token_count":2}', contract) == []
    assert validate_output_text('["zh",2]', contract)
    assert validate_output_text('{"token_count":2}', contract)
    assert validate_output_text('{"language":"zh","token_count":true}', contract)
    with pytest.raises(ValidationError):
        ToolOutputContract(media_type="text/plain", root_type="object")
    with pytest.raises(ValidationError, match="properties"):
        ToolOutputContract.model_validate({
            "media_type": "application/json",
            "root_type": "object",
            "required": {"language": "string"},
            "properties": {"language": {"minLength": 1}},
        })


@pytest.mark.parametrize(
    ("media_type", "good", "bad", "bad_reason"),
    [
        (
            "application/x-research-info-systems",
            "TY  - JOUR\nTI  - Unicode 标题\nER  - \n",
            '{"title":"not RIS"}',
            "ris:",
        ),
        (
            "text/tab-separated-values",
            "sample\tvalue\tunit\nA\t1.5\tmm\n",
            "sample\tvalue\nA\t1\tmm\n",
            "tsv: inconsistent_columns",
        ),
        (
            "text/markdown",
            "# Network summary\n\n| node | degree |\n| --- | ---: |\n| A | 2 |\n",
            '{"nodes":["A"]}',
            "markdown: json_document",
        ),
        (
            "text/html",
            "<html><head><title>QC</title></head><body><h1>FASTQ</h1></body></html>",
            '<html><body><script src="https://example.test/x.js" /></body></html>',
            "html: element_forbidden=script",
        ),
    ],
)
def test_text_output_contract_validates_declared_artifact_structure(
    media_type: str,
    good: str,
    bad: str,
    bad_reason: str,
) -> None:
    contract = ToolOutputContract(media_type=media_type, root_type="text", required={})
    assert validate_output_text(good, contract) == []
    assert any(bad_reason in error for error in validate_output_text(bad, contract))


def test_ris_contract_accepts_pinned_rispy_default_record_headers() -> None:
    """RISpy 0.10.0's default writer emits a deterministic ordinal per record."""

    output = (
        "1.\nTY  - JOUR\nTI  - First\nER  - \n"
        "2.\nTY  - BOOK\nTI  - 第二条\nER  - \n"
    )
    contract = ToolOutputContract(
        media_type="application/x-research-info-systems",
        root_type="text",
        required={},
    )
    assert validate_output_text(output, contract) == []


@pytest.mark.parametrize(
    "output",
    [
        "2.\nTY  - JOUR\nER  - \n",
        "1.\n2.\nTY  - JOUR\nER  - \n",
        "1.\n",
        "TY  - JOUR\n1.\nER  - \n",
    ],
)
def test_ris_contract_rejects_misplaced_or_nonsequential_record_headers(
    output: str,
) -> None:
    contract = ToolOutputContract(
        media_type="application/x-research-info-systems",
        root_type="text",
        required={},
    )
    assert validate_output_text(output, contract)


@pytest.mark.parametrize(
    "body",
    [
        '<html><body><object data="https://example.test/x" /></body></html>',
        '<html><body><img srcset="https://example.test/x 1x" /></body></html>',
        '<html><body><video poster="https://example.test/x" /></body></html>',
        '<html><body><form action="https://example.test/x" /></body></html>',
        '<html><head><meta http-equiv="refresh" content="0;url=https://example.test" />'
        "</head><body /></html>",
        '<html><head><style>@import "https://example.test/x";</style></head>'
        "<body /></html>",
        '<html><body><svg><script>bad()</script></svg></body></html>',
        '<html><head><style>body{background-image:u\\72 l(https://example.test/x)}'
        "</style></head><body /></html>",
        '<html><body><a href="#x" ping="https://example.test/x">x</a></body></html>',
        '<?xml version="1.0"?><?xml-stylesheet href="https://example.test/x"?>'
        "<html><body /></html>",
        '<!DOCTYPE html><html><body /></html>',
    ],
)
def test_html_contract_rejects_active_or_external_resources(body: str) -> None:
    contract = ToolOutputContract(media_type="text/html", root_type="text", required={})
    assert validate_output_text(body, contract)


@pytest.mark.parametrize("media_type", ["text/html", "application/xhtml+xml"])
@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (
            '<html><body><a href="#local" ping="https://tracker.invalid/p">x</a></body></html>',
            "resource_attribute_forbidden=ping",
        ),
        (
            '<?xml version="1.0"?><?xml-stylesheet href="https://tracker.invalid/x.css"?>'
            "<html><body /></html>",
            "processing_instruction_forbidden",
        ),
        (
            r'<html><body><p style="background:\75rl(https://tracker.invalid/x)">x</p>'
            "</body></html>",
            "style_attribute_forbidden",
        ),
    ],
)
def test_html_and_xhtml_contract_reject_external_reference_bypasses(
    media_type: str,
    body: str,
    reason: str,
) -> None:
    contract = ToolOutputContract(media_type=media_type, root_type="text", required={})
    assert any(reason in error for error in validate_output_text(body, contract))


@pytest.mark.parametrize(
    "name", ["../escape", "nested/tool", ".", "-leading", "trailing-"]
)
def test_tool_name_must_be_a_contained_lowercase_cli_slug(name: str):
    with pytest.raises(ValidationError, match="name"):
        ToolSpec(
            name=name,
            summary="invalid path-like command",
            interface=ToolInterface(
                usage=f"{name} <input>",
                input=ToolInterfaceIO(kind="file", format="TXT"),
                output=ToolInterfaceIO(kind="stdout", format="TXT"),
                exit_codes={"0": "success", "1": "user", "2": "internal"},
            ),
        )


@pytest.mark.parametrize(
    "constant", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"]
)
@pytest.mark.parametrize(("root_type", "body", "location"), [
    ("object", '{{"score":{constant}}}', "document: invalid_json"),
    ("json", "{constant}", "document: invalid_json"),
    ("json_lines", '{{"score":{constant}}}\n', "line=1: invalid_json"),
])
def test_output_contract_rejects_nonstandard_json_constants(
        constant: str, root_type: str, body: str, location: str):
    required = {"score": "number"} if root_type != "json" else {}
    contract = ToolOutputContract(
        media_type=("application/x-ndjson"
                    if root_type == "json_lines" else "application/json"),
        root_type=root_type,
        required=required,
    )

    assert validate_output_text(body.format(constant=constant), contract) == [location]


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


def test_upstream_confirmed_example_requires_a_binding_hash() -> None:
    with pytest.raises(ValidationError, match="输入/输出绑定"):
        Example(
            input_file="inputs/a.txt",
            expected_file="expected/a.txt",
            truth_provenance="UPSTREAM_DERIVED_USER_CONFIRMED",
        )
    accepted = Example(
        input_file="inputs/a.txt",
        expected_file="expected/a.txt",
        truth_provenance="UPSTREAM_DERIVED_USER_CONFIRMED",
        truth_binding_sha256="a" * 64,
    )
    assert accepted.truth_binding_sha256 == "a" * 64


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
print('"quoted": "值"')
"""

_BAD_TOOL = """#!/usr/bin/env python3
print("totally wrong output")
"""

_EXAMPLES = [
    Example(input_file="inputs/t.pdf", expected="contains:| A | B |"),
    Example(input_file="inputs/t.pdf", expected_file="expected/t.md"),
    Example(input="--help", expected="contains:usage: faketool"),
    # M4 pyyaml 实测:断言值含双引号曾让编译产物 SyntaxError —— 钉死转义
    Example(input_file="inputs/t.pdf", expected='contains:| A | B |'.replace(
        "| A | B |", '"A": "B"') if False else 'contains:"quoted": "值"'),
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
        '| A | B |\n|---|---|\n| 1 | 2 |\n"quoted": "值"\n', encoding="utf-8")
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


_JSON_CONTRACT = ToolOutputContract(
    media_type="application/json",
    root_type="object",
    required={"language": "string", "token_count": "integer"},
)


def _materialize_json(
    tmp: Path,
    stdout: str,
    expected: str,
    *,
    contract: ToolOutputContract = _JSON_CONTRACT,
) -> tuple[Path, Path]:
    tool_src = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"sys.stdout.write({stdout!r})\n"
    )
    tool = tmp / "json-tool.py"
    tool.write_text(tool_src, encoding="utf-8")
    tool.chmod(0o755)
    tdir = tmp / "tests"
    (tdir / "fixtures").mkdir(parents=True)
    (tdir / "fixtures" / "in.txt").write_text("x", encoding="utf-8")
    (tdir / "fixtures" / "expected.json").write_text(expected, encoding="utf-8")
    source = compile_pytest(
        [Example(input_file="in.txt", expected_file="expected.json")],
        header="JSON output contract",
        mode="cli",
        output_contract=contract,
    )
    assert "[tool-output-contract]" in source
    (tdir / "test_cli_compiled.py").write_text(source, encoding="utf-8")
    return tool, tdir


def test_cli_json_contract_positive_control_passes(tmp_path: Path):
    value = '{"language":"zh","token_count":2}'
    tool, tdir = _materialize_json(tmp_path, value, value)
    assert _run_compiled(tool, tdir) == 0


@pytest.mark.parametrize("bad", [
    "helo\\nwrld\\n",                       # NC_json_plaintext
    '["helo"]',                              # NC_json_wrong_root
    '{"token_count":2}',                     # NC_json_missing_field
])
def test_cli_json_contract_rejects_matching_but_invalid_stdout(
        tmp_path: Path, bad: str):
    """Actual stdout is parsed independently even when the bad golden matches it."""
    tool, tdir = _materialize_json(tmp_path, bad, bad)
    assert _run_compiled(tool, tdir) != 0


@pytest.mark.parametrize(
    "constant", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"]
)
@pytest.mark.parametrize(("root_type", "body"), [
    ("object", '{{"score":{constant}}}'),
    ("json", "{constant}"),
    ("json_lines", '{{"score":{constant}}}\n'),
])
def test_generated_cli_validator_rejects_nonstandard_json_constants(
        tmp_path: Path, constant: str, root_type: str, body: str):
    required = {"score": "number"} if root_type != "json" else {}
    contract = ToolOutputContract(
        media_type=("application/x-ndjson"
                    if root_type == "json_lines" else "application/json"),
        root_type=root_type,
        required=required,
    )
    bad = body.format(constant=constant)

    tool, tdir = _materialize_json(tmp_path, bad, bad, contract=contract)
    assert _run_compiled(tool, tdir) != 0


@pytest.mark.parametrize(
    ("media_type", "good", "bad"),
    [
        (
            "application/x-research-info-systems",
            "1.\nTY  - JOUR\nTI  - A title\nER  - \n",
            '{"title":"not RIS"}',
        ),
        (
            "text/tab-separated-values",
            "sample\tvalue\nA\t1\n",
            "sample\tvalue\nA\t1\textra\n",
        ),
        ("text/markdown", "# Summary\n", '{"summary":"wrong artifact"}'),
        (
            "text/html",
            "<html><body><p>QC</p></body></html>",
            '<html><body><img src="https://example.test/chart.png" /></body></html>',
        ),
    ],
)
def test_generated_cli_validator_enforces_non_json_text_media_types(
    tmp_path: Path,
    media_type: str,
    good: str,
    bad: str,
) -> None:
    contract = ToolOutputContract(media_type=media_type, root_type="text", required={})
    (tmp_path / "good").mkdir()
    good_tool, good_tests = _materialize_json(
        tmp_path / "good",
        good,
        good,
        contract=contract,
    )
    assert _run_compiled(good_tool, good_tests) == 0

    (tmp_path / "bad").mkdir()
    bad_tool, bad_tests = _materialize_json(
        tmp_path / "bad",
        bad,
        bad,
        contract=contract,
    )
    assert _run_compiled(bad_tool, bad_tests) != 0


@pytest.mark.parametrize("media_type", ["text/html", "application/xhtml+xml"])
@pytest.mark.parametrize(
    "body",
    [
        '<html><body><a href="#local" ping="https://tracker.invalid/p">x</a></body></html>',
        '<?xml version="1.0"?><?xml-stylesheet href="https://tracker.invalid/x.css"?>'
        "<html><body /></html>",
        r'<html><body><p style="background:\75rl(https://tracker.invalid/x)">x</p>'
        "</body></html>",
    ],
)
def test_generated_runtime_rejects_html_external_reference_bypasses(
    tmp_path: Path,
    media_type: str,
    body: str,
) -> None:
    """Generated packages enforce the same self-contained HTML floor as Core."""

    contract = ToolOutputContract(media_type=media_type, root_type="text", required={})
    tool, tests = _materialize_json(tmp_path, body, body, contract=contract)
    assert _run_compiled(tool, tests) != 0
