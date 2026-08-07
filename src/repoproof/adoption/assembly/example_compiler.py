"""样例编译器(RFC-007)— 用户样例 → 公开/held-out pytest,全确定性。"""

from __future__ import annotations

from pydantic import BaseModel

CONTAINS = "contains:"


class Example(BaseModel):
    input: str
    expected: str  # "contains:X" 表示包含断言,否则相等断言


class CompileError(ValueError):
    pass


def split_examples(examples: list[Example]) -> tuple[list[Example], list[Example]]:
    """≥3 组;每 4 组留 1 组 held-out(至少 1 组),取尾部。"""
    if len(examples) < 3:
        raise CompileError("至少需要 3 组样例(其中 1 组将作为隐藏验证)")
    n_held = max(1, len(examples) // 4)
    return examples[:-n_held], examples[-n_held:]


def _assert_line(e: Example, idx: int) -> str:
    if e.expected.startswith(CONTAINS):
        want = e.expected[len(CONTAINS):]
        return (f"def test_example_{idx}():\n"
                f"    out = str(run({e.input!r}))\n"
                f"    assert {want!r} in out, f\"期望包含 {want!r},实际: {{out[:200]}}\"\n")
    return (f"def test_example_{idx}():\n"
            f"    out = str(run({e.input!r}))\n"
            f"    assert out == {e.expected!r}, f\"期望 {e.expected!r},实际: {{out[:200]}}\"\n")


def compile_pytest(examples: list[Example], *, header: str) -> str:
    body = "\n\n".join(_assert_line(e, i + 1) for i, e in enumerate(examples))
    return (f'"""{header}(由用户样例确定性编译;验收强度=用户样例级)"""\n'
            "from user_capability import run\n\n\n" + body + "\n")
