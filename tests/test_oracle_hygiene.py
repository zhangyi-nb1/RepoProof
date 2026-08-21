"""oracle 卫生电池的钉死(v2 卫生判据,用户裁决 b;prereg-v2 §1/§3)。

电池回答:这套上游套件配不配当 held-out 的尺子。判定必须是纯函数
(`judge_hygiene`),跑套件的循环只负责搬运数字。

判据(冻结):
    H1  S-a 稳定线比**集合**不比条数 —— 25 换 25 也算病(判官换人了);
        failed/skipped/passed 三个集合七跑逐一相等才算稳;
    H2  计时线 = 钦定跑法单发 ≤ 120s(prereg-v2 §1.2:覆盖实测人口
        60.84–88.9s + 增长余量;协议不变:静机、单发、不重试);
    H3  FAIL_TO_PASS 的 parent 侧判定**复用驱动器的 measurement_problems**,
        不复制一份(复制品会静默漂移,M58a 的形状);
    H4  post 树(parent + 答案 patch)必须把 delta 集全部转绿且无新红 ——
        答案本身过不了自己的测试,这个 delta 就不是实现驱动的;
    H5  少于 2 跑判不了稳定性 → 拒绝,不猜。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(script: str):
    spec = importlib.util.spec_from_file_location(script[:-3], REPO / "scripts" / script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _score(passed=(), failed=(), skipped=()):
    return {"total": len(passed) + len(failed) + len(skipped),
            "passed": len(passed), "skipped": len(skipped),
            "passed_nodes": sorted(passed), "failed_nodes": sorted(failed),
            "skipped_nodes": sorted(skipped)}


def test_h1_stability_compares_sets_not_counts() -> None:
    oh = _load("oracle_hygiene.py")
    a = _score(passed=["t::a", "t::b"], skipped=["t::s1"])
    b_same = _score(passed=["t::a", "t::b"], skipped=["t::s1"])
    ok, problems = oh.judge_hygiene(runs=[a, b_same], canonical_seconds=10.0,
                                    delta_baseline=None, delta_nodes=None, post_run=None)
    assert ok, problems
    b_swap = _score(passed=["t::a", "t::s1"], skipped=["t::b"])   # 条数同、集合换
    ok, problems = oh.judge_hygiene(runs=[a, b_swap], canonical_seconds=10.0,
                                    delta_baseline=None, delta_nodes=None, post_run=None)
    assert not ok and any("集合" in p for p in problems), problems


def test_h2_canonical_timing_line_is_120s_single_shot() -> None:
    oh = _load("oracle_hygiene.py")
    assert oh.MAX_CANONICAL_SECONDS == 120
    a = _score(passed=["t::a"])
    ok, _ = oh.judge_hygiene(runs=[a, a], canonical_seconds=119.9,
                             delta_baseline=None, delta_nodes=None, post_run=None)
    assert ok
    ok, problems = oh.judge_hygiene(runs=[a, a], canonical_seconds=120.1,
                                    delta_baseline=None, delta_nodes=None, post_run=None)
    assert not ok and any("120" in p for p in problems), problems


def test_h3_parent_side_judgement_is_the_drivers_not_a_copy() -> None:
    oh = _load("oracle_hygiene.py")
    assert oh.measurement_problems.__module__ == "blind_attack_admission", (
        "parent 侧判定必须是驱动器那份函数本体,不是电池里的复制品")
    src = (REPO / "scripts" / "oracle_hygiene.py").read_text(encoding="utf-8")
    assert "def measurement_problems" not in src, "电池里出现了判定副本 —— 会静默漂移"
    # 语义联动:delta 在 parent 上就绿 → 电池同样拒
    a = _score(passed=["t::a", "t::new"])
    ok, problems = oh.judge_hygiene(
        runs=[a, a], canonical_seconds=1.0,
        delta_baseline=_score(passed=["t::a", "t::new"]),
        delta_nodes=frozenset({"t::new"}), post_run=_score(passed=["t::a", "t::new"]))
    assert not ok and any("就绿" in p for p in problems), problems


def test_h4_post_tree_must_green_the_delta_and_break_nothing() -> None:
    oh = _load("oracle_hygiene.py")
    a = _score(passed=["t::a"])
    base = _score(passed=["t::a"], failed=["t::new"])
    # 答案树上 delta 仍红 → 拒
    ok, problems = oh.judge_hygiene(
        runs=[a, a], canonical_seconds=1.0, delta_baseline=base,
        delta_nodes=frozenset({"t::new"}),
        post_run=_score(passed=["t::a"], failed=["t::new"]))
    assert not ok and any("post" in p.lower() for p in problems), problems
    # 答案树把旧套件打红 → 拒
    ok, problems = oh.judge_hygiene(
        runs=[a, a], canonical_seconds=1.0, delta_baseline=base,
        delta_nodes=frozenset({"t::new"}),
        post_run=_score(passed=["t::new"], failed=["t::a"]))
    assert not ok, problems
    # 双向干净 → 过
    ok, problems = oh.judge_hygiene(
        runs=[a, a], canonical_seconds=1.0, delta_baseline=base,
        delta_nodes=frozenset({"t::new"}),
        post_run=_score(passed=["t::a", "t::new"]))
    assert ok, problems


def test_h5_fewer_than_two_runs_refuses() -> None:
    oh = _load("oracle_hygiene.py")
    a = _score(passed=["t::a"])
    ok, problems = oh.judge_hygiene(runs=[a], canonical_seconds=1.0,
                                    delta_baseline=None, delta_nodes=None, post_run=None)
    assert not ok and any("稳定" in p for p in problems), problems


# ---------------------------------------------------------------- H6:题面欠定
# 判据(P1-c,2026-08-21;由 click-3407 双模型 FAIL 定因成文):
#   H6a 判死的是**体裁**不是难度 —— 选项分节 ≥2 且有对冲措辞,或对冲 ≥3 种;
#   H6b 单一弱信号不判死(一句 "we could" 不等于题没定);
#   H6c **没查 ≠ 干净**:signals=None 判死,不静默放行(M69c 同律);
#   H6d 池级扫描器不复制判据(复制品会静默漂移,H3 同律);
#   H6e 线是标定出来的:全池 14 候选实测只有 click-3407 命中,证据钉在
#       docs/evidence/d5_hunt/statement_determinacy/pool_screen.json。

_UNDERDETERMINED = """\
Some background about the feature.

