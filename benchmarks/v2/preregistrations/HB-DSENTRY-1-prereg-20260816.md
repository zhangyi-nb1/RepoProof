# 预注册:HB 第二批 · DeepSeek V4-Pro 入门档发次(HB-DSENTRY-1,2026-08-16)

> **状态:定稿即冻结(本文提交 = 冻结点)。** 冻结后改动一律附录制,
> 计分发次起跑后改动 = 整批作废。
>
> 上游文书:任务件与判据全部继承 `HB-batch1-postcutoff-delta-prereg-
> 20260816.md`(HB-PCDELTA-1,含附录一全部修订)——本文**不复制**其
> 出题构造与公开面条款,逐条"沿用声明 + 差异点"(§3/§4);预算盒与
> 判据词表**逐字重抄**(它们是冻结措辞,不允许"见上文"式漂移)。
> 通道资格出处:`DQ-deepseek-native-prereg-20260816.md`(6/6 PASS,
> 证据 `docs/evidence/dq_deepseek/canaries-dq_record-20260816T143551Z.json`,
> 冻结点 `769a7dc`)。

**测试模式:HB(TESTPLAN §11)—— 第二次真实使用。**

- 与 HB-PCDELTA-1 同形态同判据同预算,仅换受测通道:deepseek-native ×
  deepseek-v4-pro,任务只取 sqlglot-8042(§8.2 阶梯:8042 对 GPT 是
  Calibration 档,对 DeepSeek 是**入门档**);
- 与 DQ 的区别:DQ 审的是协议(canary 非任务,不计模型),本批**计模型
  表现**(`counts_toward_heldout_benchmark: true`,heldout 分母 6 → 8);
- 与 WH 的区别:无 H0/H2 两臂;两 profile 消融是**通道内单变量观察**,
  不是 harness 增益命题;
- 小样本纪律照旧:**不排名、不出率**;与 GPT 发次数字同表出现时只作
  "同题同预算同视野"的档位事实陈述。

---

## §1 要回答的问题(只有一个)

> 在与 HB-PCDELTA-1 逐项相同的"记忆不可能、先验推不出、判据上游自写"
> 的 held-out 任务 sqlglot-8042 上,**DeepSeek V4-Pro(经 DQ 合格的
> deepseek-native 通道)**能不能交出被上游隐藏验收语义接受的实现?

这是 §8.2 阶梯最低目标的入门档存在性问题。本批**不**回答:DeepSeek 与
GPT 谁强(不排名)、成功率(不出率)、两 profile 谁更好(每格 n=1,
消融差异只记录不外推;正选 profile 裁定属后续批)。

## §2 任务池(冻结,一字不增删)

只取一题。**引用纪律(沿 PCDELTA §2):任何发次数字必须与盲攻上界
并排出现。**

| 任务 | delta 节点 | 盲攻上界 | 备注(随档,引用时必带) |
|---|---|---|---|
| sqlglot-8042 | 5 | **4/5 = 80%** | 净判别余量 **1 节点**;模型全绿的增量信息集中在该节点(`test_chained_pivots_mixed` 系盲攻残差节点,批报必须报"转绿的是不是它") |

随档语境(不作排名):HB-PCDELTA-1 里 gpt-5.5 / gpt-5.6 各 1 发均
PASS_ADAPTED(5/5,盲攻上界 4/5),该题对 GPT 记 Calibration 档。

盲攻者(Fable 子代理)与 DeepSeek **不同族**,上界按"最强攻击者"读,
对受测模型是保守上界 —— 该论证对 DeepSeek 与对 GPT 同样成立。

## §3 出题构造(沿用声明)

任务包 `benchmarks/v2/tasks/hb1_sqlglot_8042/` 与契约自 `ba77070` 起
零改动(git 可查),即 HB-PCDELTA-1 冻结时跑过 F0 电池与两发计分的
同一份件;PCDELTA 附录一第 1(pytest 统一)、7(交付树 = 盲攻输入视野
重构 V + 字节码条款)、8(量具面守卫 + `INSTRUMENT_TAMPERED`)、9
(sitecustomize / 全局插件双通道封堵 + env 净化 + 收集面限定)、11
(三分法修复)条**全部随件生效**。封存池 `~/RepoProofArchive/d5-hunt`
零写照旧。Agent 全程禁网;**唯一网络例外 = provider API 端点本身**
(用户已授权的正常通道,DQ 同款)。

## §4 公开面(沿用 A 案 · 盲攻同视野,零改动)

