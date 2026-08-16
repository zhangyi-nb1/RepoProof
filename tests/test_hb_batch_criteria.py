"""hb_batch_criteria 的钉死(V 系)。classify_run 是 HB 批唯一的归因判官,
每个分支各有一条守着;selftest 语义(三形态冒烟各归各位,错一自宣无效)
单独钉。真实素材侧的验证走 --selftest 对 F0 电池实跑(不在单测里重跑)。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from hb_batch_criteria import classify_run, delta_results, selftest  # noqa: E402

DELTA = ["tests.test_x::test_a", "tests.test_x::test_b[1]"]


def _facts(**over) -> dict:
    base = {
        "verdict": "FAIL", "delta_nodes": DELTA, "cap_failing": [],
        "cap_total": len(DELTA) + 4, "scoring_unavailable": False,
        "reg_passed": 100, "reg_baseline": 100, "provider_failure": False,
        "submitted": True, "impl_touched": True,
    }
    base.update(over)
    return base


def test_v1_pass_is_no_class():
    r = classify_run(_facts(verdict="PASS_ADAPTED"))
    assert r["j3"] is None and r["delta_green"] == 2


def test_v1b_pass_with_red_cap_is_a_harness_contradiction():
    r = classify_run(_facts(verdict="PASS_ADAPTED", cap_failing=["test_a"]))
    assert r["j3"] == "HARNESS_FAILURE"


def test_v2_provider_failure_wins():
    assert classify_run(_facts(provider_failure=True,
                               cap_failing=["test_h0_oracle_operable"])
                        )["j3"] == "PROVIDER_FAILURE"


def test_v3_h0_red_is_harness_failure():
    assert classify_run(_facts(cap_failing=["test_h0_oracle_operable"])
                        )["j3"] == "HARNESS_FAILURE"


def test_v3b_scoring_surface_mismatch_is_harness_failure():
    assert classify_run(_facts(cap_total=3))["j3"] == "HARNESS_FAILURE"


def test_v4_h1_or_h3_red_is_instrument_tampered():
    assert classify_run(_facts(cap_failing=["test_h1_instrument_surface_untouched"])
                        )["j3"] == "INSTRUMENT_TAMPERED"
    assert classify_run(_facts(cap_failing=["test_h3_tree_restored"])
                        )["j3"] == "INSTRUMENT_TAMPERED"


def test_v5_truly_empty_submission():
    assert classify_run(_facts(submitted=False, impl_touched=False,
                               cap_failing=["test_a", "test_b[1]"])
                        )["j3"] == "NO_SUBMISSION"


def test_v6_regression_broken_needs_some_delta_green():
    # delta 1 绿 1 红 + h2 红 → REGRESSION_BROKEN
    r = classify_run(_facts(cap_failing=["test_b[1]", "test_h2_no_regression_broken"]))
    assert r["j3"] == "REGRESSION_BROKEN" and r["delta_green"] == 1
    # delta 全红 + 回归破坏 → IMPL_INCOMPLETE(J3 定义:REGRESSION_BROKEN
    # 要求"delta 有转绿")
    r2 = classify_run(_facts(cap_failing=["test_a", "test_b[1]"],
                             reg_passed=90))
    assert r2["j3"] == "IMPL_INCOMPLETE"


def test_v7_inert_submission_is_impl_incomplete():
    """附录一第 6 条:惰性提交 ≠ 未提交(selftest 首跑抓过这条代理混用)。"""
    r = classify_run(_facts(impl_touched=False,
                            cap_failing=["test_a", "test_b[1]"]))
    assert r["j3"] == "IMPL_INCOMPLETE"


def test_v8_design_mismatch_is_the_last_resort():
    r = classify_run(_facts(cap_failing=["test_b[1]"]))
    assert r["j3"] == "DESIGN_MISMATCH" and r["delta_green"] == 1
    assert any("盲攻上界" in n for n in r["notes"])   # 引用纪律随判决走


def test_v9_delta_matching_tolerates_report_noise():
    green, total, red = delta_results(["test_b[1]]"], DELTA, len(DELTA) + 4)
    assert (green, total) == (1, 2) and red == ["tests.test_x::test_b[1]"]


def test_v10_selftest_rejects_misclassified_smoke():
    result = {"smoke_controls": [
        {"run_id": "r1", "model": "fake-scripted:positive",
         "j3": None, "verdict": "PASS_ADAPTED"},
        {"run_id": "r2", "model": "fake-scripted:control:nc_null_submission",
         "j3": "NO_SUBMISSION", "verdict": "FAIL"},          # 判错位
        {"run_id": "r3", "model": "fake-scripted:control:nc_regression_break",
         "j3": "REGRESSION_BROKEN", "verdict": "FAIL"},
    ]}
    bad = selftest(result)
    assert bad and "r2" in bad[0]


def test_v11_selftest_rejects_missing_material():
    bad = selftest({"smoke_controls": []})
    assert len(bad) == 4                     # 四形态素材缺席逐条点名
    assert all("素材缺席" in b for b in bad)  # 合成分支同时全过,不掺进来


def test_v12_synthetic_branches_cover_every_j3_class():
    """活体负控只覆盖得起三类,其余分支靠合成事实活检 —— 但"每类都有人考"
    这件事必须由测试钉死,否则合成表少一支没人知道(审查 should-fix)。"""
    from hb_batch_criteria import J3_CLASSES, SYNTHETIC_BRANCHES
    covered = {want for want, _ in SYNTHETIC_BRANCHES}
    assert set(J3_CLASSES) <= covered, f"J3 分支无人活检:{set(J3_CLASSES) - covered}"
    assert None in covered                   # 绿路(不落归因)也要有一支


def test_v12b_selftest_actually_runs_the_biopsy(monkeypatch):
    """表在≠考了(M72f 同型逃逸):selftest 若不遍历合成表,判错也无人知。
    往表里塞一支**必然判错**的期望,selftest 必须点名它。"""
    import hb_batch_criteria as m
    facts = {"verdict": "FAIL", "delta_nodes": ["a::b"], "cap_failing": ["x"],
             "cap_total": 5, "scoring_unavailable": False, "reg_passed": 100,
             "reg_baseline": 100, "provider_failure": False, "submitted": True,
             "impl_touched": True, "suite_timeout": False}
    monkeypatch.setattr(m, "SYNTHETIC_BRANCHES",
                        [("NO_SUCH_CLASS", facts)])   # 真判 DESIGN_MISMATCH
    bad = m.selftest({"smoke_controls": []})
    assert any("合成分支判错" in b for b in bad), \
        "selftest 没跑合成活检 —— 表在,但没人考"


def test_v13_suite_timeout_is_split_out_of_harness_failure():
    """agent 代码能拖慢套件。超时若归 HARNESS_FAILURE,蓄意超时就能刷连败
    去撞停批线 1 把整批停掉 —— 单列成类,不入连败计数(附录一第 9 条)。"""
    base = {"verdict": "FAIL", "delta_nodes": ["a::b"],
            "cap_failing": ["test_h0_oracle_operable"], "cap_total": 5,
            "scoring_unavailable": False, "reg_passed": 100, "reg_baseline": 100,
            "provider_failure": False, "submitted": True, "impl_touched": True}
    assert classify_run({**base, "suite_timeout": False})["j3"] == "HARNESS_FAILURE"
    hit = classify_run({**base, "suite_timeout": True})
    assert hit["j3"] == "SUITE_TIMEOUT"
    assert any("重跑" in n for n in hit["notes"])
