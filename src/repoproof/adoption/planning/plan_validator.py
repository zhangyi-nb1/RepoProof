"""Plan Validator(RFC-004)— 计划完整性校验;问题未答不得进入确认。"""

from __future__ import annotations

from repoproof.adoption.planning.adoption_plan import AdoptionPlan


class PlanInvalid(ValueError):
    pass


def validate_plan(plan: AdoptionPlan) -> list[str]:
    """返回缺口列表(空=完整)。"""
    gaps: list[str] = []
    for field in ("goal", "understanding", "integration_strategy", "estimated_changes"):
        if not getattr(plan, field, "").strip():
            gaps.append(f"计划缺少必填内容:{field}")
    if not plan.success_criteria:
        gaps.append("计划缺少成功标准")
    if not plan.strategies:
        gaps.append("计划缺少候选方案")
    elif not plan.recommended and not plan.requires_user_choice:
        # 空白项目模式(requires_user_choice)合法地没有系统推荐——
        # 由用户在确认时选定;其余计划必须有推荐
        gaps.append("计划缺少推荐方案")
    return gaps


def require_answers(plan: AdoptionPlan, answers: dict[str, str]) -> None:
    """每个开放问题必须有非空回答,否则不得进入 Human Gate。"""
    missing = [q for q in plan.questions if not (answers.get(q) or "").strip()]
    if missing:
        raise PlanInvalid(f"以下问题未回答,不能确认计划:{missing}")
