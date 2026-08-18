# E1-DSH-MINIMAL-BRIDGE-1 预注册(冻结,2026-08-18)

**状态:FROZEN(2026-08-18 12:3x,冻结点 = 本文件所在提交)。** 开跑后判据
一字不改。冻结前置已满足:阶段 7 DQ-SDK-1 通过,
`rt-dsh-minimal-0.1.0rc6-v1` **qualified**(0396153:G6=2 模型 + G6b=1
诚实通过 + G7 清);注入纪律 = 用户授权的 `source .env` 前缀(值不进
上下文,DQ 附录一)。层 1/层 2 机械面钉齐:`dsh_bridge` + `run_dsh_round`
+ M88×4 + M89a。

**API 窗口规则(冻结时预登记,不是事后挪门)**:用户告知 DeepSeek 通道
**14:00 硬止**。①不启动"预计墙钟(同型同臂观测峰值 + 5 分)越过 14:00"
的发次;②窗口关闭即暂停,判据 / 发次序 / 预算零改动,窗口重开按序续跑;
③暂停期间只做零 API 工作(收口文书、门、台账);④在途发次不得跨窗启动。
观测峰值基线:H0(mini-swe)16.3 分、H1×pro 31.3 分、H1×flash 23.7 分。

## 1. 批名与代际

- 批名:`E1-DSH-MINIMAL-BRIDGE-1`
- 代际族:**B-dsh**(全新族,不派生 E0/E1 的分析池;两臂**永不**与历史
  E0/E1 发次合池)
- 臂:
  - **H0**:mini-swe 环(仓内缺省 AgentBackend,`backend_id=mini-swe`)
  - **H1**:封存 DSH minimal runtime 作不可信 AgentBackend
    (`backend_id=dsh`,`runtime_profile_id=rt-dsh-minimal-0.1.0rc6-v1`,
    lifecycle=**qualified**,0396153)

## 2. 研究问题(只此一问)

同一模型、同一任务、同一总额预算下,**把 agent 循环从 mini-swe 换成官方
DSH minimal 组合**,对"能不能把这道修复任务做绿"的机制效应是什么?

**不回答**:模型多能干(counts_toward_model_capability=false)、held-out
表现(backend 第三锁在 `bench_records.classify_runs`,分类旁挂自述不能
自证)、DSH 是否"更好用"(单任务 n=3 没有这个统计力)。

## 3. 任务与分类旁挂(逐发次)

- 任务:`sqlglot-8042`(**seen task**;与 HB-DSENTRY-1 同宿主同 base commit)
- `test_mode=E1` · `run_purpose=MECHANISM_ABLATION` · `task_seen=true`
- `counts_toward_model_capability=false` · `counts_toward_heldout_benchmark=false`
- `counts_toward_mechanism_effect=true` · `counts_toward_treatment_effect`
  仅送达发次填(见 §7)

## 4. 臂间同一性(相同项清单)

同:模型 profile(**用户 2026-08-18 定:双模型都进** —— deepseek-v4-pro
与 deepseek-v4-flash 各跑满 n,两模型内部两臂对照,模型是分层因子不是
自变量;两名均在 DQ-SDK-1 达成 qualified 的同一封存组合上跑过真发次)、
任务包(一字不动)、宿主 base commit、提示知识面
(同一份 host prompt 文本)、上游工件与 wheelhouse、网络策略(provider API
为正常通道)、**总额预算**(§5)、验证器与隐藏 oracle、干净重放、计分与
Completion Gate。

**唯一自变量**:AgentBackend 运行组合(mini-swe 环 ↔ DSH minimal 组合)。

## 5. 等总额预算(映射即代码:`dsh_bridge.bridge_budget`,M88c 钉)

| 轴 | H0(HostBudgets) | H1(DshBudget) |
|---|---|---|
| 模型调用 | max_model_calls | max_logical_requests(周期计数,E5) |
| 输入 tokens | max_input_tokens_total | max_input_tokens |
| 输出 tokens | max_output_tokens_total | max_output_tokens |
| 墙钟 | max_wall_time_minutes | max_wall_seconds = 分 × 60 |
| 物理尝试 | —(litellm 内部重试) | max_llm_attempts = logical × 3(C8 实测:500 恰 2 重试) |

- 只接受 `semantics="total"`;per_round 在准入即拒(等总额无从定义)。
- patch 轴(files/lines)在裁决面执法,天然臂中立;H1 命令数如实记
  bash tool/call 计数,不写 0 冒充。
- **契约:`contract-e1-total.yaml`(task_version=v1-e1-total)**,与
  DQ 的 v1-dsh-total 唯一差异 = **max_model_calls 90→500,两臂同值**。
  依据(DQ-SDK-1 附录五实证):四次真跑逐发 91 撞 90 上限(含 PASS 发),
  彼时 token 信封仅用 3-4% —— 90 来自 mini-swe 的机制常数(30/轮×3),
  把它当资源上限强加给请求重 / token 轻的 DSH 臂,恰是臂中立的反面。
  500 > 墙钟可及的 ~180-240 请求,calls 轴退为**两臂同值的逃逸后备**,
  运营约束回到真正的资源轴:in 1.8M / out 240K / 墙 60 分 / commands 300
  ——四轴两臂逐字同值。跑飞保护仍在(attempts=logical×3)。**不回头改
  DQ 批判据**(附录五原话),这是 E1 自己的冻结决定。

## 6. H1 组合冻结(`dsh_bridge.composition_fingerprint`,M88b 钉)

- 封存 runtime:`rt-dsh-minimal-0.1.0rc6-v1`(SDK 0.1.0rc6 /
  runtime-bin 0.1.0rc6 / cordis 上游钉 commit 47f94385…,现物 sha256
  与封存清单比对,不符拒跑)
