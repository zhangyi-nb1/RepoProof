# 预注册:首次真实模型 GUIDED_ADOPTION 多轮修复运行(Gate D)

> 状态:已预注册,**尚未执行**。按 RFC-008 §十六,真实模型 Guided
> Repair 运行前必须存在本预注册;执行由用户在 UI 亲手触发(与
> thefuzz 首跑同一惯例:agent 首跑留给用户),或用户明确授权后由
> 协作 AI 触发。

## 固定项(执行时不得变更)

| 项 | 值 |
|---|---|
| 模式 | GUIDED_ADOPTION(`repoproof guided-run`);产品模式,不入 benchmark,不触历史 evidence |
| 任务 | 用户选择的**已冻结**任务(contracts/*.package.json 存在;建议非 benchmark 任务) |
| 轮数上限 | 3(`--max-rounds 3` 默认) |
| 每轮反馈 | 仅 FailurePacket(公开合同测试;类型化摘要,无原始日志)——held-out 名/隐藏 fixture/oracle 参考输出/gate 答案零泄漏(tests/test_gated_guided_repair.py 钉死) |
| Best State | §11.3 字典序:收集成功 > 无策略违规 > 回归未破坏 > 通过数 > 预算内 > 更小 diff(full_score,测试钉死) |
| 劣化处理 | 真实恢复最佳快照后再开下一轮(restore_adaptation,测试钉死) |
| 停机 | 全绿(仅 pending_verification)/ 连续 2 轮无改善 / 预算尽 / 3 轮 / SCOPE_CHANGE_PENDING_USER |
| 终局 | 恢复最佳 → Freeze → 隐藏验证 → clean replay → Completion Gate;循环永不宣布成功 |
| 预算 | 合同预算不变(token 全局硬墙跨轮累计;命令预算 ×轮数;steps 为每轮上限) |
| 温度/协议 | 跟随 ProviderAdmissionGate 预检结果(temp 0 优先) |
| 运行次数 | 单次;失败不重跑、不人工补代码;结果如实入 runs/ 与停点报告 |

## 预期观察(不构成成功承诺)

- 若首轮公开样例未全过,第 2/3 轮应表现出「按 FailurePacket 修复」
  的行为差异(与单次模式对照的素材);
- 任一轮出现越权请求 → SCOPE_CHANGE_PENDING_USER 停点(report.json
  state 字段),UI 呈现待决请求;
- 多轮全绿 ≠ PASS:最终判定仍可能因 held-out/回归/策略/重放挂掉——
  该结果同样有效且必须如实记录。

## Fake-model E2E(真实模型前的机制彩排)

`REPOPROOF_RUN_GUIDED_E2E=1 .venv/bin/pytest tests/ -k guided_e2e`
(默认跳过:E2E 会在 runs/ 下创建任务运行目录,与用户正在进行的
实时会话共用视图,须在空闲时执行。)脚本化 FakeModel:第 1 轮写
空适配(公开 0/N)→ 第 2 轮写公开样例硬编码映射(公开全绿)→
终局隐藏验证应在 held-out 上拒绝——同时证明循环机制与防作弊。
