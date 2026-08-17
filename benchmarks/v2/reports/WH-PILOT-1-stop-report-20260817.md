# WH-PILOT-1 停批报告(2026-08-17)

> **本批作废。**两发如实入台账,**不作臂间判决** —— 构念在序 1 就已失效,
> 任何 GAIN / NO_GAIN / ADVERSE 读数都不可释。计划 6 发,实跑 2 发即停,
> 花费止于 **2,294,898 / 12,000,000 读入(19.1%)**。剩余 4 发**不补发**
> (用户裁定 2026-08-17)。

- **模式:WH**(TESTPLAN §11);预注册
  `WH-PILOT-1-harness-gain-prereg-20260817.md`,**冻结点 `6a671bf`**
- 变异证据 `d946bcb`:**237/237 全捕,声明归因 237,逃逸 0**
  (`docs/evidence/mutation_gate/6a671bf26f5f.json`)
- 通道:deepseek-native / deepseek-v4-pro / **DS-NATIVE-HIGH-DET**
  (`provider_config_sha256 = 58d4388e…`,两臂逐字相同)
- 停批依据:**§6 停批线第 2 条**(判据/构念缺陷在批中暴露 → 整批作废)
- 分类旁挂:两发均 `counts_toward_model_capability=false` /
  `counts_toward_heldout_benchmark=false` / `counts_toward_mechanism_effect=false`
  / `counts_toward_treatment_effect=false`;`classification_timing =
  **POST_HOC_TAXONOMY_CORRECTION**`(附录二预写的是 `mechanism_effect=true`,
  作废是看到结果之后的改动,**自曝,不伪装成预注册**)

---

## 1. 两发实况(数字全部出自台账与 bundle,非记忆)

| 序 | 臂 | 调用 | 轮 | patch 字节 | delta | 能力 | 读入 | 产出 | 墙钟 | 终止 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | guided | 30 | **1/3** | **0** | **0/5** | 4/9 | 551,370 | 6,997 | 574.2s | `LimitsExceeded` |
| 2 | minimal | 55 | 1/1 | 5,486 | **5/5** | 8/9 | 1,743,528 | 37,589 | 975.1s | `BUDGET_EXHAUSTED` |

- 两发 `verdict=FAIL`;盲攻上界 **4/5**(净判别余量 1 节点)
- 序 1 失败节点 = 五个 pivot 系 delta 全红;序 2 唯一失败节点 =
  `test_h2_no_regression_broken`
- 序 2 的 `regression 1150/0 = 基线`与 J3 判 `REGRESSION_BROKEN` **不矛盾**:
  宿主回归套与隐藏 oracle 的回归检查是**两套测试集**。agent 碰坏的是
  上游同文件既存邻居 `TestLineage::test_multiple_pivoted_sources`,
  宿主套里没有它。**此处非判据缺陷**,已核。

## 2. 致命发现:停轮规则在公开面基线全绿的任务上必然误停

`src/repoproof/adoption/repair/repair_loop.py:162-169`:

```python
if (not result.failed_nodes and result.collected_ok
        and cp.passed > 0 and cp.score >= best.score
        and not result.fatal_violations):
    stop = STOP_ALL_PUBLIC_PASS   # "all_public_green_pending_verification"
    break
```

**这个条件不看 `result.exit_status`,也不看有没有交付物。**

HB 任务族的公开面(宿主回归套)**在基线就是 1150/1150 全绿** —— delta 能力
藏在隐藏 oracle 里,公开面根本不表达任务是否完成。于是 agent 只要没把绿的
弄红,第 1 轮结束就必然命中"公开面全绿 → 收工"。

序 1 的 `repair.round.end` 是决定性证据:

```json
{"exit_status": "LimitsExceeded", "public_passed": 1150, "public_failed": 0,
 "round": 1, "fatal_violations": [], "scope_change": false}
```

`gate.verdict` 同发:`"adaptation_present": false`。

**读法:agent 被调用上限掐断在半途、一个字节都没交,循环却判"公开面全绿,
可以收工了"。** 失败方向是最危险的那一侧 —— 早停看起来像成功。

### 2.1 量化后果:引导臂只拿到自己合约的三分之一

契约 `benchmarks/v2/tasks/hb1_sqlglot_8042/contract.yaml`:

