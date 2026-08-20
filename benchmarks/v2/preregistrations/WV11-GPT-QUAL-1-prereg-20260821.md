# WV11-GPT-QUAL-1 预注册:window-v1.1 投影 × GPT 在线资格批(2026-08-21)

**测试模式:AR(仪器/观测策略资格审;不计模型表现)。冻结点 = 本文件
所在提交;开跑后判据一字不改。**

授权链:用户 2026-08-21"那为我开始修复吧,过程中视情况而修改方向,宗旨
是提高项目harness下GPT模型的成功率以及其他效率"(修复清单 R4)。背景:
window-v1.1(S2' 滑动窗口)在 deepseek 侧有六发在线基线证据(输入降
12%),在 GPT 组合上**从未激活过**;GPT 端点输入全价(R5 探针:同前缀
重打不报任何 prompt 缓存细目),投影折叠对 GPT 是**真钱**上的输入削减。

## 1. 研究问题(只此一问)

`REPOPROOF_CONTEXT_PROJECTION=window`(window-v1.1)在 **H0 mini-swe ×
openai-compatible × GPT** 组合上:投影是否如约激活(projection.applied
事件、折叠计数>0),且输入 token 相对同模型 off 基线方向性下降?——为
"GPT 代际(R1/R2)是否默认开投影"的后续决策提供资格证据。

**不回答**:模型能力(seen task,四口径全 false)、成功率变化(n=1/模型
撑不起)、与 deepseek 投影读数的数值比较(跨端点 usage 语义存疑,
DQ-GPT-SHIM-1 附录二警示)、DSH 臂(投影只接在 TokenBudgetedModel,
DSH 臂不经它)。

## 2. 组合与同一性

- 臂:H0 = mini-swe 环 × openai-compatible 通道(REPOPROOF_API_BASE/
  KEY/MODEL 注入,不设 REPOPROOF_PROVIDER),`backend_id=mini-swe`、
  rt-inprocess-v1;与 GPT-H0-E1TOTAL-1 的**唯一差异** =
  `REPOPROOF_CONTEXT_PROJECTION=window`(单旋钮)。
- 同前批:契约 `contract-e1-total.yaml`(四轴逐字同值)、任务包
  sqlglot-8042、宿主 base、host prompt、wheelhouse、验证器/隐藏 oracle/
  干净重放/Completion Gate。preflight:action_protocol=native、
  temperature=0、REPOPROOF_CALL_TIMEOUT_S 缺省、obs_cap 缺省。
- R5 仪器已入库(53bfb00):端点报缓存细目则 report.json .agent 记
  `cache_read_input_tokens`,不报则缺席(不造零)。

## 3. 分类旁挂(逐发次)

- `test_mode=AR` · `run_purpose=OBSERVATION_POLICY_QUALIFICATION`
  (本批新登记于 bench_records.QUALIFICATION_PURPOSES ——
  **代码级不充闸门**,M94a 变异钉死;散文说不算,代码算了)
- `task_seen=true`;counts_toward_{model_capability, heldout_benchmark,
  mechanism_effect, treatment_effect} **全 false**
- `treatment_assigned=false`(资格审不是治疗臂,无同批对照)·
  assistance_level=BOUNDED_PUBLIC_REPAIR · host_modification_mode=
  PRISTINE · oracle_authorship=UPSTREAM_OWN_TEST_SUITE

## 4. 资格门(W1–W4;全过才 QUALIFIED,任一不过如实 FAIL)

- **W1 仪器健康**:发车绊线(`check_host_digest.py sqlglot-8042`,每发
  前后)全绿;端点健康探(GET /models)200;零缺陷重跑。F0(--fake
  positive × 投影 env on)只验管线不受该 env 破坏,**不覆盖投影本身**
  (fake 路径不经 TokenBudgetedModel,如实声明);投影行为由
  tests/test_window_projection.py 离线钉死 + deepseek 六发在线先例背书。
- **W2 激活**:每发 trace.jsonl 含 ≥1 行 `event=="projection.applied"`
  且 payload.policy=="window-v1.1",且至少一行 payload.folded_messages>0。
  超窗仍零折叠 → 不合格;全程消息数未超窗(无折叠机会)→ INCONCLUSIVE
  如实记,不算过。
- **W3 输入方向**:该发 report.json `.agent.input_tokens` < 同模型 off
  基线(gpt-5.5: 347,367 @172546;gpt-5.6: 427,149 @174105;n=1 对 n=1,
  只作方向读数)。逆向不定罪仪器,但 QUALIFIED 不发。
- **W4 判决如实**:PASS/FAIL **不是门**;门是判决与 9 道隐藏 oracle
  读数一致落台账、干净重放照跑(重放走适配树,不重放 agent,不受投影
  影响)。

