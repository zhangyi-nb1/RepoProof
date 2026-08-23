"""公开合同测试 — agent 可运行自测(由用户样例确定性编译;验收强度=用户样例级)"""
import os
import shlex
import subprocess
from pathlib import Path

_TOOL = os.environ["REPOPROOF_TOOL_BIN"]
_FIX = Path(__file__).resolve().parent / "fixtures"


def _run(args):
    return subprocess.run([_TOOL, *args], capture_output=True, text=True, timeout=120)


def _norm(s):
    return "\n".join(line.rstrip() for line in s.strip().splitlines())


def test_example_1():
    r = _run([str(_FIX / 'inputs/note.xml')])
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    want = _norm((_FIX / 'expected/note.json').read_text(encoding="utf-8"))
    assert _norm(r.stdout) == want, f"输出与期望文件 expected/note.json 不符(规范化行尾后);实际前 200 字: {r.stdout[:200]}"


def test_example_2():
    r = _run([str(_FIX / 'inputs/attrs.xml')])
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    want = _norm((_FIX / 'expected/attrs.json').read_text(encoding="utf-8"))
    assert _norm(r.stdout) == want, f"输出与期望文件 expected/attrs.json 不符(规范化行尾后);实际前 200 字: {r.stdout[:200]}"

