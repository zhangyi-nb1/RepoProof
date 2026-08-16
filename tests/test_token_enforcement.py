"""LESSONS #39(执法读到陈旧总量 + 固定内移是猜的)— token 不越线的钉死。

实录反例(order-63,gpt-5.6 × T3v5,轮 1):政策线 800,000/轮,执法线
内移到 750,000。第 22 次调用后真实累计 **752,243**(已过执法线),第 23
次调用仍被放行,调用后 **803,310 > 800,000** —— 一发公开 23/23 + 隐藏
8/8 的满分适配被终局以 0.41% 的超出击杀。

双缺陷,缺一不可修:

  D1 陈旧总量:记账走 `litellm.success_callback`,而 litellm 用
     `executor.submit(...)` 把回调**丢进线程池**(utils.py:1479)。调用
     前读到的总量落后一次调用 —— 第 23 次调用前读到的是 703,172。
     此前的钉死没抓住,是因为**测试替身比生产更强**:FakeInner 在
     `query()` 里同步写 totals,生产的钩子是异步的。
  D2 固定内移:`TOKEN_STOP_MARGIN = 50_000` 是拍的数,而该轮单次最大
     调用 51,067 —— 差 1,067 就翻车。猜一个常数永远会有下一次。

冻结判据:
  H7-a 执法不得只依赖异步上报:响应体带 usage 而 totals 不被写时,
       第 N 次调用前必须已计入第 N−1 次的真实用量;
  H7-b 调用前投影:仅当 `已用 + 本次投影 ≤ 硬上限` 才发起调用;投影
       = max(本次消息本地估算 × 校准比值 × 安全系数, 已观测单次最大);
  H7-c 不可越线:每次真实用量 ≤ 投影时,累计输入**永不越过**硬上限;
  H7-d 轮桶归同步记账所有 —— 异步钩子会把上一轮末次调用记到下一轮;
  H7-e 不许假零、不许少报:provider 沉默时不写 0,同步记账为 0 时
       不得低于钩子读数。
边界(§39):政策判据仍是契约的每轮上限,一字不动。改的是执法,不是判据;
执法线不再内移,agent 拿到的恰是契约承诺的额度,不多不少。
"""

from __future__ import annotations

import pytest
from minisweagent.exceptions import LimitsExceeded

# 新符号刻意**不在模块级导入**(LESSONS #34:红的粒度必须与钉死的粒度
# 一致)。模块级导入会让修复前的树整文件收集失败,红绿证据退化成文件级。


class AsyncReportingInner:
    """生产形态的替身:usage 只出现在**返回体**里,totals 由"线程池"
    延后写 —— 本替身干脆永不写,把异步延迟放大成最坏情况。"""

    def __init__(self, per_call_in: int, per_call_out: int = 100) -> None:
        self.per_call = (per_call_in, per_call_out)
        self.calls = 0
        self.true_in = 0

    def query(self, messages, **kwargs):  # noqa: ANN001, ARG002
        self.calls += 1
        self.true_in += self.per_call[0]
        return {"role": "assistant", "content": "ok",
                "extra": {"actions": [],
                          "response": {"usage": {"prompt_tokens": self.per_call[0],
                                                 "completion_tokens": self.per_call[1]}}}}


def _msgs(chars: int) -> list[dict]:
    return [{"role": "user", "content": "x" * chars}]


def test_enforcement_does_not_rely_on_the_async_usage_hook() -> None:
    """H7-a:钩子一个字都不写,执法照样必须停。

    反例=order-63 轮 1:钩子落后一次调用,执法读到 703,172 就放行了那次
    把累计推到 803,310 的调用。"""
    from repoproof.agents.token_budget import TokenBudgetedModel

    totals = {"in": 0, "out": 0, "seen": False}       # 钩子永不落地
    inner = AsyncReportingInner(per_call_in=1_000)
    model = TokenBudgetedModel(inner=inner, totals=totals,
                               max_input_tokens=5_000, max_output_tokens=10_000)
    with pytest.raises(LimitsExceeded):
        for _ in range(20):
            model.query(_msgs(40))
    assert totals["in"] == 0, "本用例的前提就是钩子沉默"
    assert inner.true_in <= 5_000, f"越线了:真实累计 {inner.true_in} > 5000"
    assert inner.calls >= 4, "不得因为读不到用量就一次都不敢发"


