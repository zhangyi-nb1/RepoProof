"""Adoption Plan(RFC-004)— Plan-only 模式的产物,模板化组装。

铁律:本模块只读入四份既有报告、只产计划对象——不 shell、不写文件、
不 Docker、不 git、零 LLM(静态测试钉死)。
"""

from __future__ import annotations

from pydantic import BaseModel

from repoproof.adoption.admission.admission_report import READY, RISK_REVIEW, AdmissionReport
from repoproof.adoption.analysis.host_analyzer import BLANK_PROJECT, HostProjectReport
from repoproof.adoption.analysis.repository_analyzer import RepositoryReport
from repoproof.adoption.intent.intent_parser import IntentDraft
from repoproof.adoption.planning.strategy_selector import select_strategies


class Strategy(BaseModel):
    name: str
    description: str
    pros: list[str] = []
    cons: list[str] = []
    # RFC-008 §7.2 扩展字段(默认空,向后兼容)
    kind: str = ""
    why: str = ""
    est_changed_files: list[str] = []
    new_dependencies: list[str] = []
    needs_network: bool = False
    needs_secret: bool = False
    modifies_host: bool = False
    risks: list[str] = []
    alternatives: list[str] = []
    verification: str = ""


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
    # RFC-008:空白项目模式必须由用户选定建站计划;host_mode 随计划留档
    requires_user_choice: bool = False
    host_mode: str = ""

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
    strategies, recommended, rationale, requires_choice = select_strategies(host, repo)
    blank = host.host_mode.value == BLANK_PROJECT

    integration_point = (
        host.integration_candidates[0].file if host.integration_candidates else "新建适配模块"
    )
    understanding = (
        f"你的项目:{'空白目录(新项目)' if blank else (host.project_type.value or '未知类型')}"
        f"(测试:{'不适用——空目录无原有功能' if blank else (host.test_command.value or '未提供')});"
        f"目标仓库:{repo.repository} @ {str(repo.commit.value)[:12]}"
        f"(许可证 {repo.license.value},公开入口 {api_names or '未识别'});"
        f"目标能力:{intent.target_capability or '待确认'}"
    )
    success = [f"目标:{intent.goal}"]
    if intent.expected_output:
        success.append(f"输出满足:{intent.expected_output}")
    if blank:
        success.append("新项目能安装、能启动,目标能力可运行且输出符合约定")
        success.append("启动命令与依赖锁存在;适配代码在全新环境复测仍然成立")
    else:
        success.append("你的项目原有测试全部保持通过")
        success.append("适配代码在全新环境复测仍然成立")

    if requires_choice:
        est = "取决于你选定的建站计划(三种计划的修改范围见下方对比);未选定前不开工"
        integ = "空白项目模式:三种建站计划待你选择"
    else:
        rec_obj = next((s for s in strategies if s.name == recommended), None)
        est = ";".join(rec_obj.est_changed_files) if rec_obj and rec_obj.est_changed_files else (
            "新增 1 个适配文件(预计 ≤400 行,≤8 个文件的修改上限);不改动你的项目原有文件")
        integ = f"在 {integration_point} 接入;{recommended}"

    return AdoptionPlan(
        goal=intent.goal,
        understanding=understanding,
        integration_strategy=integ,
        strategies=strategies,
        recommended=recommended,
        rationale=rationale,
        estimated_changes=est,
        success_criteria=success,
        risks=list(admission.risks),
        questions=[q for q in (*admission.questions, *intent.questions) if q],
        requires_user_choice=requires_choice,
        host_mode=str(host.host_mode.value or ""),
    )
