"""差分注入的钉死 —— 修 A1 结构上限(F2)的那套机制。

F2:U4 比的是 `digest(交付产出) == digest(回执产出)`。上游算得对、被测方
**自己也算得对**时两者恒等 —— 所以 U3/U4 判的是"有没有按项数发出等量、
输入对得上的 RPC",**不是"值是不是从上游流过来的"**。

修法是让上游产出带一个只有 harness 算得出的标记。判据一个字不用改。

两层:
- **机制层**(本文件前半):标记本身的性质 —— 确定性、按输入分、按密钥分、
  密钥不外泄。
- **现场层**(后半,读 `scripts/differential_injection_matrix.py` 落的盘):
  同一份控制组跑两种模式,一边过一边不过。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
MATRIX = REPO / "docs" / "evidence" / "differential_injection" / "matrix.json"

from repoproof.execution.differential import (  # noqa: E402
    new_secret,
    perturb,
    perturbing_dispatch,
    strip_tag,
    tag_for,
)


# ------------------------------------------------------------------ 机制层
def test_d1_the_tag_is_deterministic_for_the_same_input():
    """D1:同一输入必须得到同一标记。

    不确定的话,**oracle 三次提交**那种诚实形态会被误杀 —— 每 nonce 三张
    回执、三个不同的产出,U4 的逐项对应当场垮掉。审查里明确否掉过
    "每 nonce 只许一张"的改法,就是因为它误杀这个形态。
    """
    s = new_secret()
    p = {"text": "# hi"}
    assert tag_for(p, s) == tag_for(p, s) == tag_for(dict(p), s)
    assert perturb("<h1>hi</h1>", p, s) == perturb("<h1>hi</h1>", p, s)


def test_d2_the_tag_is_scoped_to_the_input():
    """D2:标记必须**按输入**分。

    只按 run 分的话,把别项的标记抄过来就能过 —— 与"U3 的分母不能来自
    被测方"是同一条道理:判据不能锚在被测方能自己搬运的东西上。
    """
    s = new_secret()
    assert tag_for({"text": "a"}, s) != tag_for({"text": "b"}, s)
    # 别项的标记贴到本项上,`has_tag` 必须认不出
    from repoproof.execution.differential import has_tag

    other = perturb("x", {"text": "b"}, s)
    assert not has_tag(other, {"text": "a"}, s)
    assert has_tag(other, {"text": "b"}, s)


def test_d3_the_tag_is_unpredictable_without_the_secret():
    """D3:没有密钥就算不出标记 —— 否则整个差分注入等于没有。"""
    p = {"text": "# hi"}
    tags = {tag_for(p, new_secret()) for _ in range(20)}
    assert len(tags) == 20, "换了密钥标记却不变 —— 它没在用密钥"
    assert len(new_secret()) >= 32


def test_d4_perturbation_wraps_the_dispatch_not_the_sidecar():
    """D4:扰动包在**能力面**这一层,不在 sidecar 里。

    sidecar 只管鉴权、执行、记账。它若知道"产出被扰动过",回执记的就可能
    是**未扰动**的那一份 —— 那样 U4 比的还是原值,修等于没修。
    包在 dispatch 层的好处:回执天然记的是**实际返回给被测方的那一份**。
    """
    s = new_secret()
    called = []

    def _base(payload):
        called.append(payload)
        return "RAW"

    wrapped = perturbing_dispatch({"x.y": _base}, s)
    out = wrapped["x.y"]({"text": "t"})
    assert called == [{"text": "t"}], "原能力没被调用"
    assert out.startswith("RAW") and tag_for({"text": "t"}, s) in out
    assert strip_tag(out) == "RAW"

    src = (REPO / "src" / "repoproof" / "execution"
           / "upstream_sidecar.py").read_text(encoding="utf-8")
    assert "differential" not in src, (
        "sidecar 知道了扰动的存在 —— 它就可能记未扰动的那一份")


def test_d5_the_secret_never_reaches_the_agent():
    """D5:密钥不进 agent 环境、不落盘。漏一次,标记就可算。"""
    import tempfile

    from repoproof.execution.upstream_sidecar import UpstreamSpec, start_sidecar
    from repoproof.receipts.ledger import new_key, new_nonce

    s = new_secret()
    spec = UpstreamSpec("stdlib-json", "json",
                        perturbing_dispatch({"j.dumps": lambda p: "ok"}, s))
    d = Path(tempfile.mkdtemp())
    h = start_sidecar(spec=spec, ledger_path=d / "l.jsonl", key=new_key(),
                      run_id="r", run_nonce=new_nonce(), token="tok",
                      profile_id="rt-sidecar-test-v1", default_symbol="j.dumps")
    try:
        blob = json.dumps(h.agent_env())
        assert s.hex() not in blob and s.hex()[:16] not in blob
    finally:
        h.shutdown()


# ------------------------------------------------------------------ 现场层
def _m() -> dict:
    if not MATRIX.is_file():
        pytest.skip("差分注入证据未落盘 —— 跑 scripts/differential_injection_matrix.py")
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def test_d6_the_gap_was_measured_not_asserted():
    """D6:**上限是跑出来的,不是说出来的。**

    `nc9/plain`(照常发 RPC、交付自己算的)在未加注入时必须是 **PASS 零红**。
    它要是红的,那这套修复在修一个不存在的问题,而"修好了"就成了空话。
    """
    by = {(r["control"], r["mode"]): r for r in _m()["rows"]}
    plain = by[("nc9_memorised_but_calls", "plain")]
    assert plain["actual"] == "PASS" and not plain["actual_red"], (
        f"上限没被复现:nc9/plain 红在 {plain['actual_red']} —— "
        "要么控制组写错了,要么这个问题本来就不存在")


def test_d7_the_fix_works_and_is_not_a_wall():
    """D7:同一份控制组换个模式就从过变成不过;而正控两种模式都过。"""
    m = _m()
    assert m["ok"], f"差分注入矩阵有问题:{m['problems']}"
    by = {(r["control"], r["mode"]): r for r in m["rows"]}
    assert by[("nc9_memorised_but_calls", "perturbed")]["actual"] == "FAIL"
    assert by[("nc9_memorised_but_calls", "perturbed")]["actual_red"] == ["U4.adoption"], (
        "红在别处 —— 那是别的东西坏了,不是差分注入起了作用")
    for mode in ("plain", "perturbed"):
        assert by[("positive", mode)]["actual"] == "PASS", (
            f"正控在 {mode} 下红了 —— 差分注入把诚实实现也判死了,那是另一种墙")


def test_d8_the_matrix_judge_catches_planted_defects():
    """D8:判定函数先证明自己查得出缺陷,才有资格发绿(常设纪律)。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "differential_injection_matrix",
        REPO / "scripts" / "differential_injection_matrix.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    def _rows(over=None):
        over = over or {}
        base = []
        for (c, m), (v, red) in mod.EXPECT.items():
            r = {"control": c, "mode": m, "expect": v, "expect_red": sorted(red),
                 "actual": v, "actual_red": sorted(red)}
            r.update(over.get((c, m), {}))
            base.append(r)
        return base

    assert mod.find_problems(_rows()) == [], "干净数据上就报问题 —— 判定太紧"

    planted = {
        "修了个寂寞(注入后 nc9 仍过)": {
            ("nc9_memorised_but_calls", "perturbed"):
                {"actual": "PASS", "actual_red": []}},
        "修成了墙(正控被判死)": {
            ("positive", "perturbed"):
                {"actual": "FAIL", "actual_red": ["U4.adoption"]}},
        "上限根本没复现(plain 也红)": {
            ("nc9_memorised_but_calls", "plain"):
                {"actual": "FAIL", "actual_red": ["U4.adoption"]}},
        "红错了地方": {
            ("nc9_memorised_but_calls", "perturbed"):
                {"actual": "FAIL", "actual_red": ["U3.coverage"]}},
        # **最像会真发生的那种削弱**:现实坏了,而有人改 EXPECT 去迁就它。
        # 这时逐行比对全绿(actual == expect),只有"两种模式必须分开"
        # 与"正控必须过"这两条还在说话 —— 它们只看 actual,不看 EXPECT。
        # 实测:头一版这两条从 EXPECT 出发,与逐行比对互为冗余,M62d/M62e
        # 双双逃逸。
        "改了 EXPECT 去迁就'注入没起作用'": {
            ("nc9_memorised_but_calls", "perturbed"):
                {"expect": "PASS", "expect_red": [],
                 "actual": "PASS", "actual_red": []}},
        "改了 EXPECT 去迁就'正控被判死'": {
            ("positive", "perturbed"):
                {"expect": "FAIL", "expect_red": ["U4.adoption"],
                 "actual": "FAIL", "actual_red": ["U4.adoption"]}},
    }
    for label, over in planted.items():
        assert mod.find_problems(_rows(over)), f"查不出:{label}"
