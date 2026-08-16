# HB-DSENTRY-1 批报(2026-08-17)

- **模式:HB**(TESTPLAN §11,第二次真实使用);预注册
  `HB-DSENTRY-1-prereg-20260816.md`,**冻结点 `b50d6c0`**(预注册提交
  即冻结;F0 四形态与两计分发的 `harness_commit` 逐发 = 冻结点,已核)
- 通道:deepseek-native(DQ 6/6 PASS,`769a7dc`);模型 deepseek-v4-pro
  (alias 级,知识截止 **2026-04-15**,用户核录,早于 delta merge 下界
  2026-06-01 → §5 硬门过)
- 判据裁定:`scripts/hb_batch_criteria.py HB-DSENTRY-1`(J1–J7 冻结版
  `380b793` 零改动);自证 `… HB-DSENTRY1-F0 --selftest` = SELFTEST OK
  (四形态各归各位 + 10 支合成分支活检全对);数字出处 `gate_report.py
  --write` 与 `check_public_claims`(`{"ok": true}`)
- 批期间 harness 零改动、零停批线触发;两发照序连跑(§11:用户"起批"
  即一句确认)

## 1. 两发结果(执行序 = 预注册 §5)

| 序 | run_id | profile | verdict | J3 | delta | 盲攻上界 |
|---|---|---|---|---|---|---|
| 1 | hb1-sqlglot-8042-20260817-003557 | DS-NATIVE-HIGH-DET(58d4388e) | FAIL | NO_SUBMISSION | **0/5** | 4/5 |
| 2 | hb1-sqlglot-8042-20260817-004640 | DS-NATIVE-MAX-OFFICIAL-LIKE(38bb9045) | FAIL | NO_SUBMISSION | **0/5** | 4/5 |

J 表纪律:delta 读数一律并排该题盲攻上界(4/5 = 80%,净判别余量 1
节点)。**J2 存在性:本批未见**(0/2;N=2 的 null 分量弱,预注册已声明,
不出率不外推)。J5:五个 delta 节点全红,盲攻残差节点
`test_chained_pivots_mixed` 未转绿(与其余四节点同红,残差问题不适用)。

随档语境(不作排名):同题同预算同视野下 HB-PCDELTA-1 的 gpt-5.5 /
gpt-5.6 各一发均 PASS_ADAPTED(5/5,14–16 调用内提交);8042 对 GPT 记
Calibration 档,对 DeepSeek 为入门档 —— 本批档位事实:入门档两 profile
均未过。

## 2. 逐发实况

**序 1(HIGH-DET)**:30 调用 / 30 命令 / 供方计费读入 439,486 /
产出 6,111 / agent 墙钟 258.7s / 单轮。回归面全程绿(1150 = 基线,零
破坏,未触发修复轮),**30 调用打满未提交**(exit=LimitsExceeded,
call 上限),judged-as-left:五个 pivot 系 delta 节点全红
(`test_chained_pivots` / `_consuming_alias_columns` / `_mixed` /
`_through_cte` / `_with_alias_columns`)。J3 按冻结优先级落
`NO_SUBMISSION`(预算内未提交,优先于 DESIGN_MISMATCH)。FAIL 不重放
属设计(重放只确证 PASS)。

**序 2(MAX-OFFICIAL-LIKE)**:30 调用 / 30 命令 / 供方计费读入
538,107 / 产出 5,494 / agent 墙钟 242.1s / 单轮。行为形状与序 1 相同:
回归恒绿、打满未提交、五 delta 节点全红,`NO_SUBMISSION`。

通道协议面(两发均):FormatError 0、重试 0、trace 109 事件链完整
(action.start/end 30 对齐)、postflight 干净;R2 思考链回传轨迹级
核对:序 1 assistant 30 条中 27 条思考链在场、序 2 28 条在场,响应带
而历史丢的**真丢失双双 = 0**(无思考链的 3/2 条系模型该轮未产出,
litellm 按官方最小值注 `" "` 占位)。

## 3. 消融观察(J6:记录不外推,不选正选 profile)

- 线上差异 = temperature(0 vs 1.0)+ top_p(unset vs 0.95);
  reasoning_effort high|max 被 litellm 同折为 thinking:enabled(预注册
  §5 已声明);
