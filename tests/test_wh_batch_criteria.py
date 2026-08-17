"""WH-PILOT-1 臂间判据的钉死(预注册 §5,D7 批准的替代判据)。

判据脚本自己也是被测对象 —— 它判错一支,整批读数就错一遍,而错的方向
通常朝松(把 null 读成增益)。故每一支都单独考,边界尤其:

  X1 护栏先于一切:假 PASS / 量具被动 / 引导臂回归破坏或违规更多 → INVALID;
  X2 主判据只看有效 PASS 差,且 PASS 必须过干净重放(否则是假 PASS);
  X3 次判据(delta 逐发)需 ≥2/3,**1/3 不算** —— 这条边界不钉,一发
     侥幸就会被读成 WEAK_GAIN;
  X4 反向对称:最小臂更优一律 ADVERSE,不许只报增益不报反效;
  X5 两臂发次数不等 = INVALID(不许拿 3 比 2);
  X6 NO_GAIN_IN_PILOT 必须自带措辞铁律(不得写成"harness 无增益");
  X7 配对按臂内执行序,不按大小排序 —— 排序会把两臂各自的最好成绩配成
     对子,那是事后择优(p-hacking 的机器版)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def _r(arm, order, delta, *, is_pass=False, j3="DESIGN_MISMATCH", **kw):
    return {"arm": arm, "order": order, "delta_green": delta, "is_pass": is_pass,
            "j3": j3, "verdict": "PASS_ADAPTED" if is_pass else "FAIL", **kw}


def test_every_synthetic_arm_branch_lands_where_declared() -> None:
    """判据脚本自带的分支活检必须全对 —— 它是 --selftest 的一半。"""
    from wh_batch_criteria import SYNTHETIC_ARM_BRANCHES, judge_arms

    wrong = [(want, judge_arms(runs)["verdict"])
             for want, runs in SYNTHETIC_ARM_BRANCHES
             if judge_arms(runs)["verdict"] != want]
    assert not wrong, f"合成分支判错:{wrong}"
    assert len(SYNTHETIC_ARM_BRANCHES) >= 10, "分支活检覆盖太薄"


@pytest.mark.parametrize("breach", [
    {"false_pass": True},
    {"j3": "INSTRUMENT_TAMPERED"},
    {"j3": "REGRESSION_BROKEN"},
    {"denied": 3},
])
def test_guardrails_outrank_any_gain(breach) -> None:
    """X1:护栏破了就是 INVALID —— 哪怕引导臂在结局量上赢得再漂亮。

    顺序很重要:先判增益再判护栏,会让"拿回归换 delta"的臂拿到 GAIN。
    """
    from wh_batch_criteria import judge_arms

    runs = [_r("guided", 1, 5, is_pass=True, **breach), _r("minimal", 1, 0)]
    out = judge_arms(runs)
    assert out["verdict"] == "INVALID", out
    assert out["guardrail_breaches"], "判了 INVALID 却说不出破在哪"


def test_a_pass_that_fails_clean_replay_is_not_a_pass() -> None:
    """X2:有效 PASS 的定义含干净重放。`is_pass` 由 IO 层按重放算,这里钉的是
    判据不许绕过它去读 verdict 字面。"""
    from wh_batch_criteria import judge_arms

    # verdict 写着 PASS 但 is_pass=False(重放没过)且未标 false_pass:
    # 不许因此判 GAIN。
    runs = [{"arm": "guided", "order": 1, "delta_green": 5, "is_pass": False,
             "j3": "DESIGN_MISMATCH", "verdict": "PASS_ADAPTED"},
            _r("minimal", 1, 0)]
    assert judge_arms(runs)["verdict"] != "GAIN"


def test_one_of_three_is_not_two_thirds() -> None:
    """X3 边界:3 发里赢 1 发不是 ≥2/3。差一发就换判决,线必须钉死。"""
    from wh_batch_criteria import judge_arms

    one = [_r("guided", 1, 4), _r("guided", 2, 0), _r("guided", 3, 0),
           _r("minimal", 1, 0), _r("minimal", 2, 0), _r("minimal", 3, 0)]
    two = [_r("guided", 1, 4), _r("guided", 2, 1), _r("guided", 3, 0),
           _r("minimal", 1, 0), _r("minimal", 2, 0), _r("minimal", 3, 0)]
    assert judge_arms(one)["verdict"] == "NO_GAIN_IN_PILOT"
    assert judge_arms(two)["verdict"] == "WEAK_GAIN"
    assert judge_arms(two)["pair_wins"]["needed"] == 2


def test_adverse_is_reported_symmetrically() -> None:
    """X4:最小臂更优必须报 ADVERSE。

    只报增益不报反效的判据,在 S2′ 那两批里正是会漏掉结论的那种 ——
    批 15 的价值恰恰在于它敢判否决。
    """
    from wh_batch_criteria import judge_arms

    by_pass = [_r("guided", 1, 0), _r("minimal", 1, 5, is_pass=True)]
    by_delta = [_r("guided", 1, 0), _r("guided", 2, 1), _r("guided", 3, 0),
                _r("minimal", 1, 2), _r("minimal", 2, 3), _r("minimal", 3, 0)]
    assert judge_arms(by_pass)["verdict"] == "ADVERSE"
    assert judge_arms(by_delta)["verdict"] == "ADVERSE"


def test_unequal_arms_are_invalid_not_compared() -> None:
    """X5:3 比 2 不许比 —— 缺的那发可能正是没跑完的那发。"""
    from wh_batch_criteria import judge_arms

    runs = [_r("guided", 1, 5, is_pass=True), _r("guided", 2, 5, is_pass=True),
            _r("minimal", 1, 0)]
    assert judge_arms(runs)["verdict"] == "INVALID"
    assert judge_arms([])["verdict"] == "INVALID"


def test_null_verdict_carries_its_own_wording_lock() -> None:
    """X6:NO_GAIN_IN_PILOT 必须把措辞铁律带在身上。

    判据只输出一个词,措辞纪律就只能靠人记得 —— 而人不记得。让它跟着
    判决一起出脚本,批报抄的时候就抄到了。
    """
    from wh_batch_criteria import judge_arms

    out = judge_arms([_r("guided", 1, 0), _r("minimal", 1, 0)])
    assert out["verdict"] == "NO_GAIN_IN_PILOT"
    assert any("无增益" in r for r in out["reasons"]), "null 判决没带措辞铁律"


def test_pairs_follow_execution_order_not_sorted_scores() -> None:
    """X7:配对按臂内执行序。

    反例是"两臂各自排序后配对":下面这组按序是 1 平 2 负 3 胜(不达线),
    按大小排序则变成 3-1 / 2-0 / 0-0 = 引导两胜 → WEAK_GAIN。事后择优
    换判决,这正是配对规则必须开跑前冻结的理由。
    """
    from wh_batch_criteria import judge_arms

    runs = [_r("guided", 1, 0), _r("guided", 2, 2), _r("guided", 3, 3),
            _r("minimal", 1, 0), _r("minimal", 2, 3), _r("minimal", 3, 1)]
    out = judge_arms(runs)
    assert [p["guided"] for p in out["pairs"]] == [0, 2, 3], "配对没按执行序"
    assert [p["minimal"] for p in out["pairs"]] == [0, 3, 1]
    assert out["pair_wins"] == {"guided": 1, "minimal": 1, "needed": 2}
    assert out["verdict"] == "NO_GAIN_IN_PILOT"


def test_run_attribution_is_reused_not_reimplemented() -> None:
    """WH 不重写逐发归因:同族任务上两份判据慢慢分叉,没人会发现。"""
    import hb_batch_criteria
    import wh_batch_criteria

    assert wh_batch_criteria.classify_run is hb_batch_criteria.classify_run
    assert wh_batch_criteria._facts_of is hb_batch_criteria._facts_of
