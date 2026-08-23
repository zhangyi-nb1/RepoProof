"""验收(公开样例)(由用户样例确定性编译;验收强度=用户样例级)"""
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
    want = 'usage'
    assert want in r.stdout, f"期望 stdout 包含 {want!r},实际: {r.stdout[:200]}"


def test_example_2():
    r = _run([str(_FIX / 'utf8_cn.txt')])
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    want = _norm((_FIX / 'utf8_cn.expected.json').read_text(encoding="utf-8"))
    assert _norm(r.stdout) == want, f"输出与期望文件 utf8_cn.expected.json 不符(规范化行尾后);实际前 200 字: {r.stdout[:200]}"


def test_example_3():
    r = _run([str(_FIX / 'gbk_cn.txt')])
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    want = '"encoding":"GB2312"'
    assert want in r.stdout, f"期望 stdout 包含 {want!r},实际: {r.stdout[:200]}"



def test_held_example_1():
    r = _run([str(_FIX / 'ascii.txt')])
    assert r.returncode == 0, f"exit={r.returncode} stderr: {r.stderr[:300]}"
    want = '"encoding":"ascii"'
    assert want in r.stdout, f"期望 stdout 包含 {want!r},实际: {r.stdout[:200]}"



# ---- 接口契约·实现半(ADAPTER;依赖能力实现,S0 红属预期)----

def test_deterministic_output():
    a = _run([str(_FIX / 'utf8_cn.txt')])
    b = _run([str(_FIX / 'utf8_cn.txt')])
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout == b.stdout, "同一输入两次运行输出必须逐字节一致"


def test_stdout_purity_on_success():
    r = _run([str(_FIX / 'utf8_cn.txt')])
    assert r.returncode == 0
    assert r.stdout.strip(), "成功路径 stdout 必须有产出"
    assert "Traceback" not in r.stderr, "成功路径不得泄漏 traceback 到 stderr"
