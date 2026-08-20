# E1G-GPT-BRIDGE-1 预注册(GPT 镜像桥接批,2026-08-20)

**状态:DRAFT——冻结前置 = DQ-GPT-SHIM-1 四道机械门(G6g/G6bg/G7/K1)
全绿。** 前置满足后以"冻结转录"提交翻牌 FROZEN(判据本文一字不改,只在
文首标注冻结时刻与前置证据指针);开跑后判据一字不改。

授权链:用户 2026-08-20"为我适配和测试GPT性能"。

## 1. 批名与代际

- 批名:`E1G-GPT-BRIDGE-1`
- 代际族:**B-dsh**(与 E1-DSH-MINIMAL-BRIDGE-1 同族**不同池**:上游
  协议轴不同,指纹第 10 键分池;两批只作定性对照叙述,永不合池检验)
- 臂:
  - **H0**:mini-swe 环 × gpt-5.5(openai-compatible 通道,
    `backend_id=mini-swe`)
  - **H1**:封存 DSH minimal runtime × dsh_gpt_shim × gpt-5.5
    (`backend_id=dsh`,组合指纹十键含
    `upstream_protocol=openai-compatible+dsh_gpt_shim`)

## 2. 研究问题(只此一问)

同一 GPT 模型(gpt-5.5)、同一任务、同一总额预算下,**把 agent 循环从
mini-swe 换成官方 DSH minimal 组合(经协议转译)**,对"能不能把这道修复
任务做绿"的机制效应是什么?

**不回答**:模型多能干(counts_toward_model_capability=false)、held-out
表现(backend 第三锁)、DSH 是否"更好用"(单任务 n=3 无统计力)、
**GPT 与 DeepSeek 谁强**(跨批不同模型不合池,只许定性对照)。

**规模决定(如实声明)**:仅 gpt-5.5 单模型。E1 有"双模型都进"先例,但
"直接跑大量 GPT"在用户 2026-08-14 暂缓单上——保守取窄;gpt-5.6 镜像批
另立预注册待用户点头。gpt-5.5 取 REPOPROOF_MODEL 缺省 = 用户配置的本地
GPT 正典名。

## 3. 任务与分类旁挂(逐发次)

- 任务:`sqlglot-8042`(**seen task**;任务包一字不动,§39)
- `test_mode=E1` · `run_purpose=MECHANISM_ABLATION` · `task_seen=true`
- `counts_toward_model_capability=false` · `counts_toward_heldout_benchmark=false`
- `counts_toward_mechanism_effect=true` · `counts_toward_treatment_effect`
  仅送达发次填

## 4. 臂间同一性

同:模型(gpt-5.5)、任务包、宿主 base commit、host prompt 文本、上游
工件与 wheelhouse、网络策略(provider API 正常通道)、总额预算(§5)、
验证器与隐藏 oracle、干净重放、计分与 Completion Gate。

**唯一自变量**:AgentBackend 运行组合(mini-swe 环 ↔ DSH minimal 组合
经 shim)。已知不可消除差异(判读边界,如实记):①H0 臂 action_protocol
按 preflight 判定(litellm 通道),H1 臂 runtime 原生 tools——"换循环 =
换执行语义"的一部分;②shim 上游走非流式合成 SSE(协议转译层本身属于
被测组合,已入指纹);③观测投影旋钮两臂皆 **off**(E0 缺省;window-v1.1
资格发另立,不混入本批)。

## 5. 等总额预算

契约:`contract-e1-total.yaml`(与 E1 逐字同一份)——四轴两臂逐字同值:
in 1.8M / out 240K / 墙 60 分 / calls 500(逃逸后备);commands 300;
patch 轴裁决面执法。`bridge_budget` 映射即代码(M88c 钉):logical 500 /
attempts 1500 / wall 3,600s。gpt-5.5 推理 token 并入 completion_tokens
(端点语义),预算轴不另设。

## 6. H1 组合冻结

DQ-GPT-SHIM-1 §2 的十键指纹逐字沿用(model=gpt-5.5)。严格最小首轮:
工具面恰 bash + str_replace_editor;无 compaction/子代理/联网/skills
(fidelity ④⑤ 执法)。指纹整份入 exec context 面哈希。

## 7. Treatment fidelity(九项 + K1)

九项判读同 E1 §7;任何缺失 → TREATMENT_NOT_DELIVERED,只读作"治疗未
送达"。**停批线:H1 送达率 < 80%**。加一道 **K1**:H1 每发 shim_requests
全部 inbound_fake_key=true,任何 false = 仪器事故停批。

## 8. 发次序(instrument 坏 = 停批,不回填)

1. **F0**:不重跑——DQ-GPT-SHIM-1-F0(同契约同 HEAD)背书;如该 F0 与
   本批开跑之间出现 src 改动,加跑一发占缺陷位。
2. **计分序(单模型,n=3/臂,共 6 发)**:序 1 H0 → 序 2 H1 →
   **fidelity 闸(序 2 必须 DELIVERED 方可续)** → 序 3 H0 → 序 4 H1 →
   序 5 H0 → 序 6 H1。
3. 任何 instrument 问题:停批 → 修 → 登记新代际 → 全序重跑,不回填。
4. **运行上限 8**(6 计分 + 2 缺陷重跑位);封套:墙钟累计 ≤5h;
   in ≤12M tok / out ≤1.6M tok;超封套中止请示。
5. 发车绊线与端点健康探同 DQ-GPT-SHIM-1 §5;窗口规则:本地端点无预告
   硬止;用户告知窗口则按 E1 规则①-④。

## 9. 批层变异面

M88a-d(既有)+ M92a/b/c(GPT 接线三枚,2026-08-20 手验全杀)。批开跑
前置:全量变异闸门在冻结 HEAD 全捕(与批首发并行,主树零触碰)。

## 10. 台账与判读边界

- H1 行:`backend_id=dsh`、runtime_profile_id 取准入组合指纹(M89a 钉)、
  dsh 回执块含 upstream_protocol + shim_requests、`cost=UNKNOWN`。
- 裁决只走隐藏 oracle + 验证器 + 干净重放 + Completion Gate。
- 结论措辞上界:单任务、seen task、n=3/臂、单模型的机制效应读数——
  不得读成"DSH 对 GPT 更好/更差"的一般结论;与 E1(deepseek)只作
  定性对照,不做任何合池统计;与 HB-PCDELTA-1 的 GPT 发次(per_round
  语义)不并池。
