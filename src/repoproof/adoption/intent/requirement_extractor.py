"""Requirement Extractor(RFC-004)— IntentDraft → DRAFT requirement 种子。

只产 DRAFT(status 固定),owner 预分配(输入校验→HOST_INPUT_GUARD,
其余→ADAPTER);绝不冻结、绝不生成最终 RequirementSpec——那是
Human Gate 之后、由既有 task check/freeze 流程负责的事。
"""

from __future__ import annotations

from pydantic import BaseModel

from repoproof.adoption.intent.intent_parser import IntentDraft


class DraftRequirement(BaseModel):
    id: str
    public_text: str
    owner: str
    severity: str = "HARD"
    status: str = "DRAFT"
    source: str = ""


def extract_requirements(draft: IntentDraft) -> list[DraftRequirement]:
    reqs: list[DraftRequirement] = []
    if draft.target_capability:
        reqs.append(DraftRequirement(
            id="core-capability", owner="ADAPTER",
            public_text=f"实现「{draft.target_capability}」:{draft.goal}",
            source="intent.goal + capability 推断"))
    if draft.expected_output:
        reqs.append(DraftRequirement(
            id="output-shape", owner="ADAPTER",
            public_text=f"输出满足:{draft.expected_output}",
            source="intent.expected_output(用户原文)"))
    reqs.append(DraftRequirement(
        id="input-guard", owner="HOST_INPUT_GUARD",
        public_text="畸形输入(缺字段/错类型)由宿主守卫以稳定错误码拒绝,不交给 AI 实现",
        source="平台默认(RFC-005 责任模型)"))
    for i, c in enumerate(draft.constraints, 1):
        reqs.append(DraftRequirement(
            id=f"user-constraint-{i}", owner="ADAPTER",
            public_text=c, source="intent.constraints(用户原文)"))
    return reqs