模型可见 = 题面原文 + 交付树 + 依赖源码;公开反馈 = 回归套件(每轮跑,
红了给 FailurePacket,skipped 三分单列);delta 测试的存在、节点名、
内容全部隐藏,终局才判。PCDELTA §4 的裁定理由与代价条款(模型对 delta
行为零反馈;实验实质 = 单次设计承诺 + 多轮实现修复)原样适用,批报必抄。

## §5 通道、模型与发次序(冻结)

- **通道**:`deepseek-native`(适配器 R1–R5,行为钉 23 条,变异 M75×12
  + M76a);**DQ 6/6 PASS 是进场前提,已满足**(见页首出处);
- **模型**:`deepseek-v4-pro` —— **显式 env 覆盖**(`.env` 的
  `REPOPROOF_MODEL` 指向 GPT 默认,发次侧必须 `REPOPROOF_MODEL=
  deepseek-v4-pro` 覆盖,台账 model 字段核对);GET /models 命中条目无
  版本元数据 → **alias 级记录**(DQ 同口径,如实);
- **台账通道归属**:`runs.jsonl` 的 `provider` 字段自 `9b548fe` 起由
  `ProviderConfig.PROVIDER_TYPE` 落账(批前侦察抓出的写死字面量已修,
  钉 + M76a)——本批两发必须记 `deepseek-native`,记成别家通道即
  停批线 4 级缺陷;
- **发次序**(冻结,共 2 发,每格 n=1):

  | 序 | 任务 | profile | provider_config_sha256(env 基点 = record 当时) |
  |---|---|---|---|
  | 1 | sqlglot-8042 | DS-NATIVE-HIGH-DET | `58d4388e…2dae2b3e50` |
  | 2 | sqlglot-8042 | DS-NATIVE-MAX-OFFICIAL-LIKE | `38bb9045…a172e4910d95e` |

  (完整哈希见 DQ 预注册 §3;发次证据里逐发核对。)
- **消融的线上语义如实声明(彩排侦察发现,附录一第 3 条)**:litellm
  deepseek 变换层把 `reasoning_effort` high|max **同折**为
  `thinking:{"type":"enabled"}` —— 两 profile 到达 API 的实际差异 =
  `temperature`(0 vs 1.0)+ `top_p`(unset vs 0.95),reasoning_effort
  轴被传输层抹平。profile 哈希仍分立(哈希的是配置意图,Gate 4B 不变),
  但**消融差异的解读必须按线上差异读**,批报照此措辞;
- **补发规则(先写死)**:本批**无论结果如何不补发** —— 两 PASS = 入门
  档在两 profile 下均可过,差异记录不外推;一 PASS 一 FAIL = profile
  级差异线索,n=1 不足以立论,追察另立批;双 FAIL = 入门档"本批未见",
  如实入档。
- **知识截止硬门(§5 尾注,与 PCDELTA 同款)**:

  | 模型 | 公开知识截止(用户 2026-08-16 提供,原样记录) | 早于 2026-06-01 | 距 merge 下界余量 |
  |---|---|---|---|
  | deepseek-v4-pro | **2026-04-15** | ✅ | ≥ 1.5 个月 |

  8042 的 merge 日期下界 2026-06-01 由猎取普查查询条件保证(hunt 预注册
  §判据 1)。**硬门通过,不出局。** 记忆通道前提(delta 合并于知识截止
  之后 → 权重里不可能有)成立;余量比 gpt-5.6(3.5 个月)窄,如实记录,
  不影响门槛判定(门是布尔,不是量表)。

## §6 判据(冻结措辞,逐字重抄 + 现行词表两类)

裁定脚本:`scripts/hb_batch_criteria.py HB-DSENTRY-1`(自 PCDELTA 用的
冻结版 `380b793` 起零改动,git 可查;含合成分支活检与 J3 优先级:
`PROVIDER_FAILURE > HARNESS_FAILURE > SUITE_TIMEOUT > INSTRUMENT_TAMPERED
> NO_SUBMISSION > REGRESSION_BROKEN > IMPL_INCOMPLETE > DESIGN_MISMATCH`)。

### 主判据

- **J1 可判性**:每一发都产出 delta 节点级判定(收集不得中断;评分器
  拒测路径触发 → 该发记 `HARNESS_FAILURE`,不计模型);
- **J2 存在性**:≥1 发 PASS(delta 全绿 ∧ 回归零破坏 ∧ 干净重放一致)
  → §1 答"能";全 FAIL → 答"本批未见",如实入档(N=2 的 null 分量弱,
  批报明说);
