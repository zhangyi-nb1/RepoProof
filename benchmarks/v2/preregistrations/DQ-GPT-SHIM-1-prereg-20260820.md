# DQ-GPT-SHIM-1 预注册:GPT×DSH 组合资格批(2026-08-20)

**测试模式:DQ(backend 组合资格)。** 考察对象是 **GPT×DSH 组合**——封存
runtime `rt-dsh-minimal-0.1.0rc6-v1`(已 qualified,但其 qualified 只背书
deepseek 直连组合)× `dsh_gpt_shim` 回环协议转译 × 本地 GPT 端点
(openai-compatible)——**这套组合真模型跑不跑得动、跑得诚不诚实**,不是
模型能力。发次入 `runs.jsonl`,分类旁挂四口径全 false。冻结点 = 本文件
所在提交;开跑后判据一字不改。

授权链:用户 2026-08-20"为我适配和测试GPT性能"(适配 = host-run 接线,
本提交落地;测试 = 本资格批 + 后续 E1G 镜像批)。

## 1. 对象与判据(机械,零人工格)

对象:组合指纹十键(`composition_fingerprint`,upstream_protocol =
`openai-compatible+dsh_gpt_shim`)。**无 profile promotion 目标实体**——
profile lifecycle 不动(qualified 归 deepseek 组合);本批资格以批报判读
四道机械门为准,通过 = E1G-GPT-BRIDGE-1(DRAFT)获准冻结:

- **G6g**:台账上本组合 ≥2 个不同真实 GPT model(`gpt-5.5` / `gpt-5.6`,
  两名均为端点恢复核实 GET /models 实录,2026-08-20),每发
  attribution=ok 且 fidelity **DELIVERED**(九项全绿);
- **G6bg**:≥1 发 verdict PASS* 且未被裁决作废(诚实通过全链,含干净重放);
- **G7**:无未决 INVALIDATED_FALSE_PASS;
- **K1(key 纪律)**:每发逐轮回执 `shim_requests` 全部
  `inbound_fake_key=true`——真 key 未进不可信 worker 的布尔见证
  (M92b 面);任何一条 false = 仪器事故,停批。

任一不过 → 组合停在未资格,E1G 预注册维持 DRAFT,不加发凑门、不换判据。

## 2. 通道与组合(有效面即指纹)

- 通道:openai-compatible(REPOPROOF_API_BASE/KEY/MODEL 环境注入;**不设**
  REPOPROOF_PROVIDER)× `--backend dsh`。准入:`upstream_protocol_for_provider`
  单源判定 → shim 协议;bridge_budget fail-fast;cordis 现物复核。
- 接线(本提交落地,GS3 全栈钉常驻):`run_dsh_round` 轮内起
  `DshGptShim`——runtime 只见回环 base + `RUNTIME_FAKE_KEY` 假字面量;
  真 key 只在 host 进程内进 shim 构造参数;shim 记录只存形状 + 入站见证。
- 组合指纹冻结值(十键):runtime `rt-dsh-minimal-0.1.0rc6-v1` /
  sdk 0.1.0rc6 / runtime_bin 0.1.0rc6 / cordis 现物 sha(不符拒跑)/
  model 逐发(gpt-5.5|gpt-5.6)/ system prompt
  `You are a helpful software engineer assistant.` / maxTokens 256000 /
  reasoningEffort high(SDK 内部缺省,声明语义同 DQ-SDK-1 §2)/
  **upstream_protocol `openai-compatible+dsh_gpt_shim`**。
- 惰性旋钮如实声明:openai 通道无 DS_PROFILE;temperature/top_p 是 SDK
  内部值,设不进;REPOPROOF_CALL_TIMEOUT_S 缺省 300s,shim 上游超时 =
  单请求 +60s(代码内常数)。gpt-5.5/5.6 为推理模型:端点 usage 的
  reasoning 明细并入 completion_tokens(shim 三键投影),预算轴不另设。

## 3. 任务与已见声明

- 任务:`hb1-sqlglot-8042`(**seen**;可解性有据:HB-PCDELTA-1 2026-08-16
  gpt-5.5 / gpt-5.6 各 1 发 PASS_ADAPTED——彼时 per_round 语义 mini-swe 臂,
  仅作可解性依据,**不与本批并池**)。
