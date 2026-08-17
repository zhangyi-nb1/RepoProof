"""WH 两臂(D4 的操作定义)—— H0 最小安全 vs H2 引导执行的钉死。

方案文档 §7.2 把 H2 写成十件套,盘上**六件不存在**(S3/S4 从未建、S5 判
BLOCKED、S2′ 归档关闭)。照那张清单实现等于为一次消融临时造六个没有独立
证据的机制。故两臂按盘上真有的东西定义,差集 = 今天 harness 所谓"引导"
的全部:多轮编排 + 结构化失败包 + 最佳态回滚 + 轮抬头。

冻结判据:
  W1 缺省与拼错一律 guided —— 未知取值不许静默把发次降成最小臂;
  W2 同总额:最小臂单轮拿满 原每轮 × 原轮数(per_round 语义);
     `semantics="total"` 只收轮数不乘(那本就是全 run 额度);
  W3 patch/wall 两臂逐字相同 —— 它们约束交付物与墙钟,不是努力量;
     两臂的验收必须是同一条线,否则比的是"谁被允许交更大的东西";
  W4 两臂不混池(三面指纹 + 代际标签必须不同),且 **guided 臂的指纹与
     代际逐字节不受本特性影响**(判据 F5:不追溯改写历史发次);
  W5 引导文本只在 guided 臂出现;最小臂保留安全句(不许编造测试结果)
     —— 差的是引导,不是安全,否则测出来的是安全网的价值。
"""

from __future__ import annotations

import pytest

# 刻意不在模块级导入被考符号(LESSONS #34:红的粒度要与钉死的粒度一致)。


def _budgets(**over):
    from repoproof.runner.host_guided import HostBudgets

    base = dict(semantics="per_round", max_rounds=3, max_model_calls=30,
                max_commands=100, max_patch_files=15, max_patch_lines=1500,
                max_wall_time_minutes=60, max_input_tokens_total=600_000,
                max_output_tokens_total=80_000)
    base.update(over)
    return HostBudgets(**base)


@pytest.mark.parametrize("raw", [None, "", "guided", "GUIDED", "minimal_safe",
                                 "h0", "1", "true", "  "])
def test_unknown_harness_mode_falls_back_to_guided(monkeypatch, raw) -> None:
    """W1:缺省/拼错一律 guided。

    方向很重要 —— 回落到**当前完整 harness**。反过来(未知即最小)会让
    一次拼写错误静默把发次降成最小臂,而两臂的读数会被当同一池分析。
    """
    from repoproof.runner.host_guided import harness_mode

    if raw is None:
        monkeypatch.delenv("REPOPROOF_HARNESS_MODE", raising=False)
    else:
        monkeypatch.setenv("REPOPROOF_HARNESS_MODE", raw)
    assert harness_mode() == "guided"


@pytest.mark.parametrize("raw", ["minimal", "MINIMAL", " minimal "])
def test_minimal_is_opt_in_by_exact_value(monkeypatch, raw) -> None:
    """W1 另一半:恰好写对才进最小臂(大小写与空白宽容,别的不宽容)。"""
    from repoproof.runner.host_guided import harness_mode

    monkeypatch.setenv("REPOPROOF_HARNESS_MODE", raw)
    assert harness_mode() == "minimal"


def test_minimal_arm_keeps_the_total_effort_budget_identical() -> None:
    """W2:§7 的题面是"相同任务和相同总预算"。

    per_round 语义下总额 = 每轮 × 轮数,所以最小臂单轮必须拿满那个总和。
    少给 = 测的是"额度被砍了三分之二",不是"没给引导" —— 那是另一个实验。
    """
    from repoproof.runner.host_guided import effective_budgets

    b = _budgets()
    m = effective_budgets(b, "minimal")
    assert m.max_rounds == 1
    for field in ("max_model_calls", "max_commands",
                  "max_input_tokens_total", "max_output_tokens_total"):
        assert getattr(m, field) == getattr(b, field) * b.max_rounds, (
            f"{field} 的总额两臂不等 —— 这一发比的就不是引导了")