- **J3 归因字典**(每一发 FAIL 必须落且只落一类;"说不清"该发作废记
  harness 缺陷):

| 类 | 定义 |
|---|---|
| `DESIGN_MISMATCH` | 交付完整、可跑、回归零破坏,delta 未全绿 —— 设计与上游验收分岔。**单列,不得写成泛化能力缺陷**;引用必须并排盲攻上界 4/5 |
| `IMPL_INCOMPLETE` | 交付不完整 / 不可跑 / 公开面(回归)未过 |
| `REGRESSION_BROKEN` | delta 有转绿但回归破坏 > 0 |
| `NO_SUBMISSION` | 预算内未提交 |
| `INSTRUMENT_TAMPERED` | 量具面被动(守卫件 / tests 子树 / 根级扩展点),attribution=agent(PCDELTA 附录一第 8 条入词表) |
| `SUITE_TIMEOUT` | 套件超时,单列不入连败计数;一次重跑,复发按模型侧 FAIL 人工裁定(PCDELTA 附录一第 9 条入词表) |
| `HARNESS_FAILURE` | 量具/管线故障(含 J1 拒测),不计模型 |
| `PROVIDER_FAILURE` | provider 侧故障(API 4xx/5xx 不可恢复、流中断经外层重试仍败等),不计模型 —— deepseek 首入任务 benchmark,该类的边界即 DQ 所验协议面 |
- **J4 零泄漏**:发次工件与模型上下文里捞不出 delta 测试内容与答案
  patch(发现泄漏 → 停批,该题判死);
- **J5 部分转绿**(副,不阻断):逐发记录 delta 转绿数 / 5,**并报转绿
  节点与盲攻残差节点(`test_chained_pivots_mixed`)是否同一个**;
- **J6 消融纪律**(副):两 profile 的 usage / 轮次 / 墙钟 / 思考链在场
  差异记录不外推,不选"正选 profile"(那是后续批的预注册);
- **J7 回执/采纳类判据不适用声明**:本形态无上游采纳语义,U1–U4 不在场。

### 停批线(任一触发即停批不补发)

1. 连续 2 发 `HARNESS_FAILURE`(`SUITE_TIMEOUT` 单列不入此计数);
2. 封存件/宿主摘要在批期间变化(verify-only 复验报被动过);
3. J4 泄漏;
4. 发现安全/判据缺陷(不修完出新版不续跑,整批作废重预注册)。

`PROVIDER_FAILURE` 不入停批线连败计数(它不是 harness 病),但连续 2 发
`PROVIDER_FAILURE` → 暂停请示(通道可能整体不可用,烧预算无意义)。

## §7 发次分类(先写死,发完照此登记)

```
run_purpose: HELDOUT_MODEL_EVALUATION
test_mode: HB
task_seen: false
oracle_authorship: UPSTREAM_OWN_TEST_SUITE
host_modification_mode: PRISTINE
counts_toward_model_capability: true
counts_toward_heldout_benchmark: true
counts_toward_mechanism_effect: false
counts_toward_profile_qualification: false
classification_timing: PRE_REGISTERED
host_id: tobymao/sqlglot
model: deepseek-v4-pro
provider: deepseek-native
```

**台账效应预告(K6/K12,防惊讶——转红是设计,不是事故)**:
`tests/test_run_classification.py` 两处实台账钉(heldout 分母**恰 6**、
分子**恰 2**;真台账逐发两道硬门)在本批旁挂落账后**必然转红**。按钉上
旧文自己的指示处置:当批显式重审两道硬门(oracle=UPSTREAM_OWN_TEST_SUITE
原样接线、host=PRISTINE 零挖空零加语义 —— 本批任务件零改动,重审 =
核对 harness_commit 与任务件 git 历史),然后更新钉值:分母 6 → **8**,
分子 2 → **2 + X**(X = 本批 PASS 数,0/1/2 按实况),仍钉**恰好等于**。

## §8 HB 冻结纪律(照办)

- harness / oracle 接线 / 任务包 / 契约:**本文提交时的 HEAD 冻结**,
  批期间一字不动(F0 四形态与两发计分的 `harness_commit` 必须全等于
  冻结点);
- 不根据模型失败改执行器;失败只观察、只归因、只记录;
- 发现 safety/判据 bug → 整批作废,修完出新版重预注册;
- n 小不排名:批报只报逐发判定 / delta 转绿 / 回归 / 归因类 / token 与
  轮次消耗;不出现通过率、不出现模型排序。

