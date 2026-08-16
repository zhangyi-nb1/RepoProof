# 预注册:E1-S2′ 消融 2 —— gpt-5.6 臂补估(2026-08-17,冻结后不改)

**批次名 `E1-S2PRIME-ABLATION2-20260817`(批 15)。冻结点 = 本文件所在
提交。**

## §0 解挂与由来(为什么现在跑)

- E 轨终结报告 §6 把"S2′ 补跑 gpt-5.6 臂"**挂起**("有资格跑,但要花
  额度…不列入主线")。用户 2026-08-17 指令:**"现在开始忽略 DeepSeek
  模型的部分,完成计划中与 GPT 模型相关的部分,我要尽快推进指导报告的
  优化措施,落实优化效果"** —— 即解挂令与起批授权(§11)。
- 批 14 结论原文:"再开必须有**新证据与新预注册**。" 本文即新预注册;
  新证据 = 送达修复:`_cmd_of` 多命令按序对位(量具修复,折叠规则一字
  未动)+ 零模型重放 X1–X5 **五条全过**(预注册
  `S2prime-exposure-replay-prereg-20260814.md`,证据
  `docs/evidence/projection_exposure/replay-E1-S2prime.json`):gpt-5.6
  三条历史轨迹激活 0/0/0 → **29/12/8**,X4 每格非零 3/3。
- 指导报告(`~/Downloads/deepseek_harness_repoproof_report.md`)中"上下文
  治理是主要杠杆"的判断,在 gpt-5.5 上已被批 14 证否(该动法),在
  gpt-5.6 上**从未被检验**(TREATMENT_NOT_DELIVERED ≠ 效应为零)——
  本批取第一份效应估计。

## §1 模式声明

**测试模式 E1**(TESTPLAN §11):结论**只覆盖机制,不覆盖模型能力**。
T2v5 是开发套件,批报不得写"gpt-5.6 变强/变弱了",只许写"S2′ 机制在
gpt-5.6 profile 上的效应"。不涉 WH/HB,不动 heldout 分母(K6/K12 不变)。

## §2 要回答的问题

送达修复后的 S2′ 滑动窗口(窗口=8,只折读取型,有损)作用于 gpt-5.6:

> 模型看不到窗口外旧读取正文之后,效率(累计输入)是否改善、行为是否
> 劣化(批 14 在 gpt-5.5 上测到:首轮公开分中位 14→3、命令 +20.8%、
> 输入仅 −3.9%)、撞预算墙是否缓解?

## §3 两臂设计(唯一变量 = 投影开关)

| 臂 | `REPOPROOF_CONTEXT_PROJECTION` | `exec_generation` | `context_profile_hash` |
|---|---|---|---|
| **A(对照)** | 未设(off) | `E0` | `e8455a2fb89744c5` |
| **B(处理)** | `window` | `E1-S2` | `309589b21611dfff` |

- 两臂 ctx hash 在 HEAD 复算,与批 14 **逐字相同**(配置意图未变)。
- **exec_fingerprint 现值 `5ef70e77652ffc72`** ≠ 批 14 的
  `1d103b28659e4504`(provider 通道与记账修复所致)→ 按 §2 规则 2,
  批 14 的任何发次(含其 gpt-5.6 A 臂)**不得**充当本批对照;
  **两臂都在 HEAD 现跑**。批 14 数字在批报里只作历史参照并注明指纹不同。
- 其余四面同:同 provider profile(gpt-5.6,openai-compatible)、同
  tool/budget profile、同 exec_fingerprint。window=8 本批不调(调 = 重
  预注册)。任务包 `t2_open_deep_research_v5` 自 `62d93f0` 零改动,批
  期间一字不动(§39)。

## §4 gpt-5.5 不重测(边界,先声明)

批 14 对 gpt-5.5 的 `LOCAL_ADVERSE_EFFECT` 否决**继续有效,不因本批任何
结果而改变**:重放实证其三发修前修后激活数逐发相同(50/49/34),X5 抽样
逐条对上 —— 量具修复不改 gpt-5.5 轨迹上的折叠集,其批 14 数据本来就是
有效处理下测得。本批零 gpt-5.5 发次;将来要重测,另立预注册。

## §5 计划发次(6 发,照序连跑)

| 序 | 臂 | 模型 | | 序 | 臂 | 模型 |
|---|---|---|---|---|---|---|
| 1 | A(E0) | gpt-5.6 | | 2 | B(E1-S2′) | gpt-5.6 |
| 3 | A(E0) | gpt-5.6 | | 4 | B(E1-S2′) | gpt-5.6 |
| 5 | A(E0) | gpt-5.6 | | 6 | B(E1-S2′) | gpt-5.6 |

A/B 交替摊薄时间漂移;每格 n=3。通道:openai-compatible,env 只读宿主
显式变量(Gate 4A);`REPOPROOF_MODEL=gpt-5.6` 显式覆盖;A 臂显式
`unset REPOPROOF_CONTEXT_PROJECTION`,B 臂 `=window`;两臂均
`unset REPOPROOF_PROVIDER`(防 deepseek 残留路由)。

## §6 判据(冻结;A1–A7 沿批 14,A8 新增)

- **A1 效率(主指标)**:B 臂累计输入(`input_tokens`)中位数低于 A 臂。
  方向性判据,不预设百分比;数字只出 `scripts/exec_metrics.py`。
- **A2 不劣化(否决项)**:B 臂 verdict 分布不劣于 A 臂,公开测试最终
  通过数不低于 A 臂;**B 臂出现 A 臂没有的失败型 → S2′ 判为有害,默认
  保持关闭**,不论 token 降多少。首轮公开分照批 14 口径并排报。
- **A3 回读代价必须量出来**:B 臂命令数若高于 A 臂,必须进批报(判据
  不是"不许涨",是"涨了必须报")。
- **A4 撞墙缓解**:A 臂触发 `budget.exhausted` 的轮次占比,B 臂应下降
  —— 这是 S2′ 的真实价值主张(不被预算切断工作,非省钱)。
- **A5 停批线**:任一发暴露 harness 缺陷 → 本批作废,修完重预注册。
- **A6 预算不得动**:T2v5 预算逐字不动(36 调用 / 120 命令 / 20 文件 /
  1800 行 / 45 分钟 / 600k in / 60k out,每轮重置)。
- **A7 不混池**:两臂 `exec_generation` 与 `context_profile_hash` 台账
  可区分;本批数据不与批 1–14 任何发次合并统计。
- **A8 送达确认(新;批 14 缺陷 2 的处方)**:B 臂**逐发**核
  `projection.applied` 事件数 ≥1;零生效发判 `DELIVERY_FAILED`,不进
  对照统计。**B 臂首发零生效 → 立即停批查线**(停批线,不许静默跑完);
  整格零生效 → 本批复判 `TREATMENT_NOT_DELIVERED`,不出效应结论。

**判读决策树(先冻结)**:A8 送达 且 A1 达成 且 A2 未否决 → S2′ 获
"gpt-5.6 profile 选择性启用候选"资格(**默认仍关**;真启用归启用批的
预注册裁定)。A2 否决 → S2′ 对 GPT 代际归档关闭(与批 14 同处置)。
送达失败 → 修量具重来,不出效应结论。**n=3 小样本:批报给 Wilson 区间,
不下强结论;首轮公开分等机制性信号按批 14 口径判读。**

## §7 台账与分类

runs.jsonl 只追加;`run_classifications.jsonl` 逐发旁挂,镜像批 14 landed
schema:`test_mode=E1 / run_purpose=MECHANISM_ABLATION /
counts_toward_model_capability=false / counts_toward_heldout_benchmark=false /
treatment_assigned + treatment_activated 如实`(B 臂 activated 以
`projection.applied` 实测为准)。跑后 `gate_report.py --write` 再生。

## §8 供方失败与重试(先冻结)

供方终态失败(`PROVIDER_FAILURE`)不计入 n,可同臂补发一次,全批补发
上限 2,逐发留痕;连续 2 发 PROVIDER_FAILURE 暂停请示。除此以外**无
补发**(与批 14 同:12/12 全入账)。

## §9 成本封套

按批 14 gpt-5.6 实测(单发输入 0.53M–1.12M):6 发合计 **读入 ≤8M /
产出 ≤400K / 墙钟 ≤3h / 计分运行数 ≤8**(6 + §8 补发上限 2)。F0 冒烟
为 fake-scripted,不走 API,不计封套。

## §10 开跑前置(冻结时逐项核)

- [x] W1–W6 钉 11/11 绿(`tests/test_window_projection.py`,HEAD 实跑)
- [x] `_cmd_of` 多命令按序对位修复在位(HEAD 源码核对,docstring 记批 14 实证)
- [x] 重放 X1–X5 五条全过(证据 `replay-E1-S2prime.json`)
- [x] 两臂 ctx hash HEAD 复算 = 批 14 逐字同;exec_fingerprint 现值已录 §3
- [x] 宿主树 = 契约提交 `85278e6`,working tree 干净(仅生成物 manifest);
      H9-a 旧残留目录(`_scratch_t2_DELETE_ME_20260813`)已清,共享
      `_scratch_odr_compat/venv` 在位未动
- [x] 任务包自 `62d93f0` 零改动(git 核对)
- [x] 变异闸门 218/218(`docs/evidence/mutation_gate/17efb181f1c6.json`,
      src/ 自该提交后仅证据文件变动)
- [x] 冻结前全量绿:952 passed / 20 skipped / 0 failed,exit=0(350s 点计数)
- [ ] F0 冒烟:**冻结后、计分前**,fake-positive 两臂各一发在冻结 HEAD 上
      全绿,并核代际标签与开关同源切换(A 发 E0 / B 发 E1-S2)

## §11 跑法

用户 2026-08-17 指令(§0 引文)即起批授权,不再另行请示。顺序:冻结
提交 → F0 两臂冒烟(绿才继续)→ 计分 6 发照序连跑,逐发跑完立即核
A8(B 臂)与 A5;批期间 harness 零改动 → `exec_metrics.py` +
`batch_criteria.py` 判读 → 批报 → 台账/分类/gate 收口提交。