### 1. Keep the current shape

We could leave it alone.

### 2. Parametrise the type

I think the second one is nicer.

### 3. Something else entirely

My preference?
"""

_DETERMINATE = """\
`show_version` should print the package version and exit.

It must work when the command is invoked without a parent context.
"""


def test_h6a_discussion_genre_statement_is_refused() -> None:
    oh = _load("oracle_hygiene.py")
    sig = oh.statement_determinacy_signals(_UNDERDETERMINED)
    assert sig["option_sections"] >= 2 and sig["hedges"]
    ok, problems = oh.judge_statement_determinacy(sig)
    assert not ok and any("欠定" in p for p in problems), problems


def test_h6b_determinate_statement_passes_and_single_signal_does_not_kill() -> None:
    oh = _load("oracle_hygiene.py")
    ok, problems = oh.judge_statement_determinacy(
        oh.statement_determinacy_signals(_DETERMINATE))
    assert ok, problems
    # 一句对冲 + 零选项分节 → 不判死(否则整池好题一起陪葬)
    ok, problems = oh.judge_statement_determinacy(
        oh.statement_determinacy_signals("We could add a flag here.\n"))
    assert ok, problems


def test_h6c_unchecked_statement_is_not_clean() -> None:
    oh = _load("oracle_hygiene.py")
    ok, problems = oh.judge_statement_determinacy(None)
    assert not ok and any("没查" in p for p in problems), problems


def test_h6d_pool_screener_holds_no_copy_of_the_judgement() -> None:
    src = (REPO / "scripts" / "statement_determinacy_screen.py").read_text(
        encoding="utf-8")
    for name in ("def statement_determinacy_signals", "def judge_statement_determinacy",
                 "option_sections\": len("):
        assert name not in src, f"扫描器里出现了判据副本({name})—— 会静默漂移"


def test_h6e_calibration_evidence_separates_the_pool() -> None:
    import json

    ev = json.loads((REPO / "docs/evidence/d5_hunt/statement_determinacy"
                     / "pool_screen.json").read_text(encoding="utf-8"))
    assert ev["candidate_count"] >= 14
    assert ev["flagged"] == ["click-3407"], (
        "标定证据变了:H6 的线是按'全池只有 click-3407 命中'定的,"
        f"现在命中 {ev['flagged']} —— 线或池动了,要重新标定而不是改断言")
    clean = [c for c in ev["candidates"] if c["verdict"] == "OK"]
    assert all(c["signals"]["option_sections"] == 0 for c in clean)
