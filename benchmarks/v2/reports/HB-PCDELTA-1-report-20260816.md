# HB-PCDELTA-1 批报(2026-08-16)

> **后加脚注(2026-08-17 晚,原文一字未改)· 本批结论不受影响,但"1 轮"
> 一词须防误读。**8042 上两发的 `rounds_run=1`(合约 `max_rounds=3`)
> **是 harness 停轮缺陷造成的上限,不是模型效率的证据** ——
> `repair_loop.py:162-169` 在公开面基线全绿的任务上第 1 轮结束必然停。
> 本批两发第一轮即 `PASS_ADAPTED`(gpt-5.5 30 调用 / gpt-5.6 20 调用),
> **停轮没有削减任何已达成的结果,PASS 结论与 delta 5/5 读数全部成立**;
> 只是"一轮即解"不可被引用为效率读数。详见
> `benchmarks/v2/reports/WH-PILOT-1-stop-report-20260817.md` §3 末段。

**本批唯一事实源**(预注册 §11)。测试模式:**HB**(Held-out Benchmark,
计分);预注册 `benchmarks/v2/preregistrations/HB-batch1-postcutoff-delta-prereg-20260816.md`
(判据主文一字未动,工程留痕见其附录一)。

## 0. 身份与冻结

- 任务形态:post-cutoff delta(父提交树交付 + 上游 PR statement 为
  prompt + PR 自带新测试为隐藏 oracle,D1 严口径 UPSTREAM_OWN_TEST_SUITE)
- 受测模型:gpt-5.5(知识截止 2025-12-01)、gpt-5.6(2026-02-16),
  均早于三题 merge 下界 2026-06-01(§5 硬门,用户核录)
- **harness 冻结点:`0818d35`**(首发开跑 HEAD)。批期间
  `src/ scripts/ tests/ 任务包` 零改动(逐发 `harness_commit` 可查;
  冻结点后提交均为台账/文书)
- 判据裁定:`scripts/hb_batch_criteria.py HB-PCDELTA-1`(J1-J7 冻结版,
  含合成分支自考);数字出处 `gate_report.py --write` 与
  `check_public_claims`(`{"ok": true}`)

## 1. 六发结果(执行序 = 预注册附录一第 10 条)

| 序 | run_id | 任务 | 模型 | verdict | J3 | delta | 盲攻上界 |
|---|---|---|---|---|---|---|---|
| 1 | hb1-click-3581-20260816-193754 | click-3581 | gpt-5.5 | FAIL | DESIGN_MISMATCH | **0/3** | 0/3 |
| 2 | hb1-click-3581-20260816-194714 | click-3581 | gpt-5.6 | FAIL | DESIGN_MISMATCH | **0/3** | 0/3 |
| 3 | hb1-click-3407-20260816-201523 | click-3407 | gpt-5.6 | FAIL | IMPL_INCOMPLETE | **0/1** | 0/1 |
| 4 | hb1-click-3407-20260816-202000 | click-3407 | gpt-5.5 | FAIL | DESIGN_MISMATCH | **0/1** | 0/1 |
| 5 | hb1-sqlglot-8042-20260816-202453 | sqlglot-8042 | gpt-5.5 | **PASS_ADAPTED** | — | **5/5** | 4/5 |
| 6 | hb1-sqlglot-8042-20260816-204138 | sqlglot-8042 | gpt-5.6 | **PASS_ADAPTED** | — | **5/5** | 4/5 |

J 表纪律:delta 读数一律并排该题盲攻上界。六发全部一轮收束;公开面
全绿、回归(外层)全部 = 基线、policy 全 PASS、trace 链全完整、
postflight 全干净。两发 PASS 均过 clean replay(`mode=clean_adoption,
status=PASS`);FAIL 不重放属设计(重放只确证 PASS)。

## 2. 逐发实况

**序 1(3581×5.5)**:14 调用 / 149,307 in / 8,233 out / 212s。读源 +
翻 `tests/typing/typing_version_option.py`(父树旧物,无可捞)后实现
`click.custom_version_option(callback)`(4 文件 49 行),自写 CliRunner
冒烟绿,提交。隐藏三红:`test_custom_version_option[args0]/[args1]/
_receives_context`。名字在 prompt 里(PR 标题),语义只在隐藏测试 ——
callback 签名/上下文传递与上游真实 API 不合。

**序 2(3581×5.6)**:16 调用 / 155,193 in / 11,875 out / 349s。先做
git 考古:拿 statement 的 merge_commit SHA `git cat-file`,再
`git log --all`、`git remote -v`、`git fsck --unreachable` 扫游离对象,
**企图捞上游 PR 原文;密封交付顶住**(会话副本 = harness 自造单提交仓
`rp-host S0 baseline`,无远端无游离对象;bench 宿主本身无 `.git`)。
转手写实现(5 文件 50 行),附 mypy --strict / ruff / sphinx 自检 ——
卫生更好,隐藏三红与 5.5 逐个相同。

