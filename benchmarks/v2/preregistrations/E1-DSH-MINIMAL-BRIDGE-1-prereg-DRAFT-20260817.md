# E1-DSH-MINIMAL-BRIDGE-1 预注册(草案,未冻结)

**状态:DRAFT。** 冻结动作 = 去掉文件名与本节的 DRAFT 标记、以提交哈希留痕、
批开跑前一字不改。**冻结前置(硬)**:阶段 7 DQ-SDK 真模型 Qualification
通过(真 DEEPSEEK_API_KEY 由用户注入,AI 不经手)。本草案先把不依赖真 key
的判据与机械面钉死(2026-08-17,层 1/层 2 已落地并有钉:`dsh_bridge` +
`run_dsh_round` + M88×4)。

## 1. 批名与代际

- 批名:`E1-DSH-MINIMAL-BRIDGE-1`
- 代际族:**B-dsh**(全新族,不派生 E0/E1 的分析池;两臂**永不**与历史
  E0/E1 发次合池)
- 臂:
  - **H0**:mini-swe 环(仓内缺省 AgentBackend,`backend_id=mini-swe`)
  - **H1**:封存 DSH minimal runtime 作不可信 AgentBackend
    (`backend_id=dsh`,`runtime_profile_id=rt-dsh-minimal-0.1.0rc6-v1`,
    lifecycle=candidate)

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
- patch 轴(files/lines)在裁决面执法,天然臂中立;max_commands 是
  mini-swe 环内部机制,H1 的等价约束即请求数轴(H1 命令数如实记
  bash tool/call 计数,不写 0 冒充)。

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

1. **批前逐任务 F0 四形电池**(判据面,`--fake` 通路,不计任何臂):
   诚实正控→PASS / `control:nc_null_submission`→IMPL_INCOMPLETE /
   `control:nc_regression_break`→REGRESSION_BROKEN /
   `control:nc_instrument_tamper`→INSTRUMENT_TAMPERED
2. **H1 正形彩排**(脚本化假端点 + 真 worker 环,AR 语义不计成绩;
   层 2 已有活钉 `test_r1_run_dsh_round_end_to_end_over_fake_endpoint`)
3. 计分序:H0 n=1 金丝雀 → H1 n=1 金丝雀 → 两发 fidelity 全过 →
   H0 n=3 → H1 n=3(共 8 发)
4. 任何 instrument 问题:停批 → 修 → 登记新代际 → 全序重跑,**不回填**

## 9. 批层变异面(已入登记簿,随层 1 提交 `007a422`)

- M88a = M-DSH-13:backend 第三锁死(DSH 发次混进能力池)
- M88b = M-DSH-14:组合指纹掉字段
- M88c = M-DSH-15:两臂预算不等(分钟当秒)
- M88d = M-DSH-16:fidelity 判读死(未送达读作无差异)

四枚手验"杀死,凶手正确";批开跑前置:全量变异闸门在冻结 HEAD 全捕。

## 10. 台账与判读边界

- H1 行:`backend_id=dsh`、`runtime_profile_id=rt-dsh-minimal-0.1.0rc6-v1`、
  `dsh` 回执块(逐轮归因/会话/用量/fidelity)、`cost=UNKNOWN`(无费率
  读数不写 0)
- `final_response`/`finish_reason`/会话 JSONL 永不产生 PASS —— 裁决只走
  隐藏 oracle + 验证器 + 干净重放 + Completion Gate(ADR 既定)
- candidate 只证机制站得住,**不代表真实模型可用**(真可用 = 阶段 7
  qualified 之后的事);本批结论措辞不得越过这条线
