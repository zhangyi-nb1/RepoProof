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


def test_leak_guardrail_is_reverified_not_promised() -> None:
    """X9:§5 第四条护栏(隐藏泄漏 = 0)出判决时必须**重算**,不是抄结论。

    这条最容易退化成散文承诺 —— 它不是逐发量,证据躺在建包 json 里,没人
    重读也不会有任何东西变红。故钉的是"重验发生过"的痕迹:扫描器自证有牙
    + 有效指纹非零 + 部署树摘要至今相符。只回一个空 breaches 的实现过不了。
    """
    import json

    from wh_batch_criteria import HOST_EVIDENCE, leak_guardrail

    # 2026-08-23 收线清理后补的资源护栏:重验语义要求真部署树在盘上,
    # 树被清理时 skip(显式),不许把"树没了"读成"泄漏结论失效"或反之。
    bench_dir = Path(json.loads(HOST_EVIDENCE.read_text(encoding="utf-8"))
                     ["hosts"]["sqlglot-8042"]["bench_dir"])
    if not (bench_dir / "host").exists():
        pytest.skip(f"部署树不在本机({bench_dir});按 benchmarks/v2/ provisioning "
                    "记录重建宿主母树后可重验")

    out = leak_guardrail("sqlglot-8042")
    assert out["breaches"] == [], out["breaches"]
    c = out["checked"]
    assert c["hits"] == 0
    assert c["effective_fingerprints"] and c["effective_fingerprints"] > 0, "等于没扫"
    assert c["clean_zero"] and c["planted_detected"] and c["selfcheck_ok"], \
        "扫描器没自证有牙 —— 拔光牙的扫描器也报零命中"
    assert c["digest_match"], "部署树变了,那份泄漏结论说的是另一棵树"


def test_unknown_task_never_reads_as_no_leak() -> None:
    """X9 反面:认不出的任务不许判"没泄漏"。没证据 ≠ 有证据说没有。"""
    from wh_batch_criteria import leak_guardrail

    assert leak_guardrail("no-such-task-9999")["breaches"], "无证据却读成干净"


def test_leak_breach_outranks_any_gain() -> None:
    """X9 序:泄漏护栏与另外三条同级 —— 先于增益判,且不因增益漂亮而让路。"""
    from wh_batch_criteria import judge_arms

    strong = [_r("guided", 1, 5, is_pass=True), _r("minimal", 1, 0)]
    assert judge_arms(strong)["verdict"] == "GAIN"          # 无泄漏时确实是 GAIN
    out = judge_arms(strong, extra_breaches=["部署树命中答案指纹 ×3"])
    assert out["verdict"] == "INVALID", out
    assert any("答案指纹" in r for r in out["reasons"])


def test_smoke_split_fails_toward_excluding_not_scoring() -> None:
    """X8:计分池 / 自证池的分界线,失败方向必须朝**排除**。

    两个方向的代价不对称到不能对称处理:脚本 fake-positive 若漏进计分池,
    它长得和真 PASS 一模一样,直接造出假 GAIN 且没有下游检查会响;真发次
    若被误排除,两臂发次数不等 → INVALID,当场就响。

    故判别名换个写法(`scripted-fake:` / `FAKE-` / 中间带 fake)都必须仍
    判为脚本 —— `startswith("fake")` 那种写法漏的正是这些。
    """
    from wh_batch_criteria import is_smoke_model

    for m in ("fake-scripted:positive", "fake-scripted:control:nc_null_submission",
              "scripted-fake:positive", "FAKE-scripted:positive",
              "deepseek-v4-pro-fake", "scripted-noop"):
        assert is_smoke_model(m), f"{m} 该判脚本却没判"
    for m in ("deepseek-v4-pro", "gpt-5.5", "gpt-5.6"):
        assert not is_smoke_model(m), f"{m} 是真模型却被判成脚本"
    # 缺 model 的行不许被"选一个方向"消化掉 —— 归计分池是假 GAIN 的入口,
    # 归自证池是拿一行来历不明的记录去证明检查器有牙。两样都不行,只能炸。
    for missing in (None, "", "   "):
        with pytest.raises(ValueError):
            is_smoke_model(missing)


def test_the_smoke_split_has_exactly_one_implementation() -> None:
    """X8 结构面:分界线只许有一份实现。

    这是 usage 回调那次的同型病 —— 同一个谓词抄三份(计分池、自证池、
    `--f0-batch` 路),改其中一份,另两份静默走旧语义,而"哪份被走到"取决
    于命令行参数。故钉实现份数,不钉某一处的行为。
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "scripts" / "wh_batch_criteria.py"
    text = src.read_text(encoding="utf-8")
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    # 文档串里允许提旧写法(讲为什么不用它),代码里不许再出现
    code = re.sub(r'"""(?:.|\n)*?"""', "", body)
    assert 'startswith("fake")' not in code, "分界线又出现了第二份实现"
    assert code.count("def is_smoke_model") == 1
    assert code.count("is_smoke_model(") >= 4, "调用处少于三处 + 定义,可能有漏网的内联判别"


def test_run_attribution_is_reused_not_reimplemented() -> None:
    """WH 不重写逐发归因:同族任务上两份判据慢慢分叉,没人会发现。"""
    import hb_batch_criteria
    import wh_batch_criteria

    assert wh_batch_criteria.classify_run is hb_batch_criteria.classify_run
    assert wh_batch_criteria._facts_of is hb_batch_criteria._facts_of
