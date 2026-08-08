"""Repository Admission(RFC-003)— 纯确定性四态判定。

任何仓库可以分析;只有满足条件才进入自动适配。
优先级:UNSUPPORTED > NEED_INFORMATION > RISK_REVIEW > READY。
零 LLM / 零网络 / 零执行。
"""

from __future__ import annotations

from pydantic import BaseModel

from repoproof.adoption.admission.risk_checker import collect_risks
from repoproof.adoption.admission.support_policy import evaluate_policy
from repoproof.adoption.analysis.host_analyzer import HostProjectReport
from repoproof.adoption.analysis.repository_analyzer import RepositoryReport

READY = "READY"
NEED_INFORMATION = "NEED_INFORMATION"
UNSUPPORTED = "UNSUPPORTED"
RISK_REVIEW = "RISK_REVIEW"

_NEXT_STEP = {
    READY: "可以进入采用计划(Plan)阶段;开始前你仍需确认成功标准。",
    NEED_INFORMATION: "补齐下方「?」条目后重新检查;系统不会替你猜。",
    UNSUPPORTED: "更换目标仓库,或等待后续版本支持;下方「×」是硬性原因。",
    RISK_REVIEW: "逐条阅读「!」风险并确认接受后,才能进入采用计划。",
}


class AdmissionReport(BaseModel):
    status: str
    confirmed_facts: list[str] = []   # ✓
    questions: list[str] = []          # ?
    blockers: list[str] = []           # ×
    risks: list[str] = []              # !
    next_step: str = ""
    executes_third_party_code: bool = True

    def to_dict(self) -> dict:
        return self.model_dump()


def decide(host: HostProjectReport, repo: RepositoryReport) -> AdmissionReport:
    policy = evaluate_policy(host, repo)
    risks = collect_risks(host, repo)

    if policy.blockers:
        status = UNSUPPORTED
    elif policy.questions:
        status = NEED_INFORMATION
    elif risks:
        status = RISK_REVIEW
    else:
        status = READY

    return AdmissionReport(
        status=status,
        confirmed_facts=policy.confirmed,
        questions=policy.questions,
        blockers=policy.blockers,
        risks=risks,
        next_step=_NEXT_STEP[status],
        executes_third_party_code=(status != UNSUPPORTED),
    )


def apply_user_confirmations(
    report: AdmissionReport, confirmed_questions: list[str]
) -> AdmissionReport:
    """用户逐条人工确认后的报告形态(UI 深度检查勾选框 → 计划层)。

    被确认的 question 转为「已由你人工确认:…」的事实(出处=用户,
    系统仍未自动识别,不伪装成自动结论);状态按剩余待办重算。
    blockers 不受影响——阻断项不可被人工确认绕过。"""
    confirmed = [q for q in report.questions if q in confirmed_questions]
    if not confirmed:
        return report
    remaining = [q for q in report.questions if q not in confirmed_questions]
    if report.blockers:
        status = UNSUPPORTED
    elif remaining:
        status = NEED_INFORMATION
    elif report.risks:
        status = RISK_REVIEW
    else:
        status = READY
    return AdmissionReport(
        status=status,
        confirmed_facts=report.confirmed_facts + [f"已由你人工确认:{q}" for q in confirmed],
        questions=remaining,
        blockers=report.blockers,
        risks=report.risks,
        next_step=_NEXT_STEP[status],
        executes_third_party_code=report.executes_third_party_code,
    )
