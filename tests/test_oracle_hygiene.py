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