```yaml
budgets:
  semantics: per_round
  max_rounds: 3
  max_model_calls: 30
  max_input_tokens_total: 600000
```

| | 合约总额 | 实际送达 | 送达率 |
|---|---|---|---|
| guided | 3 × 30 = **90 调用** / 1.8M | **30 调用** / 551,370 | **33%** |
| minimal(等总额变换后) | 1 × 90 = **90 调用** / 1.8M | 55 调用 / 1,743,528 | 61%(撞读入墙) |

`effective_budgets()` 的等总额换算本身**没错**(已单独钉死),错的是引导臂
的 2、3 轮被停轮规则吃掉了,于是"等总额"设计在盘上变成了 **30 vs 90**。

### 2.2 引导臂的处理根本没送达

WH 的引导面按 D4 定义恰是四件,逐件核对序 1:

| 差异部件 | 是否生效 | 盘上证据 |
|---|---|---|
| 多轮编排 | **否** | `rounds_run: 1`(合约 3) |
| 每轮结构化失败包 | **否** | `repair.round.start {"packets": 0}`;第 2 轮从未发生,packets 恒 0 |
| 最佳态回滚 | **否** | `rolled_back_rounds: []`、`best_round: 1` |
| 轮抬头文本 | 是 | 唯一生效的一件 |

**四件里三件从未启动。**两臂唯一实际的差别是**送达的调用量:30 vs 55**。

判据脚本 `wh_batch_criteria.py` 若照单跑会算出 `ADVERSE` —— **算术没错,
但那个数测的是"三倍资源",不是"引导"**。这正是 E 轨四分类里的
`TREATMENT_NOT_DELIVERED`(引导臂)与 `BLOCKED_BY_INVALID_CONSTRUCT`
(对照臂)。

### 2.3 安全面与分池两头都仍然干净(缺陷不在这儿)

| 指纹 | guided | minimal | |
|---|---|---|---|
| `contract.frozen` sha256 | `15591cb6…` | `15591cb6…` | 同 |
| `verifier_fingerprint` | `ef608936…` | `ef608936…` | 同 |
| `executor_semantics_fingerprint` | `a9d5bb60…` | `a9d5bb60…` | 同 |
| `instrumentation_fingerprint` | `1266aa92…` | `1266aa92…` | 同 |
| `provider_config_hash` | `58d4388e…` | `58d4388e…` | 同 |
| `budget_profile_hash` | `fa2b4a71…` | `7f8b51a0…` | **异(设计如此)** |
| `context_profile_hash` | `e8455a2f…` | `110e4d57…` | **异(设计如此)** |
| `tool_profile_hash` | `0ac0594c…` | `4bacf81b…` | **异(设计如此)** |
| `exec_generation` | `E0` | `E0-H0` | **异(设计如此)** |

安全面逐字相同、分池三面指纹按设计分开、`policy=PASS`、
`main_dir_integrity=ok`、postflight 零残留 —— **本批的失败与安全网无关**,
纯粹是停轮规则把处理掐死在送达之前。

## 3. HB-DSENTRY-1 必须挂警示:那两个读数量的是上限,不是这个模型

`benchmarks/v2/reports/HB-DSENTRY-1-report-20260817.md` 发布了
deepseek-v4-pro 在 8042 上 **0/5 × 2 发 `NO_SUBMISSION`**,并据此写下
"入门档两 profile 均未过"。

盘上核对:那两发与本批引导臂**形状逐字相同**。

| | HB-DSENTRY-1 序 1 | WH-PILOT-1 序 1(guided) | WH-PILOT-1 序 2(minimal) |
|---|---|---|---|
| 模型 / profile | v4-pro / **HIGH-DET** | v4-pro / **HIGH-DET** | v4-pro / **HIGH-DET** |
| 契约 sha256 | 同 | 同 | 同 |
| `stop_reason` | `all_public_green…` | `all_public_green…` | `all_public_green…` |
| `exit_status` | `LimitsExceeded` | `LimitsExceeded` | 读入墙 |
| 送达调用 | **30**(合约 90) | **30**(合约 90) | **55** |
| patch 字节 | **0** | **0** | 5,486 |
| delta | **0/5** | **0/5** | **5/5**(高于盲攻上界 4/5) |

