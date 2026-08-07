"""Strategy Selector(RFC-004)— 方案 A/B 生成与推荐,确定性规则。"""

from __future__ import annotations

from repoproof.adoption.analysis.host_analyzer import HostProjectReport


def select_strategy(api_names: list[str], host: HostProjectReport):
    from repoproof.adoption.planning.adoption_plan import Strategy

    a = Strategy(
        name="方案A:直接调用目标仓库公开接口",
        description=(
            f"适配层直接调用 {api_names or ['目标仓库入口']},只做输入输出映射"
        ),
        pros=["依赖简单", "修改范围小", "行为与上游一致,便于验收"],
        cons=["上游接口变化时需要跟进"],
    )
    b = Strategy(
        name="方案B:增加 wrapper 抽象层",
        description="在适配层与上游之间加一层自定义抽象,统一多个来源",
        pros=["未来可替换实现"],
        cons=["代码更多、验收面更大、偏离上游行为的风险更高"],
    )
    point = host.integration_candidates[0].file if host.integration_candidates else None
    if api_names:
        where = f",并接到你项目的 {point}" if point else ""
        return [a, b], a.name, f"目标仓库有清晰公开入口,直接调用最省、最贴近上游语义{where}"
    return [a, b], b.name, "未识别公开入口,需要 wrapper 包装内部模块(先确认入口更好)"
