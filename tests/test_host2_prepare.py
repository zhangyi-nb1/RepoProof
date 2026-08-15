"""H2 宿主副本部署层的钉死 —— 挖空 + 剥离 + **捞不出答案**。

这道题的诚实尺寸只有约 1–2 bit。**答案只要还能从副本里捞出来,信息量当场
归零,而所有数字看起来照常。** 所以部署层不是"记得删 .git",是"删完必须
证明捞不出来" —— 两者之间隔着所有没想到的路径。

钉死分两层:
- **脚本层**(快,不碰盘):挖空逻辑、指纹自校准、扫描器自证;
- **现场层**(读证据):`scripts/prepare_host2.py` 造完副本落的那份报告。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "docs" / "evidence" / "host2_prepare" / "report.json"


def _mod():
    spec = importlib.util.spec_from_file_location(
        "prepare_host2", REPO / "scripts" / "prepare_host2.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


# ------------------------------------------------------------------ 脚本层
def test_h1_carving_removes_bodies_but_keeps_signatures_and_docstrings():
    """H1:挖的是**函数体**,签名与 docstring 一个字不动。

    签名保留是有意的:任务要的是"把这些实现出来",不是"猜出有哪些函数"。
    连名字都藏起来,判的就变成"能不能猜到我们挖了什么" —— 那是用未言明的
    要求判人。docstring 是上游自己写的,删掉它等于我们**改写宿主**,
    那正是 F1 那条分界线不许做的事(ENRICHED 一律不算 held-out)。
    """
    src = '''
def f(a):
    """说明。"""
    x = a + 1
    return x * 2


class C:
    def m(self):
        return 42
'''
    carved, names = _mod()._carve(src)
    assert names == ["f", "m"]
    assert '"""说明。"""' in carved, "docstring 被挖掉了 —— 那是改写宿主"
    assert "def f(a):" in carved and "def m(self):" in carved
    assert "x = a + 1" not in carved and "return 42" not in carved
    assert carved.count("raise NotImplementedError") == 2
    # 挖完必须仍是合法 Python,且**没有多出**原件没有的符号
    before = {n.name for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    after = {n.name for n in ast.walk(ast.parse(carved))
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert after == before, f"符号集变了:{after ^ before} —— 那是 ENRICHED"


def test_h2_fingerprints_are_self_calibrating():
    """H2:指纹只留**原仓 seam 之外没出现过**的行。

    判据不能是"这行长不长",得是"这行是不是只有答案里才有"。头两版栽在
    这上面:`if self.openapi_version.major < 3:` 这种通用惯用行在原仓好几处
    都有,报出来纯噪声,真信号被淹。自校准的好处是换 seam、换宿主门槛自己变。
    """
    m = _mod()
    if not m.SRC.is_dir():
        pytest.skip("封存件不在本机")
    original = (m.SRC / m.SEAM).read_text(encoding="utf-8")
    fps = m._answer_fingerprints(original)
    assert fps, "一条指纹都没有 —— 扫描器什么都匹配不上,'零泄漏'是假绿"

    import re

    blob = "\n".join(
        f.read_text(encoding="utf-8", errors="replace")
        for f in m.SRC.rglob("*.py")
        if f.relative_to(m.SRC).as_posix() != m.SEAM and "/.git/" not in f.as_posix())
    for name, pat in fps:
        assert not re.search(pat, blob), (
            f"指纹 {name} 在原仓 seam 之外也出现 —— 它不是答案的指纹,是噪声")


def test_h3_the_scanner_proves_it_can_find_a_planted_answer():
    """H3:扫描器先证明自己查得出泄漏,才有资格发绿(常设纪律)。

    指纹刚被收窄过两轮,正是最该疑心"窄到什么都匹配不上"的时候。
    """
    m = _mod()
    if not m.HOST.is_dir():
        pytest.skip("副本未生成 —— 跑 scripts/prepare_host2.py")
    original = (m.SRC / m.SEAM).read_text(encoding="utf-8")
    assert m.selfcheck(original) == [], "扫描器自证没过"

    # 再当场演一次:把原件塞进副本,必须报出来
    planted = m.HOST / "_rp_test_planted.py"
    try:
        planted.write_text(original, encoding="utf-8")
        hits = m.leak_scan(original)
        assert any(h["file"] == planted.name for h in hits), (
            "原件原样塞进副本,扫描器竟然没报")
    finally:
        planted.unlink(missing_ok=True)
    assert m.leak_scan(original) == [], "还原后仍报泄漏 —— 扫描不稳定"


def test_h4_every_strip_entry_names_a_real_retrieval_path():
    """H4:剥离清单里的每一条都对应一条**实测过的取回路径**,不是"看着危险"。

    清单越长越像在做事,而多剥一样就多一分"改写宿主"的风险(F1)。
    所以每条都要说得出它堵的是什么。
    """
    m = _mod()
    for must in (".git", "tests", "__pycache__", "docs"):
        assert must in m.STRIP_DIRS, f"{must} 不在剥离清单里"
    for suf in (".pyc", ".pth", ".orig"):
        assert suf in m.STRIP_SUFFIXES
    src = (REPO / "scripts" / "prepare_host2.py").read_text(encoding="utf-8")
    # 每条剥离都要有一句说明它堵什么 —— 光有清单没有理由,后人不敢动也不敢留
    assert "git show HEAD:" in src and "隐藏 oracle" in src and "字节码" in src


# ------------------------------------------------------------------ 现场层
def _r() -> dict:
    if not REPORT.is_file():
        pytest.skip("部署层证据未落盘 —— 跑 scripts/prepare_host2.py")
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_h5_the_prepared_copy_is_leak_free():
    """H5:造好的副本里捞不出答案,且结构性检查全过。"""
    r = _r()
    assert r["leak_hits"] == [], f"副本里能捞到答案:{r['leak_hits']}"
    assert r["structural_problems"] == [], r["structural_problems"]
    assert r["ok"] is True
    assert len(r["carved_symbols"]) == 12, (
        f"挖空的符号数变了({len(r['carved_symbols'])})—— 题面变了,诚实尺寸要重算")


def test_h6_public_hints_are_disclosed_not_deleted():
    """H6:**留在副本里、确实降低难度、但不许删**的东西,必须逐条写出来。

    删了就是改写宿主(剥掉上游自己的公开文档,副本就不再是那个宿主了)。
    所以它们不是泄漏 —— 但不写出来的话,"10 个 node、1–2 bit"这句话就是虚的。

    泄漏与公开线索混成一栏最坏:要么为了"零泄漏"去删上游的文档,
    要么把真泄漏混进"已知无害"里放过。
    """
    r = _r()
    hints = r["disclosed_hints"]
    assert hints, "一条公开线索都没有?那说明根本没找过"
    for h in hints:
        for k in ("where", "what", "impact", "why_kept"):
            assert h.get(k), f"线索缺 {k}:{h}"
        assert "宿主" in h["why_kept"] or "上游" in h["why_kept"], (
            f"没说清为什么不能删:{h['why_kept']}")
    # 那条最要紧的必须在:Api.register_converter 的 docstring 里有完整示例
    assert any("register_converter" in h["where"] for h in hints)
