"""Human Confirmation Gate(RFC-005)。

Plan 生成后必须暂停;用户确认 → FrozenAdoptionIntent(sha 绑定计划
与准入报告)。`require_confirmed` 是后续 TaskPackage 创建 / Agent
启动的强制入口:未确认或内容被改动,结构上无法继续。
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict

from repoproof.adoption.admission.admission_report import READY, RISK_REVIEW, AdmissionReport
from repoproof.adoption.planning.adoption_plan import AdoptionPlan
from repoproof.adoption.planning.plan_validator import require_answers, validate_plan

ACK_TEXT = "我确认当前成功标准代表实际业务目标;开始后 AI 只能修改解决方案,不能修改合同和评分规则。"


class HumanGateError(RuntimeError):
    pass


class FrozenAdoptionIntent(BaseModel):
    model_config = ConfigDict(frozen=True)  # F7: 冻结产物本身不可变

    plan_sha256: str
    accepted_risks: list[str] = []
    admission_sha256: str
    answers: dict[str, str]
    user_ack: str
    confirmed_at: str

    def to_dict(self) -> dict:
        return self.model_dump()


def _sha(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def confirm_plan(
    plan: AdoptionPlan,
    admission: AdmissionReport,
    *,
    answers: dict[str, str],
    user_ack: str,
    confirmed_at: str,
    accepted_risks: list[str] | None = None,
) -> FrozenAdoptionIntent:
    """用户确认动作。所有前置不满足都抛 HumanGateError——不静默放行。
    RISK_REVIEW 状态要求 accepted_risks 覆盖全部风险(F1)。"""
    if admission.status == RISK_REVIEW:
        missing = [r for r in admission.risks if r not in (accepted_risks or [])]
        if missing:
            raise HumanGateError(f"以下风险未被接受,禁止确认:{missing}")
    elif admission.status != READY:
        raise HumanGateError(f"适用性检查状态为 {admission.status},不是 READY,禁止确认")
    gaps = validate_plan(plan)
    if gaps:
        raise HumanGateError(f"计划不完整,禁止确认:{gaps}")
    try:
        require_answers(plan, answers)
    except Exception as exc:
        raise HumanGateError(f"问题未回答,不能确认:{exc}") from exc
    if user_ack.strip() != ACK_TEXT:
        raise HumanGateError("确认语与要求不一致——必须逐字确认成功标准声明")
    return FrozenAdoptionIntent(
        accepted_risks=list(accepted_risks or []),
        plan_sha256=_sha(plan.to_dict()),
        admission_sha256=_sha(admission.to_dict()),
        answers=dict(answers),
        user_ack=user_ack.strip(),
        confirmed_at=confirmed_at,
    )


def require_confirmed(
    intent: FrozenAdoptionIntent | None,
    plan: AdoptionPlan,
    admission: AdmissionReport,
) -> None:
    """TaskPackage 创建 / Agent 启动前的强制门。

    未确认(None)→ 拒绝;确认后计划或准入报告被改动(sha 失配)→
    拒绝。「用户未确认时启动 Agent」由此在结构上不可能。"""
    if intent is None:
        raise HumanGateError("用户尚未确认采用计划,禁止创建任务包或启动 AI")
    if intent.plan_sha256 != _sha(plan.to_dict()):
        raise HumanGateError("计划在确认后被修改(sha 失配)——请重新走确认流程")
    if intent.admission_sha256 != _sha(admission.to_dict()):
        raise HumanGateError("适用性报告在确认后被修改(sha 失配)——请重新走确认流程")
