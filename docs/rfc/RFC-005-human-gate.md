# RFC-005: Human Confirmation Gate(Phase 5)
planning/human_gate.py。confirm_plan(plan, admission, answers, ack,
now) -> FrozenAdoptionIntent{plan_sha/admission_sha/answers/ack/
confirmed_at}(canonical-json sha 绑定,冻结后改 plan 即失配)。
前置:admission.status==READY 且 plan.questions 全部有答案,否则
HumanGateError。require_confirmed(intent) 是未来 TaskPackage/Agent
启动的强制入口——None 或 sha 失配即拒绝。"用户未确认时启动 Agent"
在结构上不可能。测试:未确认禁止执行/未答问题拒绝/非 READY 拒绝/
冻结后篡改检测/roundtrip。
