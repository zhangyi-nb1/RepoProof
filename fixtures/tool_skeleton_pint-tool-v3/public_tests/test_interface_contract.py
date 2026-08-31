"""接口契约·骨架半(HOST_INPUT_GUARD;从 ToolSpec 确定性生成)。

exit 语义:0=成功;1=用户错误;2=内部错误。本文件两项在 S0 骨架态即恒绿
—— 它是"回归"面:agent 把它搞红 = 破坏了骨架既有行为。
"""
import os
import subprocess
from pathlib import Path

_TOOL = os.environ["REPOPROOF_TOOL_BIN"]
_FIX = Path(__file__).resolve().parent / "fixtures"


def _run(args):
    return subprocess.run([_TOOL, *args], capture_output=True, text=True, timeout=120)


def test_help_reachable():
    r = _run(["--help"])
    assert r.returncode == 0, f"--help 必须 exit 0,实际 {r.returncode}"
    assert "usage" in r.stdout.lower(), f"--help 须含 usage 行: {r.stdout[:120]}"


def test_missing_input_is_user_error():
    r = _run([str(_FIX / "no_such_file.tsv")])
    assert r.returncode == 1, f"输入不存在必须 exit 1,实际 {r.returncode}"
    assert r.stderr.strip(), "用户错误必须在 stderr 说明原因"
    assert not r.stdout.strip(), "错误路径不得向 stdout 输出半成品"