- 分类旁挂(预写,批结束机械转录):test_mode=DQ、
  run_purpose=BACKEND_QUALIFICATION、task_seen=true、
  assistance_level=BOUNDED_PUBLIC_REPAIR、host_modification_mode=PRISTINE、
  oracle_authorship=UPSTREAM_OWN_TEST_SUITE、treatment_assigned=false、
  counts_toward_{model_capability, heldout_benchmark, mechanism_effect,
  treatment_effect} **全 false**。

## 4. 预算(与 E1 同契约,不另立)

契约:`contract-e1-total.yaml`(task_version=v1-e1-total,total 语义)——
calls 500 / commands 300 / in 1.8M / out 240K / 墙 60 分 / patch 轴原值。
`bridge_budget` 等总额映射(logical 500 / attempts 1500 / in 1,800,000 /
out 240,000 / wall 3,600s)。选它的理由:E1G 镜像批(§DRAFT)将用同一
契约,资格批与计分批组合同一,资格才背书得上。

## 5. 发次序与上限(防事后挪门槛)

计划 3 发,**运行上限 5**(含缺陷重跑):

1. 8042 × `gpt-5.5` × dsh——机械面确认(逐轮归因/工具调用/usage 对账/
   shim 形状与 K1)+ 通过尝试;
2. 8042 × `gpt-5.6` × dsh——G6g 第二 model + 通过尝试;
3. 仅当 1-2 均无 PASS:8042 × `gpt-5.5` × dsh 最后尝试一发。

全序跑完仍无诚实 PASS → 资格如实 FAIL:证据入库,E1G 不冻结。

- **fidelity 前置**:每发九项判读;TREATMENT_NOT_DELIVERED 不满足 G6g。
- **停规**:harness/instrument 缺陷 → 停修(钉死+附录留痕)→ 该发从零
  重跑;不回填、不带伤计数。
- **发车绊线(每发前后各一道)**:`scripts/check_host_digest.py`
  (摘要+锁态双面执法);发前红拒发,发后红唯一归因刚结束那发。
- **端点健康探(发车前)**:GET /models 200 且目标模型在列;失败即暂停
  (判据/发次序/预算零改动),端点恢复按序续跑。本地端点无预告硬止窗口;
  若用户告知窗口,按 E1 窗口规则①-④执行。

## 6. F0 与彩排面(声明)

- **F0(零 API)**:fake-positive 一发过 E1 契约全链
  (batch=DQ-GPT-SHIM-1-F0)——接线改动后重证管线;四形负控不重跑
  (判据面无变,与接线正交;同 E1 §8 收窄声明)。
- **彩排(零 API,套件常驻)**:GS3 = 模块级 run_dsh_round × 封存 runtime
  × shim × 假 openai 上游(job.model=gpt-5.5 走通、指纹换脸、K1 见证、
  fidelity 全绿);GS1/GS2 全栈;在线探针 line-probe-20260820 六 checks
  全过(仪器适配测试,不计模型表现)。
- **批开跑前置**:全量变异闸门在冻结 HEAD 全捕(与批首发次并行跑,
  门在临时 worktree 施变、主树零触碰;未全捕当场停批)。新增 M92a/b/c
  三枚均已手验"杀死、凶手正确"(2026-08-20)。

## 7. 封套与判读边界

- 成本封套:运行 ≤5;墙钟累计 ≤3h;in ≤6M tok / out ≤1M tok(本地端点
  无货币成本,token 照记);超封套中止请示。
- cost 列恒 "UNKNOWN"(DSH 无费率读数;本地端点同理,不写 0 冒充)。
- 判读上界:资格不是能力主张;单任务、seen、n=1/模型——**不得读作
  "GPT×DSH 好/坏"**,也不得与 deepseek 组合(DQ-SDK-1 / E1)合池比较。
- `final_response`/`finish_reason`/会话 JSONL 永不产生 PASS;裁决只走
  隐藏 oracle + 验证器 + 干净重放 + Completion Gate(ADR 既定)。

## 附录一(冻结时工程留痕,2026-08-20)