## §9 额度(冻结值,与 HB-PCDELTA-1 逐字相同 —— 同预算铁律)

```
semantics: per_round
max_rounds: 3
max_model_calls: 30
max_commands: 100
max_patch_files: 15
max_patch_lines: 1500
max_wall_time_minutes: 60
max_input_tokens_total: 600000
max_output_tokens_total: 80000
```

跨通道可比性的根:GPT 两发 8042 就是在这个盒子里跑出 5/5 的。**开跑后
不改;要改 = 全通道同改 + 批作废 + 重预注册。** token 执法沿现行调用前
投影;deepseek 侧记账权威 = `extra.response.usage` 同步双向(DQ C1 的
契约点,已实测非零)。

## §10 前置条件(全绿才起第 1 计分发,逐条勾)

- [x] **通道资格**:DQ 6/6 PASS(已满足,证据绑定 `769a7dc`);
- [x] **知识截止硬门**:2026-04-15 < 2026-06-01(§5 已录,用户提供);
- [x] **闸门**:变异闸门 **217/217** 声明归因(M75×12 + M76a 入列,证据
      `docs/evidence/mutation_gate/9b548fe26e4e.json`,绑定 `9b548fe`);
      全量测试 + `check_public_claims` 冻结提交前最后跑,结果记附录一
      第 5 条;
- [x] **端到端接线彩排(工程冒烟,不计任何表现)**:deepseek-native 走
      完整 runner 栈(host-run → preflight → TokenBudgetedModel(
      DeepSeekNativeModel) → 会话装配 → 判定 → 台账)在**开发套件**
      任务 t1(§11.2 允许面)跑通一发,批号
      `EXPLORATORY_UNPREREGISTERED`(闸门计数排除);验的是布线
      (provider/model/profile/config-sha 落账正确、usage 记账非零、
      多轮工具循环无协议错),**不是** t1 成绩 —— verdict 无论
      PASS/FAIL 均不入任何能力口径(T1 是开发套件,§11.2 禁止外推)。
      **已跑毕,六项布线判据全绿,详见附录一第 2 条**(含 reasoning
      回传告警的追查与凭据级排除);
- [ ] **F0 四形态自证(冻结 HEAD 上)**:8042 × {正控 `--fake positive`、
      `control:nc_null_submission`、`control:nc_regression_break`、
      `control:nc_instrument_tamper`},批号 **`HB-DSENTRY1-F0`**;
      `hb_batch_criteria.py HB-DSENTRY1-F0 --selftest` 必须打印
      SELFTEST OK(四形态各归各位 + 合成分支活检全对)。正控期望
      PASS_ADAPTED 且轮末读数与契约基线逐字对齐(`1150 passed / 0
      failed / 0 skipped`);三负控期望逐类落位。任何错位 = 停,修完
      重冻结;
- [x] **宿主与封存**:`prepare_hb1_hosts.py --hosts` verify-only 幂等
      复验绿(2026-08-16 15:00Z 一轮已绿入证据;F0 电池后、批后各再
      复验一轮);封存池零写。

## §11 跑法与成本封套

- **计划确认**:整批计划(侦察 → 彩排 → 冻结 → F0 → 计分两发 → 收口)
  已报,用户 2026-08-16 "**DeepSeek V4-Pro 知识截止 2026-04-15,起批**"
  即 v3 协议的一句确认 —— 两计分发**照序连跑不逐发停**;唯 harness
  缺陷 → 停修(钉死 + 附录)→ 该发从零重跑,停批线即停;
- 发次命令形态(记录,防复现歧义;key 值不进任何工件):
  `REPOPROOF_PROVIDER=deepseek-native REPOPROOF_MODEL=deepseek-v4-pro
  REPOPROOF_DS_PROFILE=<profile> repoproof host-run --contract
  benchmarks/v2/tasks/hb1_sqlglot_8042/contract.yaml --batch HB-DSENTRY-1
  --run-order <N> --run-index 1`;
- **成本封套**:计分段 2 发 ≤ **1.2M 读入 / 160K 产出 / 2.5h 墙钟**
  (单发预算盒 ×2 的余量内取整;彩排与 F0 另计:彩排 ≤1 发预算盒,
  F0 零 API);**运行上限 4**(计划数 × 2,含缺陷重跑);超封套 = 中止
  请示;
- 批报唯一事实源:`benchmarks/v2/reports/HB-DSENTRY-1-report-<date>.md`,
  数字只出脚本(`hb_batch_criteria.py` / `gate_report.py` /
  `check_public_claims`)。

