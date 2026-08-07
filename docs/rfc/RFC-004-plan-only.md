# RFC-004: Intent Parser + Plan-only Mode(Phase 4)
确定性规则实现(无 LLM——LLM 辅助解析留作后续增强,不伪装)。
intent_parser: 自然语言 -> IntentDraft{goal/capability/expected_io/
constraints/unknowns + Confirmed(原文命中)/Assumption(规则推断)/
Question(固定+派生)};禁止直接产合同——无法确认的一律进 Question。
requirement_extractor: draft+分析报告 -> DRAFT requirement 种子
(owner 预分配:输入校验→HOST_INPUT_GUARD,其余→ADAPTER),不冻结。
adoption_plan: build_plan(intent,host,repo,admission) 模板化组装
§七 schema{goal/understanding/integration_strategy/estimated_changes/
success_criteria/risks/questions}+方案 A(直接调用上游)/B(wrapper)
+recommended+理由;strategy_selector 按 capability_candidates 与宿主
集成点选择;plan_validator: 完整性校验+questions 未答不得进入确认。
Plan-only 铁律:模块禁 shell/write/docker/git(静态测试);只读元数据。
测试:只读、不执行工具、UNKNOWN 传播、问题必出。