**序 3(3407×5.6)**:16 调用 / 176,341 in / 7,829 out / 274s。只改
`termui.py`(25 行)。delta 节点红,且 **oracle 铺入 PR post 测试后
delta 之外另有三红**(`test_prompt_cast_default` /
`_default_round_trips_through_type` / `_default_validated_by_type`)——
外层回归 1868=基线过(跑的是父树自带版本),PR 更新版测试不买账。
`test_h2_no_regression_broken` 红 → 按冻结判据落 IMPL_INCOMPLETE
(delta=0 时 REGRESSION_BROKEN 不适用)。

**序 4(3407×5.5)**:30 调用打满(LimitsExceeded)/ 478,286 in /
10,606 out / 289s。改 `termui.py`+`types.py`(60 行),公开面绿、
PR post 测试无额外红,唯 delta 节点
`test_param_type_input_parameter_defaults_at_runtime` 红 →
DESIGN_MISMATCH。本批最贵一发。

**序 5(8042×5.5)**:30 调用打满 / 556,973 in / 7,300 out / 1002s。
只改 `sqlglot/lineage.py`(98 行)。**9/9 全绿(delta 5/5)+ 回归
1150=基线 + clean replay PASS → PASS_ADAPTED**。

**序 6(8042×5.6)**:20 调用干净提交 / 389,921 in / 10,477 out /
1075s。只改 `sqlglot/lineage.py`(76 行)。同样 **PASS_ADAPTED**。

## 3. 批级读法(记录,不外推)

- **紧题上模型 = 盲攻上界**:3581 双模型 0/3、3407 双模型 0/1,与准入
  盲攻完全同剖面 —— prompt(PR statement)在这两题上未提供可将 delta
  语义猜中的增量信息;记忆通道(post-cutoff)与物证通道(序 2 git
  考古被密封挡回)均无迹象。
- **松题上模型 > 盲攻**:8042 盲攻 4/5(唯一判别节点不中),两模型带
  statement 全 5/5 —— statement 携带的实现指向在该题足以补上判别节点。
  这与准入时"8042 是宽题"的判断一致(4/5 上界入池即为此意)。
- **模型间差异**:结论层面零差异(逐题同落点);过程层面 5.6 更倾向
  取证与工程卫生(git 考古、mypy/ruff/sphinx),5.5 更快更省。
  样本 n=1/题/模型,**不做任何强于"记录"的声明**。
- 序 3 与序 4 同题异 J3:5.6 的实现连 PR 更新版周边测试都破
  (IMPL_INCOMPLETE),5.5 的实现周边全绿唯判别节点不中
  (DESIGN_MISMATCH)—— J 表按冻结优先级裁,无人工干预。

## 4. 成本封套(上限:≤3.6M in / ≤480K out / ≤6h / 运行数 ≤12)

| 量 | 实用 | 占比 |
|---|---|---|
| tokens in | 1,906,021 | 52.9% |
| tokens out | 56,320 | 11.7% |
| 墙钟 | 53.4 min | 14.8% |
| 运行数 | 6(计分)+ 1(中止不计) | 6/12 |

## 5. 批期间 harness 事件(§11:停修 → 钉死 + 附录 → 复测 → 继续)

**首发中止一次(不计分、不入台账、不计封套)**:量具三分法塌陷 ——
skipped 被当成 failed,26 个平台性 skip 变成 26 个凭空失败包喂给模型,
预算被引去追鬼。当场 pkill,修复(三分法 + `public_skipped` 留痕 +
同病扫查两处:v1 路共享口径、负控电池反向假绿)、钉死(G9 系列 +
M73a-c/M74a-f,变异闸门 **204/204** 声明归因)、F0 电池 R3 全量重跑
(12 发四形态零例外,正控读数与契约基线逐字对齐)后,**该发从零重跑**
(即序 1)。全程见预注册附录一第 11 条。批期间(冻结点后)零事件。

## 6. 完整性

- 宿主幂等复验(批后):三宿主 verify-only 逐字节对得上(139/152/354),
  六发未污染 bench;封存池零写
- `check_public_claims` `{"ok": true}`;台账 +6 计分行;分类旁挂
  (`run_classifications.jsonl`)+6 行 HB(两道硬门:
  `oracle_authorship=UPSTREAM_OWN_TEST_SUITE`、`host=PRISTINE` 父树;
  旁挂为冻结预注册的机械转录,落笔时点在 basis 里自曝)——
  `v2_gate.json` **heldout_model_evaluation_runs 0→6、heldout_passes
  0→2,是本仓第一批非零 held-out 能力读数**;K6/K12 实台账钉按其旧文
  自身指示同步更新(钉恰好 6/2,下一批落账必转红逼显式重审);
  答案零入库(statement/controls 均经泄漏扫查)
- 逐发 `harness_commit=0818d35...`、trace 链 sha 完整、
  `main_dir_integrity=ok`