def test_no_single_call_can_cross_the_hard_cap() -> None:
    """H7-c:单次 51,000、上限 800,000 —— 越线必须**不可能发生**。

    反例=order-63:固定内移 50,000 < 单次最大 51,067,于是 803,310。"""
    from repoproof.agents.token_budget import TokenBudgetedModel

    totals = {"in": 0, "out": 0, "seen": False}
    inner = AsyncReportingInner(per_call_in=51_000)
    model = TokenBudgetedModel(inner=inner, totals=totals,
                               max_input_tokens=800_000, max_output_tokens=10_000_000)
    with pytest.raises(LimitsExceeded) as ei:
        for _ in range(40):
            model.query(_msgs(40))
    assert inner.true_in <= 800_000, f"越线了:{inner.true_in} > 800000"
    # 也不许因噎废食:投影只该挡住**最后**那次放不下的调用
    assert inner.true_in > 800_000 - 2 * 51_000, f"停得太早:只用了 {inner.true_in}"
    assert ei.value.messages[0]["extra"]["exit_status"] == "TokenBudgetExhausted"
    assert model.exhausted is not None and model.exhausted["reason"] == "projected"


def test_projection_floor_is_the_largest_observed_call() -> None:
    """H7-b(下限支):消息短到估算近乎为零时,靠"已观测单次最大"兜底。

    这一支单独钉,是因为本地估算天然会失准(工具 schema、系统开销、
    provider 侧改写都不在消息里),不能让不可能越线的保证只挂在估算上。"""
    from repoproof.agents.token_budget import TokenBudgetedModel

    totals = {"in": 0, "out": 0, "seen": False}
    inner = AsyncReportingInner(per_call_in=30_000)
    model = TokenBudgetedModel(inner=inner, totals=totals,
                               max_input_tokens=100_000, max_output_tokens=10_000_000)
    with pytest.raises(LimitsExceeded):
        for _ in range(10):
            model.query(_msgs(4))          # 估算 ≈ 1 token,真实 30,000
    assert inner.true_in <= 100_000, f"越线了:{inner.true_in} > 100000"
    assert model.max_call_in == 30_000


def test_local_estimate_catches_a_prompt_that_suddenly_grows() -> None:
    """H7-b(估算支):历史都是小调用,下一次提示突然变大 —— 已观测最大
    救不了,必须靠对**本次消息**的估算。"""
    from repoproof.agents.token_budget import TokenBudgetedModel

    totals = {"in": 0, "out": 0, "seen": False}
    inner = AsyncReportingInner(per_call_in=1_000)
    model = TokenBudgetedModel(inner=inner, totals=totals,
                               max_input_tokens=12_000, max_output_tokens=10_000_000)
    for _ in range(9):
        model.query(_msgs(400))            # 已用 9,000;已观测单次最大 1,000
    assert inner.calls == 9
    with pytest.raises(LimitsExceeded):
        model.query(_msgs(200_000))        # 本次提示估算 ≫ 剩余 3,000
    assert inner.calls == 9, "放不下的那次调用必须根本不发生"


def test_estimator_never_undercounts_cjk() -> None:
    """H7-b(估算的老实度):中文按字算,不许照搬 chars/4。

    order-63 的实测:chars/4 把轮 1 估成 604,905,真实 803,310(比值
    1.33);按字算是 754,295(比值 1.07)。估算越准,投影浪费越小。"""
    from repoproof.agents.token_budget import estimate_prompt_tokens

    cn = estimate_prompt_tokens([{"role": "user", "content": "中" * 1_000}])
    en = estimate_prompt_tokens([{"role": "user", "content": "a" * 1_000}])
    assert cn >= 1_000, f"1000 个汉字不该只算 {cn} 个 token"
    assert en < cn, "英文的 token 密度应低于中文"


def test_round_bucket_prefers_synchronous_accounting() -> None:
    """H7-d:异步钩子会把上一轮末次调用记进下一轮的桶,轮桶只认同步记账。

    轮桶是**终局政策判据的输入**(per_round 比的是单轮最大用量),被串
    了账就会拿别人的 token 杀这一轮 —— 与 order-63 同型的伏击。"""
    from repoproof.runner.host_guided import round_usage

    class _Synced:
        seen, used_in, used_out = True, 100, 10

    polluted = {"in": 999_999, "out": 999, "seen": True}     # 上一轮漏过来的
    assert round_usage(_Synced(), polluted) == (100, 10)

    class _Silent:
        seen, used_in, used_out = False, 0, 0

    # 同步记账拿不到用量时才回落到桶 —— 不许因为"我没记到"就报 0
    assert round_usage(_Silent(), {"in": 42, "out": 4, "seen": True}) == (42, 4)
    assert round_usage(object(), {"in": 7, "out": 1, "seen": True}) == (7, 1)


