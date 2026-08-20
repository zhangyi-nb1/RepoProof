# V2GEN-GPT-BASE-1 预注册:构造法 v2 代际 × GPT 基线批(2026-08-21)

**测试模式:E1(单臂观察批,GPT×mini-swe×hb1-sqlglot-8042-v2,total 语义;
F0/F0b 冒烟不计)。冻结点 = 本文件所在提交;开跑后判据一字不改。**

授权链:用户 2026-08-21"继续"(承接"那为我开始修复吧…宗旨是提高项目
harness下GPT模型的成功率以及其他效率"修复清单 R1/R2;设计蓝图
docs/R1R2-DELTA-V2-DESIGN.md 已于 95eced5 冻结,本批执行其 §4 ⑤-⑦)。

## 1. 研究问题(机制三问,设计 §4⑦ 预写)

构造法 v2(base 版 tests/test_lineage.py 留树可运行,回归网 1150→1193)
+ prompt v2(R5 隐藏节点名单宣示 + R6 回归网/保守性教导)下:

1. **OLD_INTACT 类回归破坏是否消失** —— unpivot_with_alias_columns
   (base==post 旧测试,v1 下 5/12 发被砸)现在模型可见可自查;
2. **delta 修复是否仍达成** —— v1 基线 gpt-5.6 曾 9/9 PASS、gpt-5.5 曾
   8/9 唯欠回归检查;
3. **multiple_pivoted_sources 是否仍被砸** —— STRIPPED_NEW(green-on-
   parent 新增)结构性不可见,是答案承载不可约盲区;R6/R5 教导面是唯一
   合法杠杆。仍砸 → harness 侧到边界,病灶如实转模型/任务构造侧。

**不回答**:模型能力(seen task,n=1/模型)、v1 vs v2 数值化 A/B(不同
任务版本不合池;跨代差是机制读数不是能力读数)、DSH 臂(本批只跑 H0)。

## 2. 组合与同一性

- 臂:H0 = mini-swe 环 × openai-compatible 通道(REPOPROOF_API_BASE/KEY/
  MODEL 注入,不设 REPOPROOF_PROVIDER),rt-inprocess-v1。
- 契约:`benchmarks/v2/tasks/hb1_sqlglot_8042_v2/contract-e1-total.yaml`
  —— 与 v1 e1-total **预算四轴逐字同值**(calls 500 逃逸后备 / commands
  300 / 墙 60 分 / in 1.8M / out 240K,total 语义);差异恰为身份(-v2/
  hb-delta-v2)、宿主(v2 树,基线 1193)、教导(R5/R6)。
- 宿主:hb1-sqlglot-8042-v2(构造法 v2,锁写 + host_digest 入清单);
  发车绊线 `check_host_digest.py sqlglot-8042-v2` 每发前后。
- 投影:`REPOPROOF_CONTEXT_PROJECTION` **不设**(off)—— WV11 资格 FAIL
  的直接后果,v2 代际不默认开投影。
- 对照(方向性,不合池):GPT-H0-E1TOTAL-1(冻结 b6b10e6)v1 基线两发
  (gpt-5.5 FAIL 8/9 / 347K;gpt-5.6 PASS 9/9 / 427K)。

## 3. 分类旁挂(逐计分发)

`test_mode=E1` · `run_purpose=MECHANISM_ABLATION` · `task_seen=true` ·
counts_toward_{model_capability, heldout_benchmark, mechanism_effect,
treatment_effect} **全 false**(单臂无治疗;机制口径不计防被读成跨代
回填)· `treatment_assigned=false` · assistance_level=
BOUNDED_PUBLIC_REPAIR · host_modification_mode=PRISTINE ·
oracle_authorship=UPSTREAM_OWN_TEST_SUITE · PRE_REGISTERED。
F0/F0b 冒烟不落分类行(台账行如实)。

## 4. 发次序与上限

1. **F0**:v2 × `--fake positive`(答案 patch)→ 期望 PASS_ADAPTED
   (delta 全绿 + 回归零破坏 + 重放一致)—— 验 v2 判卷管线正向;
2. **F0b**:v2 × `--fake control:nc_regression_break`(答案 + 窄破坏)→
   期望 FAIL / REGRESSION_BROKEN —— 验 v2 判卷失败侧真能红对桶
   (v2 新 lay 分支的失败侧负控);
