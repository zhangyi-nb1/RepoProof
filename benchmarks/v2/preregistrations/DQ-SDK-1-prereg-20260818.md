# DQ-SDK-1 预注册:DSH minimal backend 真模型资格(阶段 7,2026-08-18)

**测试模式:DQ(backend 资格)。** 考察对象是 **rt-dsh-minimal-0.1.0rc6-v1
这套运行组合真模型跑不跑得动**(指导报告阶段 7),不是模型能力。与
DQ-deepseek-native(Provider 层资格,不落台账)不同:本资格的判据 G6/G7
**机械读台账**,故发次入 `runs.jsonl`,但分类旁挂四口径全 false ——
资格发次不作任何能力 / held-out / 机制 / 处理主张。冻结点 = 本文件所在
提交;开跑后判据一字不改。

## 1. 对象与判据(机械,零人工格)

- 对象:`rt-dsh-minimal-0.1.0rc6-v1`(现 candidate)→ **qualified** 晋级。
- 判据 = `profile_promotion.evaluate_promotion(..., to="qualified")`:
  - **G6**:该 profile 台账上 ≥2 个不同真实 model(非 fake 前缀);
  - **G6b**:≥1 发 verdict PASS* 且未被裁决作废(诚实通过全链);
  - **G7**:无未决 INVALIDATED_FALSE_PASS。
- 全过 → `promote_profile.py rt-dsh-minimal-0.1.0rc6-v1 --to qualified
  --record` 留痕 + lifecycle 翻牌;任一不过 → 停在 candidate,阶段 8
  桥接批**不冻结**(其预注册维持 DRAFT)。

## 2. 通道与组合(有效面即指纹)

- 通道:`deepseek-native` × `--backend dsh`(B-dsh,准入三验:provider
  类型 / bridge_budget fail-fast / cordis 现物复核)。
- **REPOPROOF_DS_PROFILE 旋钮在 B-dsh 臂惰性**(如实声明):worker job
  只送 model / system_prompt / max_tokens / 通道凭据,temperature 与
  top_p 是 SDK 内部值,设不进。点名 `DS-NATIVE-HIGH-DET` 仅为通道准入
  所需(provider_from_env 无缺省);**有效组合以
  composition_fingerprint 九键为准**(system prompt / 256000 / high,
  阶段 8 预注册草案 §6 同源)。故 G6 的"两个 model profile"按台账
  `model` 名去重落实:`deepseek-v4-pro` 与 `deepseek-v4-flash`
  (两名均为 DQ 证据 GET /models 实录,2026-08-16)。
- 封存:`~/RepoProofRuntimes/rt-dsh-minimal-0.1.0rc6-v1`,指纹现场复核,
  不符拒跑。

## 3. 任务与已见声明

- 任务:`hb1-sqlglot-8042`(**seen**:HB-DSENTRY-1 / WH-PILOT-1 两批 +
  准入盲攻已接触公开面;真实可解性有据:gpt-5.5 / gpt-5.6 各 1 发
  PASS_ADAPTED)。指导报告"corrected Front Matter 类正控"在本仓无对应
  现成任务,取现有池中**真模型通过过、宿主就绪、判据面最新**的任务替,
  如实记为偏差(判据语义不变,载体替换)。
- 后备:`t1-offerclaw-fastapi-mcp-v1`(gpt 两发通过;deepseek 旧架构
  5 FAIL)。
- 分类旁挂(**预写**,批结束机械转录):test_mode=DQ、
  run_purpose=BACKEND_QUALIFICATION、task_seen=true、
  assistance_level=BOUNDED_PUBLIC_REPAIR、host_modification_mode=PRISTINE、
  oracle_authorship=UPSTREAM_OWN_TEST_SUITE、treatment_assigned=false、
  counts_toward_{model_capability, heldout_benchmark, mechanism_effect,
  treatment_effect} **全 false**。

## 4. 预算(total 语义变体契约)

原 contract.yaml 是 per_round 语义,B-dsh 准入即拒(等总额无从定义)。
本批用 `contract-dsh-total.yaml`(task_version=v1-dsh-total):预算盒
**等信封 ×3 折算**(calls 90 / commands 300 / in 1.8M / out 240K;实证
基础:HB 发次 164602 in=1,743,528 > 600K 未被砍 → 原语义按轮分桶),
墙钟 60 分**原值不扩**(观测峰值 16.3 分),patch 轴原值(裁决面执法,
臂中立),max_rounds=1(B-dsh 的循环在 runtime 内部)。host / capability /
constraints / acceptance 四节与原件逐字一致。

## 5. 发次序与上限(防事后挪门槛)

计划 3 发,**运行上限 5**(含缺陷重跑):

1. 8042 × `deepseek-v4-pro` × dsh —— 机械面确认(模型调用 / 工具调用 /
   usage / finish reason 逐项)+ 通过尝试;
2. 8042 × `deepseek-v4-flash` × dsh —— G6 第二 model + 通过尝试;
3. 仅当 1-2 均无 PASS:t1-fastapi-mcp × `deepseek-v4-pro` × dsh
   (最后尝试;host 沿用现成 offerclaw-t1 宿主)。