**同模型、同 profile、同任务、同契约哈希,唯一变量是送达的调用量。**
30 调用 → 0/5 且零字节;55 调用 → 5/5。

**结论:HB-DSENTRY-1 的"未过"是预算受限,不是能力受限。**那两发测到的是
harness 停轮规则造成的 33% 送达上限,不是 deepseek-v4-pro 在这道题上的
能力。该报告需挂警示,其读数不得再被引用为该模型的能力证据。

**波及 held-out 台账**(分母 8 / 通过 2):这两发计入了分母。修停轮缺陷后
需重跑才能恢复该题对 DeepSeek 的能力读数。

**HB-PCDELTA-1 不受影响但需一句脚注**:gpt-5.5(30 调用)/ gpt-5.6
(20 调用)两发均 `PASS_ADAPTED` 且同样是 `1/3` 轮 —— 它们第一轮就解决了,
停轮没坑到结论。但**那个"1 轮"是上限不是效率**,报告里若被读成"一轮即解"
的效率证据则是误读。

## 4. WH 需要换任务族:公开面基线必须是红的

WH 要测的是"多轮 + 失败包 + 最佳态回滚"值不值。这三件的触发前提都是
**公开面在基线是红的、且 agent 有机会把它弄绿**。HB 任务族的公开面基线全绿
(delta 藏在隐藏 oracle 里),从构念上就不可能让引导面启动 —— 这不是选错了
一道题,是选错了一整族。

**换族的硬判据(下一次 WH 预注册须冻结):**

1. **公开面基线必须红**,且红的节点就是任务要修的节点;
2. F0 冒烟须证明**引导臂真能跑满多轮**(`rounds_run > 1`)、
   **packets > 0**、且至少一发触发 `rolled_back_rounds != []` ——
   否则处理未送达,不许开跑计分发;
3. 两臂"送达调用量"须并排入表,**任何一臂送达率 < 80% 合约总额即停批**
   (本批若有这条,序 1 就会当场停,而不是跑完再判)。

## 5. 修与钉(本批作废后的待办,**不在作废批内顺手改**)

1. **停轮条件加送达前提**:`STOP_ALL_PUBLIC_PASS` 须同时要求
   `exit_status` 正常收敛(非 `LimitsExceeded`)**且**有交付物
   (`adaptation_present`)。当前条件只看公开面颜色。
2. **同病扫查**:凡以"公开面全绿"为停止信号的判断处,全部按同一结构钉
   (一份实现),不逐路钉行为 —— 这是 #43 / H7-g 同型教训。
3. **变异钉**:至少两枚 —— ①停轮条件退回不看 `exit_status`;
   ②退回不看 `adaptation_present`。两枚都须被**声明钉**当场抓获。
4. **潜伏隐患(本批未发作,记录备查)**:`host_guided.py:2802` 把
   `"guided": True` 硬编入台账行 —— 它记的是"走了 host_guided 这条 runner",
   **不是臂**。最小臂在盘上也写着 `guided=true`。当前判据脚本按
   `harness_mode` 派生的 `arm` 分臂、不碰该字段,故未发作;但任何按
   `guided` 分组的分析都会**静默把两臂并池**。建议改名或按臂赋值,并补钉。

## 6. 本批的正面结论(不是白跑)

1. **等总额变换、分池、安全面恒等三件都在真模型上实测通过**,不是声明:
   两臂契约哈希/验证器/执行器/量具指纹逐字相同,三面 profile 指纹按设计分开,
   `E0` vs `E0-H0` 代际正确落位。
2. **停轮缺陷是被 WH 的对照臂逼出来的**。若不设最小臂、不做等总额换算,
   30 调用打满零提交会继续被读成"模型不行"。**对照臂的价值在这里兑现了一次。**
3. **判据脚本的两处缺口(冒烟/计分分池的失败方向、泄漏护栏)在开跑前补上了**,
   变异闸门 233 → 237。这些不随本批作废。

---

*本报告的数字全部出自 `benchmarks/v2/runs.jsonl`、各 run 的
`repair/summary.json` / `trace.jsonl` / `report.json` 与
`benchmarks/v2/tasks/hb1_sqlglot_8042/contract.yaml`,无一凭记忆。*
