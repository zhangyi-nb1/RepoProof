# M4 模型对比批(DeepSeek):M4-MODEL-COMPARE-DS-1 · 2026-08-23

## 一、目的与性质

批次一(M4-TOOL-ONBOARDING-1)12 任务已在 gpt-5.5×mini-swe 下 12/12
VERIFIED_TOOL_READY。本批把**同一批冻结任务包**(题面/oracle/预算盒
零改动)换 provider 重发一遍,回答:同样的产品闸门下,第二家模型的
通过率与失败形态是什么。

- 这是**对比观察**,不是交付:发次不 export、不 register、不覆盖
  `~/tools/` 已交付工具(交付版本的谱系锚定在 gpt-5.5 发次上不动)。
- 口径 `test_mode=PRODUCT`、`run_purpose=PRODUCT_MODEL_COMPARE`
  (bench_records.py 显式登记,不充闸门、不计模型能力、不进 held-out)。
- 产品主张在本批的读法:**判定保证而非成功保证**——弱模型失败属预期
  数据,闸门拦下即产品行为正确;不得以"提高通过率"为由修任务或重发。

## 二、冻结配置(开跑前定,跑中不改)

| 轴 | 值 | 依据 |
|---|---|---|
| 任务集 | 批次一 12 任务包原样(task_id 见 §三) | 题面冻结,sha256 sidecar 在案 |
| 模型 | `deepseek-v4-pro` | `.env` REPOPROOF_DEEPSEEK_DEFAULT |
| 通道 | `REPOPROOF_PROVIDER=deepseek-native`(P-D 直连) | agent_run.provider_from_env |
| profile | `DS-NATIVE-HIGH-DET`(temp 0) | §55 两候选无正选裁决;取确定性侧,
  与产品线复现审美一致。**边界如实**:MAX-OFFICIAL-LIKE 未测,本批结论
  不外推到该 profile |
| 后端 | mini-swe(缺省,不动) | D3 裁决;DSH 不资格化不涉 |
| 发制 | 每任务一发,失败=数据;仅 HARNESS_FAILURE/BLOCKED(系统层)
  允许排障后补发并分行注记 | 循环 vs 闸门对齐律 |
| 批帽 | 名义 in 6,000,000 触顶即停 | 与批次一同帽 |
| 金丝雀 | 第一发(python-slugify)跑完先停,验台账
  model/provider/provider_config_hash 与 trace 回显确为 deepseek-native
  ×deepseek-v4-pro(30 秒复验取证式,防静默换模),取证过再放行其余 11 发 | 模型降级历史事故 |

## 三、任务清单(= 批次一冻结清单,顺序同)

tool-python-slugify-tool-v1 / tool-ftfy-tool-v1 / tool-unidecode-tool-v1 /
tool-pyyaml-tool-v1 / tool-json5-tool-v1 / tool-markdown-tool-v1 /
tool-pygments-tool-v1 / tool-tabulate-tool-v1 / tool-humanize-tool-v1 /
tool-chardet-tool-v1 / tool-python-dateutil-tool-v1 / tool-feedparser-tool-v1

(chardet/dateutil/feedparser 的任务包为批次一重建版;12 包均带
`.sha256` sidecar,本批零改动。)

## 四、报告口径

按任务成对报:`gpt-5.5 verdict` vs `deepseek verdict`;失败侧必须给
failure_class 与 gate_reasons 摘录。汇总:通过数、失败形态分布、
调用/tokens 对比。驱动与汇总唯一出口 `scripts/m4_model_compare.py`。

## 五、勘误区(append-only)

- 2026-08-23 §二金丝雀后曾以单进程全批驱动开跑,操作员误判后台超时风险
  TaskStop 拦腰:ftfy 首发(181746)round1 中被杀,tokens 已烧未入账,
  已补 BLOCKED(CRASHED_INTERNAL)报告;此后改逐发驱动,ftfy 按 §二
  系统层条款补发(结果 FAIL,为正式对比数据)。
- humanize 首发被 H9-a 拦截(/tmp/sizesx=批次一备题期残留,0 tokens),
  清残留后补发(PASS)。
- 批帽:末发(feedparser)发出前累计 5,531,552 未触顶,发出后总计
  6,015,425,超帽 15,425(0.26%)——"触顶即停"按发前判定执行,如实记。
