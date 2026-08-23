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
    r = _run(shlex.split('--help'))
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    assert 'usage' in r.stdout, f"期望 stdout 包含 'usage',实际: {r.stdout[:200]}"


def test_example_2():
    r = _run([str(_FIX / 'inputs/warn-report.pdf')])
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    assert '| Notice Date | Effective | Received | Company | City | No. Of | Layoff/Closure |' in r.stdout, f"期望 stdout 包含 '| Notice Date | Effective | Received | Company | City | No. Of | Layoff/Closure |',实际: {r.stdout[:200]}"


def test_example_3():
    r = _run([str(_FIX / 'inputs/table-curves.pdf')])
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    want = _norm((_FIX / 'expected/table-curves.md').read_text(encoding="utf-8"))
    assert _norm(r.stdout) == want, f"输出与期望文件 expected/table-curves.md 不符(规范化行尾后);实际前 200 字: {r.stdout[:200]}"

