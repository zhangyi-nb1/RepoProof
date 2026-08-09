# T1 停点报告(源 §48 清单,2026-08-10)

1. **Task**: `t1-offerclaw-fastapi-mcp-v1`(task_shape 10/16,真实工程集成档)
2. **Host**: OfferClaw @ `8e59a18f`(副本;主目录护栏+指纹对账全程有效)
3. **Target**: fastapi_mcp @ `e5cad13c`
4. **TaskPackage**: `benchmarks/v2/tasks/t1_fastapi_mcp/`(冻结于 ba0252b,内容全程未改)
5. **Positive Control**: 公开 8/8 + 隐藏 9/9 + 回归 591(冻结前实证可满足)
6. **Negative Controls**: NC1→H5 / NC2→H1+H1b / NC3→H3 / NC4→H2 逐一按预期挂
7. **Direct Baseline**: 公开 4/8、隐藏 3/9(起点非零、远未达标)
8. **Model Run Summary**(真实 6 发全入账,fake 冒烟 4 发另账):

| # | model | verdict | 轮 | 调用 | 读入 | 墙钟 | harness | 备注 |
|---|---|---|---|---|---|---|---|---|
| 1 | deepseek-v4-pro | FAIL | 3 | 20 | 379k | 367s | ce70f23 | v1 总额语义:R1 烧穿,未自测即提交,净破坏(2/8·1/9) |
| 2 | deepseek-v4-pro | FAIL | 2 | 51 | 1050k | 1676s | 65ab6f7 | R2 修通 8/8+9/9+依赖声明,峰值 538k>500k 政策线(执法内移前) |
| 3 | deepseek-v4-pro | FAIL | 3 | 54 | 1407k | 1195s | 15b19db | R1 只装库 5/8*;R2/R3 脚手架被"同分取小 diff"误滚(修订②前) |
| 4 | gpt-5.5 | READY_FOR_REPLAY | 2 | 50 | 924k | 480s | 15b19db | 三绿 9/9,replay 被"耗尽即跳过"拦截(修订③前) |
| 5 | gpt-5.5 | **PASS_ADAPTED** | 2 | 34 | 705k | 556s | e5aa857 | R1 7/8→R2 8/8,干净提交,replay PASS |
| 6 | gpt-5.6 | **PASS_ADAPTED** | 1 | 19 | 451k | 718s | 3a81bff | 一轮通,含自写宿主测试(回归 595),replay PASS |

\* 5/8 含 real_upstream 公开测试字符串匹配瑕疵(+1,判定不受影响,见 20)

9. **Round Timeline**: 各 run `repair/round-N/record.json`(公开/回归/diff/packets/tokens 逐轮)
10. **FailurePacket**: 全部由 junit 结构化生成;run2/5 实证 packets 驱动第二轮修通
11. **Best State**: host_score(修订②后无 diff 项)+ 硬信号真退步恢复
12. **Rollback Events**: run3 误滚 2 次(修订②动因);修订后未再发生
13. **Scope Change**: 0
14. **Capability**: 2 个 PASS 运行 oracle 9/9(H1-H8 含结构性反伪:实例化 spy/schema 对 OpenAPI/冻结 legacy 集)
15. **Host Regression**: 全部 run 全轮 ≥591(592 常态;run6 595 含 agent 自写 3 测试)
16. **Policy**: run2 峰值超限一次(FAIL 判据);其余全绿;0 策略拒绝;三树(oracle/upstream/public_tests)全程未被篡改
17. **Replay**: 2 次 clean_adoption 全 PASS(全新会话+从声明依赖重建环境+结果逐项一致)
18. **Token/Cost/Wall**: 见表;cost=UNKNOWN(代理无计价);两 PASS 合计 ~1.16M 读入
19. **新发现 Failure**: 单轮峰值越线(执法粒度)/脚手架误滚(评分水土不服)/replay 准入残留 v1 语义——三者均为 harness 层,已修
20. **Harness 增强判定**: 四项修订(每轮额度/执法内移 50k/真退步才恢复/replay 三绿准入)全部由 ≥1 真实 run 证据驱动、经用户确认、预注册修订记录在案、测试钉死;任务包缺陷 1 项(real_upstream 字符串匹配)入 task-v2 候选,不改 v1
21. **增强触发条件**: 满足(真实失败驱动,非预制;附录 C 原则)
22. **Feature Transaction**: 未启用(T4 范畴)
23. **Rollback Readiness**: N/A(EXPORT_ONLY 阶段,未写回任何真实目录)
24. **Evidence Bundle**: 各 runs/<id>/(trace 链验证通过;PASS 运行 integrity ok)
25. **Verdict 汇总**: T1 完成校准使命——难度真实(直连 3/9、6 发中 3 败)、可解(两模型 PASS 含重放)、失败可解释(每败一因,见台账)

## 结论边界(源 §49 纪律)

- 有效声称:两个 PASS 为**经七道独立关卡验证的真实能力交付**;失败全部可解释且被正确拒绝放行;False System Pass=0、oracle 零泄漏、未批准写回=0;
- 不声称:模型排名(n<3)、成功率、跨 harness_commit 可比(演进期各 run 按其 commit 留档)、异机复现(L 级=machine-reproducible;对外声称须 D 级复验或如实标注)。

## 增补(2026-08-10):deepseek 第 4 发(终版 harness 检验)

| # | model | verdict | 轮 | 调用 | 读入 | 墙钟 | harness | 备注 |
|---|---|---|---|---|---|---|---|---|
| 7 | deepseek-v4-pro | FAIL | 3 | 80 | 1347k | 833s | bd56823 | 单调推进 5→5→7,oracle 7/9(其最佳冻结态),零回滚;败于轮次用尽+终步 API 误用+未声明依赖 |

修订②④生效实证:零回滚、三轮满油、调用 54→80/命令 102→131(单位
产出提升),进度首次单调。终局差距:mount_http(router=app,…) 误用
(正确签名不带 router)致 h1 暴露泄漏+h7 不可调用;requirements 全程
未声明(0 提及,潜在 replay 死因,四发中第 2 次)。**本发 harness 零
新缺陷——差异归属模型**;不再为其改动(加轮次违 §31 且稀释任务区分
度)。deepseek 四发画像完备:能力在(run2 曾达 8/8+9/9),但预算饱和
型消费+工程习惯不稳定+组件先行集成后置,使其在"3 轮×500k"冻结盒
内不稳定转化。指纹第 3 次告警=用户 00:40/01:10 两次主目录提交(判定
同前:用户自改,run 有效;用户通宵与跑分并行开发,T2 起按"如实标注"
处理该噪声,机制不改)。
