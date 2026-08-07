"""Adoption Plan(RFC-004)— Plan-only 模式的产物,模板化组装。

铁律:本模块只读入四份既有报告、只产计划对象——不 shell、不写文件、
不 Docker、不 git、零 LLM(静态测试钉死)。
"""

from __future__ import annotations

from pydantic import BaseModel

from repoproof.adoption.admission.admission_report import READY, RISK_REVIEW, AdmissionReport
from repoproof.adoption.analysis.host_analyzer import HostProjectReport
from repoproof.adoption.analysis.repository_analyzer import RepositoryReport
from repoproof.adoption.intent.intent_parser import IntentDraft
from repoproof.adoption.planning.strategy_selector import select_strategy


class Strategy(BaseModel):
    name: str
    description: str
    pros: list[str] = []
    cons: list[str] = []


class AdoptionPlan(BaseModel):
    goal: str
    understanding: str
    integration_strategy: str
    strategies: list[Strategy] = []
    recommended: str = ""
    rationale: str = ""
    estimated_changes: str
    success_criteria: list[str] = []
    risks: list[str] = []
    questions: list[str] = []

    def to_dict(self) -> dict:
        return self.model_dump()


def build_plan(
    intent: IntentDraft,
    host: HostProjectReport,
    repo: RepositoryReport,
    admission: AdmissionReport,
    *,
    accepted_risks: list[str] | None = None,
) -> AdoptionPlan:
    """READY 直接可出计划;RISK_REVIEW 必须由用户逐条接受全部风险
    (accepted_risks 覆盖 admission.risks)才可出计划——风险接受随后
    会被 Human Gate 冻结进 sha。其余状态一律拒绝。"""
    if admission.status == RISK_REVIEW:
        missing = [r for r in admission.risks if r not in (accepted_risks or [])]
        if missing:
            raise ValueError(f"存在未接受的风险,不能生成采用计划:{missing}")
    elif admission.status != READY:
        raise ValueError(
            f"适用性检查未通过(状态 {admission.status}),不能生成采用计划;"
            f"先处理:{admission.blockers or admission.questions or admission.risks}"
        )

    api_names = [str(f.value) for f in repo.public_api[:5]]
    strategies, recommended, rationale = select_strategy(api_names, host)

    integration_point = (
        host.integration_candidates[0].file if host.integration_candidates else "新建适配模块"
    )
    understanding = (
        f"你的项目:{host.project_type.value or '未知类型'}"
        f"(测试:{host.test_command.value or '未提供'});"
        f"目标仓库:{repo.repository} @ {str(repo.commit.value)[:12]}"
        f"(许可证 {repo.license.value},公开入口 {api_names or '未识别'});"
        f"目标能力:{intent.target_capability or '待确认'}"
    )
    success = [f"目标:{intent.goal}"]
    if intent.expected_output:
        success.append(f"输出满足:{intent.expected_output}")
    success.append("你的项目原有测试全部保持通过")
    success.append("适配代码在全新环境复测仍然成立")

    return AdoptionPlan(
        goal=intent.goal,
        understanding=understanding,
        integration_strategy=f"在 {integration_point} 接入;{recommended}",
        strategies=strategies,
        recommended=recommended,
        rationale=rationale,
        estimated_changes=(
            "新增 1 个适配文件(预计 ≤400 行,≤8 个文件的修改上限);"
            "不改动你的项目原有文件"
        ),
        success_criteria=success,
        risks=list(admission.risks),
        questions=[q for q in (*admission.questions, *intent.questions) if q],
    )