- 组合三缺省(逐字):
  - system prompt:`You are a helpful software engineer assistant.`
  - maxTokens:`256000`
  - reasoningEffort:`high`(SDK 0.1.0rc6 内部缺省;我们的配置面设不了
    它,声明进指纹的意义是换 SDK 版本必换 sdk_version,批不可混)
- 严格最小首轮:工具面**恰** bash + str_replace_editor;无 compaction /
  子代理 / 联网工具 / skills(fidelity ④⑤ 执法)
- 指纹整份入 exec context 面哈希(`_exec_profile_fields(backend="dsh")`)

## 7. Treatment fidelity(九项,§17.3;`treatment_fidelity`,M88d 钉)

①backend 身份 ②封存版本 ③组合一致 ④工具面白名单 ⑤无扩展面
⑥runtime 事件存在 ⑦会话唯一 ⑧预算生效 ⑨workspace 出处。

- 任何一项缺失 → 该发次 `TREATMENT_NOT_DELIVERED`,**只能读作"治疗未
  送达",不得读作 H0/H1 无差异**;仅送达发次进臂间比较。
- **停批线:H1 送达率 < 80% 即停批**,修 instrument,新代际重跑,不回填。

## 8. 发次序(instrument 坏 = 停批,不回填)

1. **F0(收窄声明,零 API)**:fake-positive 一发过 E1 契约全链
   (batch=E1-DSH-MINIMAL-BRIDGE-1-F0)。四形负控不重跑:同判据面四形
   已于 2026-08-17 全量证过 + DQ-SDK-1 对 total 语义变体重证过正形,
   本变体与 v1-dsh-total 的差异只有一个整数字段;负控形与 calls 上限
   无交互。附:`bridge_budget(E1 契约)` 机械核映射数(附录一)。
2. **H1 彩排(收窄声明,零 API)**:full-runner × dsh 集成已由 DQ-SDK-1
   发 3/发 4 在**同一 HEAD 代码**(313f9a6,其后零 src 改动)× 同任务
   × 真端点全链产线证过(含 PASS + replay);round 级活钉
   `test_r1_run_dsh_round_end_to_end_over_fake_endpoint` 在全量套件常驻。
   独立 full-runner×fake-endpoint 常驻钉**批后补**(登记为欠账,不挡本批)。
3. **计分序(双模型,n=3/臂/模型,金丝雀计入 n,共 12 发)**:
   序 1 H0×pro → 序 2 H1×pro → **pro 对 fidelity 闸** → 序 3 H0×flash →
   序 4 H1×flash → **flash 对 fidelity 闸** → 序 5-12 = 每模型每臂再 2 发
   (顺序 H0×pro ×2 → H1×pro ×2 → H0×flash ×2 → H1×flash ×2,窗口规则
   优先于顺序:预计越窗的发次跳过等窗,不改判据)。
4. 任何 instrument 问题:停批 → 修 → 登记新代际 → 全序重跑,**不回填**
5. **运行上限 16**(12 计分 + 4 缺陷重跑位);成本封套:in ≤14M tok /
   out ≤1.5M tok / API 墙钟累计 ≤7h;超封套中止请示。

## 9. 批层变异面(已入登记簿,随层 1 提交 `007a422`)

- M88a = M-DSH-13:backend 第三锁死(DSH 发次混进能力池)
- M88b = M-DSH-14:组合指纹掉字段
- M88c = M-DSH-15:两臂预算不等(分钟当秒)
- M88d = M-DSH-16:fidelity 判读死(未送达读作无差异)

四枚手验"杀死,凶手正确";批开跑前置:全量变异闸门在冻结 HEAD 全捕
(与批首发次**并行**跑 —— 门在临时 worktree(HEAD)施变、PYTHONPATH
压 editable、主树零触碰,隔离性为设计保证 + DQ 附录四实录;若未全捕,
当场停批修复)。最近全捕基线:257/257 @ 313f9a6,其后 src 唯二改动 =
bench_records 登记集加一常量 + profile lifecycle 翻牌,均不在任何变异
体靶行上。

## 10. 台账与判读边界

- H1 行:`backend_id=dsh`、`runtime_profile_id=rt-dsh-minimal-0.1.0rc6-v1`、
  `dsh` 回执块(逐轮归因/会话/用量/fidelity)、`cost=UNKNOWN`(无费率
  读数不写 0)
- `final_response`/`finish_reason`/会话 JSONL 永不产生 PASS —— 裁决只走
  隐藏 oracle + 验证器 + 干净重放 + Completion Gate(ADR 既定)
- qualified 只证真模型全链诚实跑通且一发真过(DQ-SDK-1 划界 §8),
  **不是能力主张**;本批结论措辞的上界:单任务、seen task、n=3/臂/模型
  的机制效应读数,不得读成"DSH 更好/更差"的一般结论

## 附录一(冻结时工程留痕,2026-08-18)

1. **preflight 双探活(12:31,冻结前)**:deepseek-v4-pro
   PROVIDER_READY(378/53,1.6s);deepseek-v4-flash PROVIDER_READY
   (378/60,1.1s)。
2. **DS 旋钮**:两臂 `REPOPROOF_DS_PROFILE=DS-NATIVE-HIGH-DET`。H0 臂
   旋钮生效(temp 0 / top_p unset / effort high / tool_loop);H1 臂
   旋钮惰性(DQ 预注册 §2 如实声明,有效组合 = composition_fingerprint
   九键)。这是臂间已知的不可消除差异,属"换循环 = 换执行语义"的一部分,
   记入判读边界。
3. **bridge_budget 机械核**(冻结时现场):E1 契约 → logical_requests
   500 / attempts 1500 / in 1,800,000 / out 240,000 / wall 3,600s。