全序跑完仍无诚实 PASS → **阶段 7 如实 FAIL**:profile 停 candidate,
证据入库,阶段 8 不冻结 —— 不加发次凑门,不换判据。

- **fidelity 前置**:每发 `dsh` 回执块九项判读;TREATMENT_NOT_DELIVERED
  的发次不满足 G6 的"被执行"(治疗没送到不算跑过),如实入账。
- **停规**:harness / instrument 缺陷 → 停修(钉死 + 附录留痕)→ 该发
  从零重跑;不回填、不带伤计数。

## 6. F0 与彩排面(声明,不做的说清为什么)

- 判据面四形负控:同判据在 2026-08-17 已全量证过(HB/WH F0 电池 +
  R1 活钉),本批只重跑 **fake-positive 工程冒烟**(新契约变体的
  total 语义全链验证,零 API,batch=DQ-SDK-1-F0,不计任何口径);
- dsh 执行面彩排:`test_r1_run_dsh_round_end_to_end_over_fake_endpoint`
  活钉在每次全量套件跑(真封存 worker × 假端点)。

## 7. 成本封套

≤5 发,累计 in ≤8M tok / out ≤500K tok / 墙钟 ≤3h;preflight 双探活
已计(378+378 in)。超封套 = 中止请示,不静默续跑。

## 8. 划界(结论措辞的上界)

qualified 只证明:**这套封存组合 + 真 DeepSeek 模型,能把 RepoProof
全链诚实跑通,且至少一发真过了一道真任务**。它不是模型能力主张
(四口径全 false),不是 DSH 优于 mini-swe 的证据(那是阶段 8 批的
研究问题,n=3 才开问),更不回答 held-out 表现。

## 附录一(工程留痕)

1. **preflight 双探活(2026-08-18,冻结前)**:deepseek-v4-pro
   PROVIDER_READY(native,1 调用,378/63,1.8s);deepseek-v4-flash
   PROVIDER_READY(native,1 调用,378/69,0.9s)。base 只记 redacted
   summary;key 注入 = shell `source .env`,值不进上下文 / argv / 工件
   (用户 2026-08-18 授权代注入,纪律原文见 EXPLORATION_LOG 本批段)。

## 附录二(停修留痕,判据零改动)

1. **F0 冒烟(计划内)**:total 变体契约 fake-positive 全链
   PASS_ADAPTED(run `hb1-sqlglot-8042-20260818-003100`,
   batch=DQ-SDK-1-F0)。
2. **发 1(运行 1/5,HARNESS_FAILURE)**:8042 × v4-pro × dsh,agent 环 /
   验证 / oracle / 重放全走完,**台账记录装配处 NameError**
   (`_finish` 引 `run()` 局部名 `dsh_round_infos`;R1 只钉 module 函数、
   F0 走 mini-swe 条件分支,均未覆盖此行)→ 发次未落账,如实弃置
   (run 目录 `hb1-sqlglot-8042-20260818-004959` 留作现场)。工程读数
   (诊断,不判):worker 归因 `budget_overrun:logical_requests`
   (91 撞 90),usage in 46,294 / out 52,612(+reasoning 28,541)——
   消耗形状与 mini-swe 臂截然不同(请求多而 token 轻),留待批报分析。
   **修**:回执块独立成签名传参纯函数 `dsh_receipt_block`(跨方法自由
   变量类结构性消灭),判读走 dsh_bridge.fidelity_verdict 不另写第二套;
   **钉**:`test_r2_dsh_receipt_block_*` ×2。判据、预算、发次序零改动;
   发 1 按 §5 停规从零重跑。

## 附录三(基建事件与计数口径,续跑前声明)

1. **供应商翻牌实录(2026-08-18 01:33–01:52)**:发 1 两次重启动均在
   preflight 即 BLOCKED(PROVIDER_TIMEOUT,30s 探针超时,零 agent 活动、
   零 token、零台账行);期间独立探针 01:36 同超时(附 litellm 远程价目
   表拉取同刻超时)、01:38–01:51 六连 PROVIDER_READY(1–2s)、01:57 复又
   READY —— 一般出网全程正常(github 0.7s/apple 0.2s)。判:DeepSeek
   端点分钟级翻牌,preflight 单发无重试(按设计,不静默降级)撞窗即挡。
2. **计数口径(声明,非改判据)**:§5 的"运行上限 5"约束的是**进入
   agent 阶段的运行**(有 run 目录、有消耗、可归因)—— 其立意是封顶
   API 消耗与防"加发凑门"。preflight 即 BLOCKED 的启动(零消耗、零
   发次工件)记**基建事件**,入本附录不占运行位。至此:运行 1/5
   (NameError 那发,91 请求);基建事件 2 起;工程探针 preflight 合计
   9 次(≈3.4K in,计入封套)。
3. **翻牌应对(执行层,不改 preflight 语义)**:启动封装对"preflight
   即 BLOCKED 且 PROVIDER_TIMEOUT"的结果自动隔 120s 重启,单发次至多
   4 次;每次启动的 preflight 判定原样留痕。连 4 次撞窗 → 中止请示。