def test_never_reports_below_the_hook_and_never_fabricates_zero() -> None:
    """H7-e:钩子写了、返回体没带 usage 时,执法用的是钩子的数;
    两边都沉默时保持 UNKNOWN,不许写成 0。"""
    from repoproof.agents.token_budget import TokenBudgetedModel

    class HookOnlyInner:
        def __init__(self, totals):
            self.totals, self.calls = totals, 0

        def query(self, messages, **kwargs):  # noqa: ANN001, ARG002
            self.calls += 1
            self.totals["seen"] = True
            self.totals["in"] += 1_000
            return {"role": "assistant", "content": "ok", "extra": {"actions": []}}

    totals = {"in": 0, "out": 0, "seen": False}
    model = TokenBudgetedModel(inner=HookOnlyInner(totals), totals=totals,
                               max_input_tokens=2_500, max_output_tokens=10_000)
    model.query(_msgs(20))
    assert model.used_in == 1_000, "同步记账为 0 时不得低于钩子读数"
    with pytest.raises(LimitsExceeded):
        for _ in range(10):
            model.query(_msgs(20))

    silent_totals = {"in": 0, "out": 0, "seen": False}

    class SilentInner(HookOnlyInner):
        def query(self, messages, **kwargs):  # noqa: ANN001, ARG002
            self.calls += 1
            return {"role": "assistant", "content": "ok", "extra": {"actions": []}}

    quiet = TokenBudgetedModel(inner=SilentInner(silent_totals), totals=silent_totals,
                               max_input_tokens=2_500, max_output_tokens=10_000)
    quiet.query(_msgs(20))
    quiet.query(_msgs(20))
    assert quiet.seen is False and silent_totals["seen"] is False
    assert quiet.inner.calls == 2, "用量未知不是停跑的理由(终局也不以 UNKNOWN 杀)"


def test_run_level_hook_counts_a_streaming_request_once() -> None:
    """H7-f:流式双终态事件不得翻倍 run 级读数(HB-DSENTRY-1 批报 §4)。

    实录反例:deepseek 流式路对同一请求派发两枚带 usage 的 success 事件
    (末 chunk 自带全额 usage + 组装完毕的 complete_streaming_response 又
    带同一份;单调用探针 66 枚逐 chunk usage=None + 2 枚终态满额)。回调
    桶不去重 → 台账 input_tokens 虚高 1.30×/1.50×(571,266/807,266 vs
    供方计费 439,486/538,107)。执法(同步记账)不受影响 —— 病只在
    run 级汇总口径,但台账读数必须是供方计费口径。"""
    from types import SimpleNamespace

    from repoproof.runner.host_guided import make_usage_cb

    totals = {"in": 0, "out": 0, "seen": False}
    cb = make_usage_cb(totals)
    usage = SimpleNamespace(prompt_tokens=14_000, completion_tokens=200)

    # 逐 chunk 事件 usage=None:不触桶
    for _ in range(3):
        cb({"litellm_call_id": "req-1"}, SimpleNamespace(usage=None), None, None)
    assert totals == {"in": 0, "out": 0, "seen": False}

    # 同一请求两枚终态(末 chunk 满额 usage + 组装响应同一份)→ 只记一次
    cb({"litellm_call_id": "req-1"}, SimpleNamespace(usage=usage), None, None)
    cb({"litellm_call_id": "req-1"}, SimpleNamespace(usage=usage), None, None)
    assert (totals["in"], totals["out"]) == (14_000, 200), "同请求第二枚终态事件翻倍了读数"

    # id 藏在 litellm_params 里的派发形态,同样按请求去重
    cb({"litellm_params": {"litellm_call_id": "req-1"}}, SimpleNamespace(usage=usage), None, None)
    assert totals["in"] == 14_000

    # 不同请求照常累加(gpt 非流式单枚事件即此形态)
    cb({"litellm_call_id": "req-2"}, SimpleNamespace(usage=usage), None, None)
    assert (totals["in"], totals["out"]) == (28_000, 400)
    assert totals["seen"] is True


def test_run_level_hook_without_call_id_keeps_counting() -> None:
    """H7-f 边界 = H7-e 的不许少报:拿不到 litellm_call_id 的事件不去重、
    不静默丢 —— 宁可维持旧行为(可能虚高)也不许漏记。"""
    from types import SimpleNamespace

    from repoproof.runner.host_guided import make_usage_cb

    totals = {"in": 0, "out": 0, "seen": False}
    cb = make_usage_cb(totals)
    usage = SimpleNamespace(prompt_tokens=1_000, completion_tokens=10)
    cb({}, SimpleNamespace(usage=usage), None, None)
    cb(None, SimpleNamespace(usage=usage), None, None)
    assert (totals["in"], totals["out"]) == (2_000, 20), "无 id 事件被丢弃 = 少报"