## 5. 发次序与上限

F0:8042 × `--fake positive` × `REPOPROOF_CONTEXT_PROJECTION=window`。
计划 2 发,**运行上限 3**(1 缺陷重跑位):

1. 8042 × `gpt-5.5` × H0+window(run_order 1);
2. 8042 × `gpt-5.6` × H0+window(run_order 2)。

停规:instrument 缺陷 → 停修 → 该发从零重跑,不回填;绊线红 → 全停。

## 6. 封套与判读边界

- 封套:运行 ≤3;墙钟累计 ≤1.5h;in ≤2M tok / out ≤0.3M tok;超封套
  中止请示。
- 判读上界:单任务 seen、n=1/模型、资格审语义 —— 只回答"投影在 GPT
  组合上激活且方向对不对",不得读作能力/成功率/跨模型结论;QUALIFIED
  只背书"后续代际可讨论默认开投影",不自动改任何默认;不与 deepseek
  的 12% 数值合池。
- 裁决只走隐藏 oracle + 验证器 + 干净重放 + Completion Gate;台账
  cost 列如实(litellm 读数缺失时 UNKNOWN)。

## 附录一(2026-08-21 · 批毕机械转录:F0+2/2 照冻结序跑毕,批关闭)

### 三发结果

| 发 | 模型 | 判决 | 调用 | in tok(其中 cache_read) | out | agent 墙 |
|---|---|---|---|---|---|---|
| F0(023054) | fake-scripted:positive | PASS_ADAPTED + replay PASS(smoke,不计) | — | — | — | — |
| 1(024123) | gpt-5.5 | FAIL 8/9(唯欠 test_h2_no_regression_broken) | 48 | 740,587(370,176 = 50%) | 9.3K | 9.5 分 |
| 2(025641) | gpt-5.6 | FAIL 8/9(唯欠同一道) | 44 | 641,851(239,616 = 37%) | 17.0K | 13.7 分 |

零缺陷重跑;绊线(digest+双锁)每发前后全绿;健康探每发前 200 且目标
模型在列。封套决算:运行 3/3 ≤3;墙钟累计 ≈50 min ≤1.5h;in 1.38M
≤2M;out 26.3K ≤0.3M。全内。

### 资格门判定:**FAIL —— QUALIFIED 不发**

- **W1 仪器健康:过。** F0 绿(投影 env 不破管线;如实声明其不覆盖投影
  本身);绊线/健康探/零缺陷如上。
- **W2 激活:过。** 两发各 39 枚 `projection.applied`,payload.policy
  全部 "window-v1.1",folded_messages 最高 11(单枚省 61,116 chars)——
  旋钮在 GPT 通道上确实接通并折叠。
- **W3 输入方向:不过(两发全逆)。** gpt-5.5:740,587 = off 基线
  347,367 的 **2.1 倍**;gpt-5.6:641,851 = off 基线 427,149 的 **1.5
  倍**。机制读数(n=1 级):折叠没有降低单发总输入,反而伴随调用数近
  翻倍(23→48 / 24→44)—— 与"折走的上下文迫使模型重读"的解释相容。
- **W4 判决如实:过。** 两发 FAIL 均由 CapabilityVerifier 9 道读数落
  台账;FAIL 不触发重放(重放仅 PASS 侧),照判据。

### 附带读数(判读上界内,n=1 级)

- **行为侧**:off 基线 9/9 PASS 的 gpt-5.6 开投影后转 FAIL,砸的正是
  剥离文件两节点(unpivot=STRIPPED_OLD_INTACT + multiple_pivoted=
  STRIPPED_NEW);gpt-5.5 砸 unpivot 一节点。可见树桶仍为零(21 发累计)。
  基线 gpt-5.6 的过关行为特征(主动探 test_lineage.py 缺失)在投影下
  未再现 —— 方向与"折叠丢了关键线索"相容,n=1 不定罪。
- **仪器侧(R5 首批线上读数)**:端点在真实多轮会话里**报 prompt 缓存
  细目**(cache_read 37-50%)—— 同日冷探针(两发同前缀)的"不报缓存/
  全价输入"读数只对冷测成立,证据文件 wv11-live-cache-reporting-
  20260821.json 载修正;不造零纪律使该修正自然落地(探针负读数未被
  写死成 0)。
- **结论(资格审语义)**:window-v1.1 **不迁移**到 GPT×mini-swe 组合
  (S2' 的 deepseek 六发降 12% 是彼组合的局部事实)—— 观测策略旋钮属
  组合特定,R1/R2 新代际不默认开投影;若再议须另立资格批。
