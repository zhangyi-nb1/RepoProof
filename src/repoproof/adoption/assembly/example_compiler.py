"""样例编译器(RFC-007;LOCAL-TOOL 扩展见 TOOL_CONTRACT_SCHEMA §四)
— 用户样例 → 公开/held-out pytest,全确定性。

两种编译目标:
  mode="seam"  现行:import user_capability 调 run(value)(旧谱系,零变化);
  mode="cli"   LOCAL-TOOL:subprocess 跑工具 CLI,断言 exit 0 + 输出匹配。
               工具入口经 REPOPROOF_TOOL_BIN 环境变量注入(runner 负责),
               fixture 相对测试文件自身的 fixtures/ 解析 —— 公开区与
               oracle 区各放各的 fixtures,模板统一。
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

CONTAINS = "contains:"


class Example(BaseModel):
    """一组样例。输入源与期望源各自二选一:

      input        字符串:seam 模式 = run() 实参;cli 模式 = argv(shlex 切分)
      input_file   fixture 相对路径(仅 cli 模式;文件本体由装配器落位)
      expected     "contains:X" 包含断言,否则相等断言(strip 后)
      expected_file 期望全文文件,精确比对(规范化行尾;仅 cli 模式)
    """

    input: str | None = None
    input_file: str | None = None
    expected: str | None = None
    expected_file: str | None = None

    @model_validator(mode="after")
    def _exactly_one_each(self) -> "Example":
        if (self.input is None) == (self.input_file is None):
            raise ValueError("input 与 input_file 必须恰好给一个")
        if (self.expected is None) == (self.expected_file is None):
            raise ValueError("expected 与 expected_file 必须恰好给一个")
        return self


class CompileError(ValueError):
    pass


def split_examples(examples: list[Example]) -> tuple[list[Example], list[Example]]:
    """≥3 组;每 4 组留 1 组 held-out(至少 1 组),取尾部。"""
    if len(examples) < 3:
        raise CompileError("至少需要 3 组样例(其中 1 组将作为隐藏验证)")
    n_held = max(1, len(examples) // 4)
    return examples[:-n_held], examples[-n_held:]


# ---------------------------------------------------------------- seam 模式

def _assert_line(e: Example, idx: int) -> str:
    if e.input is None or e.expected is None:
        raise CompileError(
            f"样例 {idx}:seam 模式只支持字符串 input/expected(文件样例属 cli 模式)")
    if e.expected.startswith(CONTAINS):
        want = e.expected[len(CONTAINS):]
        return (f"def test_example_{idx}():\n"
                f"    out = str(run({e.input!r}))\n"
                f"    assert {want!r} in out, f\"期望包含 {want!r},实际: {{out[:200]}}\"\n")
    return (f"def test_example_{idx}():\n"
            f"    out = str(run({e.input!r}))\n"
            f"    assert out == {e.expected!r}, f\"期望 {e.expected!r},实际: {{out[:200]}}\"\n")


# ----------------------------------------------------------------- cli 模式

_CLI_PRELUDE = '''import os
import shlex
import subprocess
from pathlib import Path

_TOOL = os.environ["REPOPROOF_TOOL_BIN"]
_FIX = Path(__file__).resolve().parent / "fixtures"


def _run(args):
    return subprocess.run([_TOOL, *args], capture_output=True, text=True, timeout=120)


def _norm(s):
    return "\\n".join(line.rstrip() for line in s.strip().splitlines())
'''


def _cli_argv_expr(e: Example, idx: int) -> str:
    if e.input_file is not None:
        return f"[str(_FIX / {e.input_file!r})]"
    return f"shlex.split({e.input!r})"


def _cli_test(e: Example, idx: int) -> str:
    argv = _cli_argv_expr(e, idx)
    head = (f"def test_example_{idx}():\n"
            f"    r = _run({argv})\n"
            f"    assert r.returncode == 0, "
            f"f\"exit={{r.returncode}} stderr: {{r.stderr[:300]}}\"\n")
    if e.expected_file is not None:
        return head + (
            f"    want = _norm((_FIX / {e.expected_file!r}).read_text(encoding=\"utf-8\"))\n"
            f"    assert _norm(r.stdout) == want, "
            f"f\"输出与期望文件 {e.expected_file} 不符(规范化行尾后);"
            f"实际前 200 字: {{r.stdout[:200]}}\"\n")
    if e.expected.startswith(CONTAINS):
        want = e.expected[len(CONTAINS):]
        # 消息用**运行时** f-string 求值(want 先落局部变量):把 repr 裸插进
        # 生成代码的引号串,断言值含双引号即碎(M4 pyyaml 实测:
        # contains:"greeting": "你好" 让整文件 SyntaxError)。
        return head + (
            f"    want = {want!r}\n"
            "    assert want in r.stdout, "
            "f\"期望 stdout 包含 {want!r},实际: {r.stdout[:200]}\"\n")
    return head + (
        f"    want = {e.expected!r}\n"
        "    assert r.stdout.strip() == want, "
        "f\"期望 {want!r},实际: {r.stdout[:200]}\"\n")


# ------------------------------------------------------------------- 编译口

def compile_pytest(examples: list[Example], *, header: str, mode: str = "seam") -> str:
    doc = f'"""{header}(由用户样例确定性编译;验收强度=用户样例级)"""\n'
    if mode == "seam":
        body = "\n\n".join(_assert_line(e, i + 1) for i, e in enumerate(examples))
        return doc + "from user_capability import run\n\n\n" + body + "\n"
    if mode == "cli":
        body = "\n\n".join(_cli_test(e, i + 1) for i, e in enumerate(examples))
        return doc + _CLI_PRELUDE + "\n\n" + body + "\n"
    raise CompileError(f"未知编译模式:{mode!r}(支持 seam / cli)")