---

## 附录一(工程留痕;冻结前逐条补记,冻结后只增不改)

1. **批前侦察抓出台账通道归属写死并修复(2026-08-16,commit `9b548fe`)**。
   `host_guided._finish` 原把 provider 写死 `"openai-compatible"/"fake"`,
   deepseek 发次会被记成别家通道 —— 静默换模的台账端。修为
   `provider_label()`(取 `ProviderConfig.PROVIDER_TYPE`,fake 冒烟如实
   记 fake),四处调用点全改;钉(值断言 + AST 双面)+ 变异 M76a。修复
   在任何计分发次之前,属 §10 前置侦察的产出(PCDELTA 附录一第 9 条同
   款时序论证:计分发次数 = 0,无数据需作废)。

2. **端到端接线彩排实测(2026-08-16,run
   `t1-offerclaw-fastapi-mcp-v1-20260816-231847`,批
   `EXPLORATORY_UNPREREGISTERED`,harness `9b548fe`)**。六项布线判据:

   - ① preflight PROVIDER_READY,发次未被拦;
   - ② 台账行:`provider=deepseek-native`、`provider_config_hash=
     58d4388e…`(= 冻结 HIGH-DET sha 逐字)、`model=deepseek-v4-pro`、
     `exec_generation=E0` —— M76a 所钉的归属链路首次实弹核对通过;
   - ③ 预算执法:同步记账非零(in 1,855,769 / out 26,032),第 3 轮
     调用前投影触墙(`474096 >= 500000, final_round`)→
     `TokenBudgetExhausted` 干净收束,非崩溃;
   - ④ 协议面零故障:75 调用 / 89 命令 / 3 轮,trace 296 事件链完整
     (`action.start/end` 89 对齐),FormatError 0、重试 0;
   - ⑤ **R2 回传凭据级验证**:三轮轨迹 72 条 assistant 消息,凡响应带
     思考链者历史里逐字在场,**真丢失 = 0**;6 条无思考链消息系模型该
     轮未产出(原始响应同样无),litellm 对这 6 条按官方最小值注入
     `" "` 占位并告警 —— 告警 79 次全部对应这 6 条在后续调用里的重复
     计数,**不是管线丢件**(逐轮取证脚本见会话记录;这正是彩排要抓
     的那类"看起来像 bug"的现场,追查结论:适配器无缺陷);
   - ⑥ 判定链完整:capability 9/9(会话内)、回归 592/基线 591、干净
     重放执行且给出判决(FAIL — replay 分歧)、postflight 干净。

   **verdict = FAIL(重放分歧)如实记录,不入任何能力口径**(t1 属
   开发套件,§11.2;且本发批号即 EXPLORATORY)。重放分歧属模型侧交付
   自包含性问题,非通道协议故障 —— 8042 计分发对这一维的判定正是判据
   本职,不预修不预教。

3. **reasoning_effort 的传输层抹平(彩排侦察发现,已升入 §5 正文)**。
   litellm deepseek 变换 `map_openai_params`:reasoning_effort ≠ none
   → `thinking:{"type":"enabled"}`,不区分 high/max。两 profile 线上
   差异 = temperature + top_p。DQ 结论不受影响(DQ 判的是协议通不通,
   `reasoning_rounds_observed` 本就记录不设门);哈希纪律不受影响
   (Gate 4B 哈希配置意图)。批报消融段按线上差异措辞。

4. **冻结前工程冒烟两笔(API 面,不计任何口径)**:①两格探针(有/无
   `max_tokens`)排除 max_tokens 抑制思考链假说;②两轮回传探针证明
   适配器全链保真(turn2 无占位告警)。合计 4 次小调用,封套忽略不计;
   与 DQ 冒烟同族(ENGINEERING_SMOKE),不落台账。

5. **冻结提交前最后一跑(数字如实)**:彩排行落账后首跑全量 exit=1,
   红的恰是三根 v2_gate 新鲜度/公开声明钉(台账新增一行、docs/v2_gate.json
   未再生 —— 钉在干本职);按 checker 自带处方 `gate_report.py --write`
   再生,diff 全量复核 = exploratory 7→8(新行入列)+ total 160→161 +
   输入 sha,**heldout 分母/分子 6/2 不动**(彩排行零污染,K6/K12 如
   §7 预告只在计分批落账时转红);三钉复跑绿,`check_public_claims`
   `{"ok": true}`;冻结提交前全量整跑绿(数字见提交信息)。