3. 发 1:8042-v2 × `gpt-5.5` × H0 total(run_order 1);
4. 发 2:8042-v2 × `gpt-5.6` × H0 total(run_order 2)。

计分 2 发,**运行上限 5**(F0/F0b + 2 计分 + 1 缺陷重跑位)。停规:
F0/F0b 任一不达期望 → 停修,修复后该冒烟从零重跑,不进计分;
instrument 缺陷 → 停修重跑不回填;绊线红 → 全停。

## 5. 封套与判读边界

- 封套:计分运行 ≤3(含重跑位);墙钟累计 ≤1.5h;in ≤2M tok /
  out ≤0.3M tok;超封套中止请示。
- 裁决只走隐藏 oracle 九道 + 验证器 + 干净重放 + Completion Gate;
  台账 cost 如实(缺读数 UNKNOWN);健康探(GET /models,Authorization
  经 env)每计分发前 200 且目标模型在列。
- 判读上界:单任务 seen、n=1/模型、新代际首批 —— 三问只作机制方向
  读数;multiple_pivoted 改善(若有)归 R2 教导面不归 R1(它够不着,
  设计 §5 预写);不与 v1 数值合池;不作 GPT 能力/成功率主张。

---

## 附录:批结果转录(2026-08-21,机械转录不改判据)

冻结点 44e4c69;工程 269ae23(门 275/275 @ 269ae23,证据 cc685d1)。
发序照 §4,绊线每发前后全绿,健康探 200 且双模型在列。

| 发 | 组合 | 判决 | 读数 |
|---|---|---|---|
| F0 | fake positive | **PASS_ADAPTED**(delta 5/5) | 墙 557s;期望达成 |
| F0b | fake nc_regression_break | **FAIL / j3=REGRESSION_BROKEN**(delta 5/5,回归 1138/1193) | 墙 752s;期望达成 |
| 1 | gpt-5.5 × H0 | **PASS_ADAPTED**(delta 5/5,回归 1193/1193)+ replay PASS | 37 调用 / in 696,072(cache_read 619,520=89%)/ out 9,700 / agent 墙 9.1 分 |
| 2 | gpt-5.6 × H0 | **PASS_ADAPTED**(delta 5/5,回归 1193/1193)+ replay PASS | 26 调用 / in 428,304(cache_read 386,048=90%)/ out 15,134 / agent 墙 13.5 分 |

封套核销:计分 2/≤3;墙累计 58.5 分 ≤1.5h;in 1.124M ≤2M;out 24.8K
≤0.3M —— 全内,零重跑位动用。

**机制三问答(方向读数,n=1/模型,不作能力主张)**:

1. **OLD_INTACT 消失:是。**两发回归 1193/1193 零破坏,隐藏面非 delta
   节点零红(PASS_ADAPTED 语义含隐藏回归干净)——v1 下 5/12 发被砸的
   unpivot_with_alias_columns 在 v2 两发全存活。
2. **delta 仍达成:是。**两发 delta 5/5;v1 同轴 FAIL 8/9(唯欠回归
   检查)的 gpt-5.5 在 v2 转 PASS_ADAPTED。
3. **multiple_pivoted 未再被砸。**v1 下 12/12 REGRESSION_BROKEN 发全砸
   的 STRIPPED_NEW 盲区项,v2 两发全存活。按设计 §5 预写归因:改善归
   R2 教导面(R5 名单 + R6 保守性),不归 R1(其内容 v2 下仍不可见,
   R1 够不着)。单臂合并治疗,R1/R2 内部不可再分解 —— 如实记。

消耗形状(方向对照,不合池):gpt-5.5 in 347K→696K(2.0×,调用
23→37)——为跑满 1193 回归网付费,买来 FAIL→PASS;gpt-5.6 427K→428K
(≈1.0×,24→26)——同消耗吸收更大可见树并保持 9/9。R5 仪器线上第二
批读数:cache_read 89-90%(高于 WV11 的 37-50%),名义 in 的有效成本
远低于面值。

批性质注记:本批 2/2 PASS 是**机制修复验证**(harness 修复线 R1-R6 全
链后首批),不是模型能力读数;task seen、单任务、n=1,不外推。