1. **preflight 双探活(冻结前,base 恒脱敏)**:gpt-5.5 PROVIDER_READY
   (70/21,4.8s,action_protocol=native,temperature=0);gpt-5.6
   PROVIDER_READY(70/21,2.9s,同上)。preflight 属通道准入,发次不入
   台账。注:preflight 的 native/temp 判定作用于 H0(mini-swe)臂;本批
   dsh 臂 agent 环在 runtime 内,该判定惰性(有效组合以指纹十键为准)。
2. **GS3 全栈钉实证(2026-08-20,零 API)**:封存 runtime 接受
   job.model=gpt-5.5(非 deepseek 名)全程走通到线上 model_in;指纹换脸、
   K1 见证、fidelity 九项全绿——host-run 接线的离线彩排。
3. **变异体手验**:M92a/b/c 逐一施变 → 声明凶手当场红 → 还原复绿
   (M92b 首轮手验因还原脚本误用 git checkout 冲掉未提交接线,已按
   逆向替换重做三枚,结果不受染)。

## 附录二(2026-08-20 · 批毕机械转录:资格 FAIL,批关闭)

### 执行留痕

- 批开跑前置:全量变异门 **265/265 全捕**(证据 7b5bc93cec42.json,
  d3d2b27 提交)。F0(fake-positive × E1 契约,152824)PASS_ADAPTED。
- 三发照冻结序 15:43-17:20 跑毕,**零缺陷重跑、绊线全绿**(每发前后
  digest+锁态双面),端点健康探每发前 200。

### 三发结果(隐藏 oracle 9 道)

| 发 | 模型 | 判决 | 归因 | 请求 | in/out tok | fidelity | K1 |
|---|---|---|---|---|---|---|---|
| 1(154315) | gpt-5.5 | FAIL 8/9 | budget_overrun:input_tokens(1,831,594,溢 1.75%) | 61 | 1.832M / 49.2K | DELIVERED | 61/61 |
| 2(161822) | gpt-5.6 | FAIL 8/9 | **ok**(自然完成,21.5 分) | 51 | 1.577M / 29.9K | DELIVERED | 51/51 |
| 3(165239) | gpt-5.5 | FAIL 8/9 | budget_overrun:input_tokens(1,803,749,溢 0.2%) | 63 | 1.804M / 44.3K | DELIVERED | 64/64(1 在途无状态=被杀形状) |

三发**同一败象**:5 道链式 pivot delta 节点全修好,唯欠
`test_h2_no_regression_broken`(砸既有回归)—— 与 E1-DSH 批主导失败模式
(8/12 发)同款。

### 四道门判读(机械)

- **G6g ✗**:attribution=ok 且 DELIVERED 的只有 gpt-5.6 一个 model
  (发 2);gpt-5.5 两发均越线被杀。
- **G6bg ✗**:零 PASS。
- **G7 ✓**:无未决 INVALIDATED_FALSE_PASS。
- **K1 ✓**:176/176 条 shim 记录 inbound_fake_key=true —— 真 key 全程
  未进不可信 worker。

**判决:资格如实 FAIL —— E1G-GPT-BRIDGE-1 维持 DRAFT,不冻结、不加发、
不换判据。** 分类旁挂 3 行已转录(四口径全 false)。

### 机制观察(判读上界:单任务 seen、n≤2/模型,不得读作组合优劣)

1. **消耗形状**:GPT×DSH 是 token 重臂(1.58-1.83M in / 51-64 请求),
   贴 in-token 墙 —— 与 deepseek×DSH(E1:≤73.6K in / 106-183 请求,
   token 轻)形状相反。**仪器警示**:两端点 usage 语义可能不同
   (deepseek 缓存命中计数疑异),跨模型 usage 不可直接比较。
2. **DSH 臂预算执法语义**:父侧 watchdog 越线即杀(事后),溢出
   0.2-1.75% 如实入 PolicyVerifier 红;H0 臂 TokenBudgetedModel 是
   调用前拒绝 —— 两臂执法点不同属既知"换循环 = 换执行语义"。
3. 8/9 的一致性(三发同欠同一道)说明组合把模型能力真实送到了判决面
   —— 机械线(接线/指纹/回执/K1/绊线)零缺陷,FAIL 是模型侧读数。

### 封套决算

运行 4/5(F0 + 3 资格发)≤ 上限;墙钟累计 ≈70.4 min ≤ 3h;
in ≈5.21M ≤ 6M;out ≈123K ≤ 1M。全部在封套内。
