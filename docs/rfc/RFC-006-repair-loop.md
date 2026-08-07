# RFC-006: Guided Repair Loop(Phase 6)
产品模式,非 Benchmark(Benchmark=单次不变)。repair/ 三模块:
repair_budget{max_rounds=3,max_tokens,max_commands,max_diff_lines};
failure_packet: 测试输出 -> FailurePacket{type/summary/affected_files/
expected/actual/suggestion/owner},类型∈{DEPENDENCY_ERROR,API_MISMATCH,
SCHEMA_ERROR,TEST_FAILURE,REGRESSION_FAILURE,RESOURCE_MISSING,
SCOPE_EXCEEDED,UNKNOWN},禁止透传原始 pytest 日志行;
repair_loop: RepairLoop(run_round 可注入)——每轮 checkpoint(adapter/
diff/test_result)、best-state 追踪、劣化 rollback、连续 2 轮无改善
stagnation 停机、scope_change_request 即暂停待用户(新增大依赖/改
核心架构/访问网络/改成功标准)、预算耗尽停机。产出 RepairOutcome
{rounds,best_round,stop_reason,...}——无 verdict 字段:循环永不宣布
成功,all-pass 也只是 completed_all_pass,最终必须走既有 Freeze→
Capability→Regression→Policy→Clean Replay→Completion Gate。
仍单 Agent:多轮=同一 DefaultAgent 顺序调用;真实模型多轮运行属
未来预注册 gate,本阶段交付机制+注入式测试(复用 fake 驱动)。
测试:三轮限/ checkpoint/rollback/stagnation/scope gate/budget/
不宣布成功/packet 无原始日志。
