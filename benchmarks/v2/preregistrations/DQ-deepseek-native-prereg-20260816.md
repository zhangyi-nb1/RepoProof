# DQ 预注册:deepseek-native 通道资格(2026-08-16)

**测试模式:DQ(Provider 资格)**,记账口径按 TESTPLAN §11:考察对象是
**Provider 层协议**(经我们的栈是否按官方语义跑),不是模型能力;canary
非任务,**一律不计模型表现**;§11.5 停规适用。冻结点 = 本文件所在提交
(harness_commit 逐格入证据)。

## 1. 对象与通道

- 通道:`deepseek-native`(`src/repoproof/agents/deepseek_native.py`,
  适配器 sha256 入证据)。五条卫生规则 R1-R5 见适配器 docstring,行为
  钉 22 条(`tests/test_deepseek_native.py`)+ 变异 M75a-l 声明归因。
- Provider:DeepSeek 官方 API(base 走 env,证据只落 redacted summary)。
- 模型:`REPOPROOF_DEEPSEEK_DEFAULT` 所指(canary 时点)。**alias 与
  resolved release 分开记**:GET /models 的 id 全列 + 命中项原样入证据;
  跑的是别名还是钉死版本,证据层必须能说清。
- 传输:litellm `deepseek/` 路由,SSE 流式 + include_usage,流内零重试
  (R4);action protocol 冻结 `native`(function calling)——native 探针
  不过即 BLOCKED,**不落回 textbased**(那是另一个协议,不是本资格对象)。

## 2. 判据矩阵(冻结)

**3 canary × 2 profile = 6 格。全 6 格 PASS → DQ PASS;任一格 FAIL 或
缺格 → `PROVIDER_PROTOCOL_FAILURE`,该通道不进任务 benchmark(§11.5)。**
判决由 `dq_verdict()` 机械算出(钉:`tests/test_dq_deepseek_canaries.py`
`test_dq_verdict_requires_every_cell_green_and_complete`),无人工格。

每格前置:`run_preflight` 必须 `PROVIDER_READY`(typed status 入证据;
不 READY 该 profile 三格全 FAIL,病名 = preflight status)。

- **C1 单轮工具**:一发 prompt 要求 `echo DQ_C1_OK`。PASS =
  `action_parsed ∧ command_echoes_token ∧ usage_prompt_positive ∧
  usage_completion_positive`(后两条即 TokenBudgetedModel 同步记账契约
  点:`extra.response.usage` 双向 > 0 —— 预算执法的眼睛)。
- **C2 多轮 reasoning passback**:三步 echo(STEP1 → STEP2 → DONE)的
  **全工具轮**循环,≤4 轮,逐轮按 profile 的 `reasoning_passback` 旋钮
  回传思考链。PASS = `multi_round_tool_loop(≥2 工具轮)∧
  done_step_reached ∧ no_protocol_error`(任何 4xx/异常即 FAIL,异常
  形状入证据)。收尾也是工具调用 —— mini 协议里无 tool_call 轮即
  FormatError(生产同款),canary 不与自家栈打架。思考链逐轮在场与否
  (`reasoning_rounds_observed`)**记录不设门** —— 它回答"回传规则实测
  是什么",不预设官方文档记忆正确。
- **C3 长 observation**:第 1 轮取 tool_call 后,喂一条 **8000 字符**
  (= 生产 `obs_cap()` 默认)的工具观察,末尾针语句
  `DQ_C3_NEEDLE_VALUE=<token>`;第 2 轮须以 `echo REPORT:<token>` 工具
  调用复述针值。PASS = `tool_call_round1 ∧ needle_echoed_verbatim`
  (第 2 轮动作参数逐字含 token)——只"被接受"不算数,内容必须真的
  送达;针在尾部,截断攻击面最敏感处。

观察一律**模拟**(canary 零执行面,AST 钉死:
`test_canary_script_has_zero_execution_surface`),证据 `simulated=true`
自曝。

## 3. 两 profile 消融(§55;§66:官方 Flash 参数只是候选)

| profile | temperature | top_p | reasoning_effort | reasoning_passback |
|---|---|---|---|---|
| DS-NATIVE-HIGH-DET | 0 | unset | high | tool_loop |
| DS-NATIVE-MAX-OFFICIAL-LIKE | 1.0 | 0.95 | max | tool_loop |

全部旋钮进 `DeepSeekProviderConfig.normalized()` → 两 profile 各得独立
`provider_config_sha256`(单变量可比由哈希层背书;钉:
`test_two_ablation_profiles_hash_differently_single_variable_comparable`)。
冻结时点哈希:

- DS-NATIVE-HIGH-DET:`58d4388e0626b4c921a65171fca8d1f4d415dcbfa380637841190a2dae2b3e50`
- DS-NATIVE-MAX-OFFICIAL-LIKE:`38bb904540acfc10b4be9e40582332c06a7b3e20d9182144a7ea172e4910d95e`