def test_total_semantics_budget_is_not_multiplied() -> None:
    """W2 边界:`semantics="total"`(v1 语义)本就是全 run 额度,只收轮数。

    乘了就是白送两倍额度给最小臂 —— 同一个换算式对两种语义必须给出两种
    答案,这正是它不能写成"反正乘上去"的原因。
    """
    from repoproof.runner.host_guided import effective_budgets

    b = _budgets(semantics="total")
    m = effective_budgets(b, "minimal")
    assert m.max_rounds == 1
    assert m.max_model_calls == b.max_model_calls
    assert m.max_input_tokens_total == b.max_input_tokens_total


def test_minimal_arm_does_not_relax_deliverable_or_wall_limits() -> None:
    """W3:patch/wall 不乘(HostBudgets 原文:两者恒为全 run)。

    乘了就等于最小臂被允许交三倍大的补丁 —— 两臂的验收线必须逐字同一条,
    否则赢的那臂可能只是被允许交更大的东西。
    """
    from repoproof.runner.host_guided import effective_budgets

    b = _budgets()
    m = effective_budgets(b, "minimal")
    assert (m.max_patch_files, m.max_patch_lines, m.max_wall_time_minutes) == (
        b.max_patch_files, b.max_patch_lines, b.max_wall_time_minutes)


def test_guided_arm_is_an_identity_transform() -> None:
    """W4 前半:guided 臂必须**原对象返回** —— 既有全部发次一字不动(§39)。"""
    from repoproof.runner.host_guided import effective_budgets

    b = _budgets()
    assert effective_budgets(b, "guided") is b
    assert effective_budgets(_budgets(max_rounds=1), "minimal").max_rounds == 1


def test_two_arms_do_not_share_a_pool() -> None:
    """W4:两臂的三面指纹与代际标签必须不同,且 guided 臂不受本特性影响。

    guided 侧钉的是**逐字节不变**:历史发次绑着旧 hash,判据 F5 不许追溯
    改写。所以新特性只许在非默认臂**加键**。
    """
    from repoproof.agents.profiles import exec_generation, profile_hashes

    tool = {"action_protocol": "textbased", "tools": ["bash"], "obs_char_cap": 8000}
    ctx = {"policy": "full-history-resend", "obs_char_cap": 8000}
    budget = {"semantics": "per_round", "max_rounds": 3}

    guided = profile_hashes(tool=tool, context=ctx, budget=budget)
    minimal = profile_hashes(tool={**tool, "harness_mode": "minimal"},
                             context={**ctx, "guidance": "none"},
                             budget={**budget, "max_rounds": 1})

    assert guided["tool_profile_hash"] != minimal["tool_profile_hash"]
    assert guided["context_profile_hash"] != minimal["context_profile_hash"]
    assert guided["budget_profile_hash"] != minimal["budget_profile_hash"]

    # 代际:最小臂是**减配**,不是 E1 增强 —— 标签不许读成"加了一步"。
    assert exec_generation(context=ctx, tool=tool) == "E0"
    assert exec_generation(context={**ctx, "guidance": "none"}, tool=tool) == "E0-H0"
    assert exec_generation(context={"prune_policy": "window-v1", "guidance": "none"},
                           tool=tool) == "E1-S2-H0"


def test_guidance_text_is_the_whole_difference_and_safety_is_not() -> None:
    """W5:引导四样只在 guided 臂;安全句两臂都有。

    最小臂照发"修复轮/失败包/最佳态回滚/scope-change"= 教一条它没有的路
    (#33 先教后杀的反面:不许教做不到的事)。而"不许编造测试结果"是安全面
    —— 摘掉它,赢的那臂就可能只是赢在没被允许撒谎。
    """
    from repoproof.runner.host_guided import round_guidance

    guided = round_guidance("guided", idx=2, max_rounds=3, marker="SCOPE:")
    minimal = round_guidance("minimal", idx=1, max_rounds=1, marker="SCOPE:")

    assert "Never invent test results." in guided
    assert "Never invent test results." in minimal, "安全句不是引导,不许摘"

    for taught_only_when_real in ("REPAIR ROUND", "failure packets",
                                  "ROLLBACK", "SCOPE:"):
        assert taught_only_when_real.lower() in guided.lower()
        assert taught_only_when_real.lower() not in minimal.lower(), (
            f"最小臂教了它没有的 {taught_only_when_real!r}")
