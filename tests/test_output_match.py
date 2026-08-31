"""输出判据(harness 判据面)的钉死 —— 放宽只沿合同语义,一步都不多。

LESSONS #57:同一事实两处判定、两把尺子,把一个通过了全部能力测试的
工具判死并自动撤回。这里钉三件事:①噪声要容;②语义差异必须红;
③两处判定必须是**同一份实现**(不是"照着写的两份")。
"""

from __future__ import annotations

import pytest

from repoproof.verification.output_match import canonical_source, compare_output

# ---------------------------------------------- ① 呈现噪声:容(人不精确)

@pytest.mark.parametrize(("actual", "expected", "root"), [
    ('{"a":1}\n', '{"a":1}', "object"),            # 尾换行:用户粘贴时最常见
    ('{"a":1}', '{"b":2,"a":1}'.replace('"b":2,', ""), "object"),
    ('{"a":1,"b":2}', '{"b":2,"a":1}', "object"),  # 键序:序列化噪声
    ('{ "a" : 1 }', '{"a":1}', "object"),          # 缩进/空格
    ("navy\n", "navy", "text"),
    ("navy  \r\n", "navy", "text"),                # CRLF + 行尾空白
])
def test_presentation_noise_is_tolerated(actual, expected, root):
    ok, _mode = compare_output(actual, expected, root_type=root)
    assert ok, (actual, expected, root)


# ---------------------------------------------- ② 语义差异:必须红(门槛不降)

@pytest.mark.parametrize(("actual", "expected", "root", "why"), [
    ('{"a":1}', '{"a":2}', "object", "值不同"),
    ('{"a":1}', '{"a":1,"b":2}', "object", "少字段"),
    ('{"a":1,"b":2}', '{"a":1}', "object", "多字段"),
    ('{"a":1}', '{"a":1.0}', "object", "int 与 float 不是同一个值"),
    ('{"a":1}', '{"a":"1"}', "object", "数字与字符串"),
    ("Navy", "navy", "text", "大小写敏感"),
    ("navy blue", "navyblue", "text", "串内空白不许抹"),
    ("not json at all", '{"a":1}', "object", "合同要 JSON 而输出不是 → 合同违约"),
    ('{"a":1}', "not json at all", "object", "人写的期望不满足合同"),
])
def test_semantic_difference_always_fails(actual, expected, root, why):
    ok, _mode = compare_output(actual, expected, root_type=root)
    assert not ok, f"{why} 竟被判为相符:{actual!r} vs {expected!r}"


def test_json_contract_grants_no_text_level_leniency():
    """**负控**:合同声明 JSON 时,不许拿文本口径去"救"解析不出的输出。

    `"hello\n"` vs `"hello"` 在文本口径下相符(尾换行是噪声),但在 JSON
    合同下两边都解析不出 —— 判不符。宽容度是**跟着合同走**的,不是一个
    全局的"差不多就行"。

    分工说明:本模块只回答"实际是否等于期望";"输出是否满足合同形状"
    是另一道闸(输出合同校验)。两串完全一致时 exact 短路,合同违约由
    那道闸抓 —— 一件事只由一处判。
    """
    assert compare_output("hello\n", "hello", root_type="text")[0] is True
    ok, mode = compare_output("hello\n", "hello", root_type="object")
    assert mode == "json" and not ok


# ---------------------------------------------- ③ 一物一名:不许再长出第二把尺子

def test_generated_tests_inline_the_same_judge_source():
    """生成的验收测试内联的必须是**同一份实现**,不是照着写的第二份。

    会话 venv 装不了 repoproof,所以判据只能内联进生成的测试。若哪天有人
    "照着再写一份",两把尺子会各自演化 —— LESSONS #57 的病根就是这个。
    这里逐字比对内联源码与本体源码。
    """
    from repoproof.adoption.assembly.example_compiler import Example, compile_pytest
    from repoproof.domain.models import ToolOutputContract

    generated = compile_pytest(
        [Example(input_file=f"{c}.txt", expected_file=f"{c}.expected.txt")
         for c in "abc"],
        header="demo", mode="cli",
        output_contract=ToolOutputContract(media_type="application/json",
                                           root_type="object"))
    judge = canonical_source()
    for fragment in judge.split("\n\n"):
        if fragment.strip():
            assert fragment.strip() in generated, "生成的测试与判据本体已分家"
    assert "_ROOT_TYPE = 'object'" in generated       # 判据跟着合同的声明走


def test_audit_and_contract_tests_share_one_implementation():
    """抽查与合同验收测试必须调用同一个 compare_output(不是各自的 _norm)。"""
    import inspect

    from repoproof.runner import tool_release

    src = inspect.getsource(tool_release)
    assert "from repoproof.verification.output_match import compare_output" in src
    assert "def _norm_output" not in src, "旧的本地实现应已退役,免得两把尺子复活"