(以 base fingerprint = record 当时 env 为准;若 base 变更,哈希随变并
在证据里可见 —— 哈希是配置的影子,不是配置的替身。)

采样参数若被官方拒(400 提及 temperature/top_p/reasoning_effort)→
该格 FAIL 如实入证据,**不做静默降级重试**(preflight 的 temperature
回落只影响探针本身,不影响 canary 判决)。

## 4. 停规与重冻

- 任何格 FAIL → 记 `PROVIDER_PROTOCOL_FAILURE`,分析病名;若病在**我们
  的适配器/脚本**(非 provider):修复 → 钉死 → **重新冻结**(本文件
  附录留痕)→ 已跑 record 作废全量重跑。已作废证据不删,标 SUPERSEDED。
- 两 profile 都 PASS → 消融差异(usage/思考链在场率/墙钟)**记录不外推**;
  正选 profile 的裁定属后续批(WH/HB)预注册,不在本 DQ。
- DQ PASS 是进入 WH 弱模型臂与 HB 阶梯(§8.2:DeepSeek V4-Pro 从 8042
  档进场)的**必要条件**,不是充分条件 —— 各批仍有自己的准入。

## 5. 记账与证据

- **不落 `runs.jsonl`**(无发次;DQ 是 Provider 层资格,不是 benchmark
  运行),`v2_gate` 计数不受影响;证据文件即台账:
  `docs/evidence/dq_deepseek/canaries-dq_record-<UTC>.json`(逐格 checks
  原值、转录摘要 = 头部+长度+sha、usage、preflight typed status、
  GET /models 原样、litellm 版本、适配器 sha、harness_commit)。
- 脚本:`scripts/dq_deepseek_canaries.py`(离线钉 12 条:
  `tests/test_dq_deepseek_canaries.py`,PASS 形状与 FAIL 路径均有红绿)。
- 成本封套:≤2 profile × 3 canary,调用 ≤40(适配器外层 retry 计入),
  in ≤200K tok / out ≤50K tok / 墙钟 ≤30min。超封套 = 中止,病名入证据。

## 6. K5(落笔时点自曝)

本预注册在**工程冒烟之后、record 之前**冻结:冒烟(ENGINEERING_SMOKE,
证据落 /tmp,不算 DQ)用于验证旋钮拼写与连通性,其发现如实记入附录一;
判据矩阵(§2)与 profile 定义(§3)在冒烟前已由代码与钉死固定
(commit `4383681`),冒烟只允许修正"发不出去"级别的工程错误,不允许
按冒烟结果调判据 —— 若发生判据级改动,必须在附录留痕并说明为何不构成
looking-at-the-answer。

## 附录一(工程留痕)

1. **冒烟 A(2026-08-16 14:22Z,两 profile × 三 canary)**:2/6 —— C1
   双 PASS;C2/C3 四格 FAIL,病名 `FormatError`(空串)。诊断:FAIL 发生
   在**客户端解析层**(API 往返均 200,reasoning 回传被官方接受)——
   原 canary 设计让收尾轮"裸文本作答",而 mini 协议里**每轮必须是
   tool_call**(`parse_toolcall_actions` 对空 tool_calls 抛 FormatError,
   生产同款):是 canary 与自家栈打架,不是 provider 缺陷。修复(判据
   语义不变,载体改全工具轮):C2 收尾改 `echo DQ_C2_DONE` 工具调用,
   `loop_terminated_with_content` → `done_step_reached`;C3 复述改
   `echo REPORT:<token>` 工具调用,针值判定移到动作参数;`_typed_exc`
   补 FormatError 病名提取(其 str() 为空)。离线钉同步 13 条全绿。
   附带教训:冒烟命令管道 `| tail` 吞了退出码(与 -qq 吞汇总同型),
   判读一律以打印的 verdict JSON 为准。冒烟证据(不算 DQ):
   `/tmp/dq_deepseek_smoke/canaries-engineering_smoke-20260816T142240Z.json`。
2. **冒烟 B(2026-08-16 14:28Z,修复版,冻结前最后一发)**:**6/6 全
   PASS,dq_status=PASS**。逐格:C1 双 profile usage 383/6x,~2s;C2 双
   profile 恰 3 轮全工具收束(STEP1→STEP2→DONE),思考链 3/3 轮在场
   且回传全被接受(HIGH-DET 1630/203、MAX 1664/216);C3 8000 字符观察
   后 REPORT 动作逐字命中针值,两轮思考链在场(2401/172、2364/144)。
   preflight 双 PROVIDER_READY(native),temperature 0 与 1.0 官方均
   接受,无降级。GET /models:`[deepseek-v4-flash, deepseek-v4-pro]`,
   命中条目无版本元数据 → alias 级记录(resolved release 无端点可查时
   如实记 alias-only,属记录不是门)。litellm 1.91.4。冒烟证据(不算
   DQ):`/tmp/dq_deepseek_smoke/canaries-engineering_smoke-20260816T142810Z.json`。
   冒烟 B 后判据零改动 → 本文件冻结,record 开跑。
