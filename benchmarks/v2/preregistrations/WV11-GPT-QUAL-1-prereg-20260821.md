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