- 同 30 调用预算内,MAX 侧供方计费读入多 22%(538,107 vs 439,486;
  均值 17.9K vs 14.7K/调用)—— 与 R2 回传的思考链更长一致;产出与墙钟
  同量级;verdict/J3/delta 逐项相同。n=1/格,差异不立论。

## 4. 台账 token 读数虚高:病名与两套读数(如实公示)

**发现**:两计分发台账 `input_tokens` 记 571,266 / 807,266,而逐调用
供方 usage 求和(轨迹为证)为 439,486 / 538,107(虚高 1.30× / 1.50×)。

**病名(探针定案)**:台账数取自 litellm success 回调的 run 级累加桶;
deepseek 流式路径下 litellm 对**同一支请求**派发两枚带 usage 的终态
success 事件(66 枚逐 chunk 事件 usage=None + 2 枚终态带满额 usage,
单调用探针实录),回调桶遂重复计数;异步派发 + agent 段末清空回调的
竞态使虚高非严格 2×(1.30–1.50×,含 t1 彩排发 1.31×)。GPT 发次不受
影响(非流式路径单枚事件)。

**执法未受影响(与虚高问题分立,逐项核)**:预算执法权威 = 同步记账
(LESSONS #39 H7-a/H7-d,读返回体 usage,= 供方计费口径)。两发同步
口径 439K / 538K 均低于 600K/轮墙;两发 `budget.exhausted` 事件零、
`budget_exhausted=None`,终局由 call 上限(30)收束 —— **token 墙未
误发火,发次未被虚高读数扭曲**。判据 J1–J7 与 verdict 不读
input_tokens,判定不受影响。

**成本封套(§11)按两套读数分别报**:供方计费口径 2 发读入 977,593 ≤
1.2M(✓,产出 11,605 ≤ 160K ✓,墙钟 ~18min ≤ 2.5h ✓,运行数 2 ≤ 4 ✓);
台账口径读入 1,378,532 名义超线 —— 病名即上,按真实计费判未超,虚高
数字不采信但不改台账(不追溯改写旧发次读数,旧例照守)。

**处置**:harness 冻结批期间一字未动;修复(回调按请求去重或流式路
改读同步口径)+ 钉死 + 变异,批后立即单独提交。

## 5. 完整性

- **F0 四形态(批 `HB-DSENTRY1-F0`,冻结 HEAD 上,4 发)**:正控
  PASS_ADAPTED(delta 5/5,回归 1150 逐字对齐基线,replay PASS)、
  nc_null → IMPL_INCOMPLETE(0/5)、nc_regression_break →
  REGRESSION_BROKEN(5/5 + 回归破坏)、nc_instrument_tamper →
  INSTRUMENT_TAMPERED(0/5),`--selftest` SELFTEST OK;
- **宿主幂等复验**:批前(15:00Z)、F0 电池后、批后三轮 verify-only
  全绿(8042:354 条构造自证恰好相等;三宿主总闸 ok=true);封存池
  零写;任务包自 `ba77070` 零改动(批后 git 核对);
- **两道硬门逐发重审**(K6/K12 转红→更新,按钉上旧文指示):oracle=
  UPSTREAM_OWN_TEST_SUITE、host=PRISTINE,旁挂 2 行机械转录冻结预注册
  (`run_classifications.jsonl` 29 行);K6/K12 钉更新为分母 **8** /
  分子 **2**(仍恰好等于),18 钉全绿;
- 冻结点闸门:变异 217/217(`9b548fe26e4e.json`)+ 冻结前全量 950 绿
  / 20 skip / exit=0(点计数);收口全量见收口提交信息;
  `check_public_claims` `{"ok": true}`。

## 6. 备注

- 两发 J7:本形态无上游采纳语义,U1–U4 不在场;
- t1 端到端彩排(EXPLORATORY_UNPREREGISTERED,预注册附录一第 2 条)
  六项布线判据全绿后才开的批;彩排 verdict 不入任何口径;
- 后续(不在本批):NO_SUBMISSION 行为形态(30 调用打满未提交)是
  deepseek 侧首个可复核的行为观察 —— 是否值得在 WH/后续 HB 里配更长
  call 预算或提交提示语强化,属**新批预注册**议题,本批不改不补。
