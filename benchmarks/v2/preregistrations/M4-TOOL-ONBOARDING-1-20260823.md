# 预注册 · M4-TOOL-ONBOARDING-1(产品指标批次一)

- 状态:**冻结待用户批准**(2026-08-23;批准前本文与任务清单 json 一并
  commit,结果未见;开跑后本文不改,勘误按 §3.3/§8 走旁注)
- 依据:RFC-010 §六 M4 · [G4] 指标口径 · TOOL_READY_GATE §六
- 任务清单(机器可读,与本文同批冻结):`M4-batch-1-tasks.json`(12 仓)

## 1. 目的与非目的

**目的**:量产品四指标 —— 系统把"用户看中的 GitHub 能力"变成
"已验证本地工具"这条流水线,在真实多样任务上的接受率、成功率、
可重装率与假成功率。

**非目的**(措辞铁律):
- 不测模型能力(单模型 gpt-5.5,无对照臂;全部发次 test_mode=PRODUCT,
  `PRODUCT_PURPOSES` 不充闸不计能力,与 Lab 成绩永不互比);
- 不做 held-out 声明(任务是操作员现场构造的开发性任务;
  oracle_authorship=TASK_AUTHOR_COMPILED);
- 数字不出本预注册定义之外的口径;散文只解释不下判断
  (唯一出口 `scripts/tool_metrics.py`,已喂合成台账自证)。

## 2. 流程(逐任务,与 M2 验收流同构)

`tool add`(intake+gpt-5.5 起草)→ **操作员人闸**(AI 操作员执行、用户
抽验):审阅 statement/reference、放样例真值(输入取自上游测试材料或
合成;期望由 reference 直连生成并过目;≥3 组、含文件样例、尾部
held-out)→ `tool build`(confirm→conformance 预检→备轮→**fake 彩排
门**→真模型 **1 发**→export+注册)。

- **真发一发制,不重试**。FAIL 如实入账;若归因为任务侧缺陷
  (题面欠定/样例错),修复后重发 = **新版本任务号**,原发照留,
  per_task 记两行,指标按原任务清单项的**末次真发**计(口径冻结);
- admission UNSUPPORTED / NEED_INFORMATION 无法由盘上事实作答 →
  该任务停在 intake,计入 submitted 分母、不计 accepted(这正是
  接受率要量的东西,不是失败要藏的东西);
- 彩排 BLOCKED/FAIL → 不烧真预算;归因 harness 侧则修 harness(全部
  任务受益,如实记于日志);归因任务侧同上重发条款。

## 3. 任务池(冻结)

**3.1 选取口径**(在看任何 intake 结果之前定):PyPI 常用纯 Python 库、
CPU、能力可一句话描述、输入输出为文件/文本型、宽松许可、跨 ≥8 个能力
域(slug/乱码修复/转写/YAML/JSON5/Markdown/高亮/表格/日期/编码检测/
人读格式/feed 解析)。**清单 12 项一次冻结,不换任务、不加任务。**

**3.2 已知风险预写**:个别仓可能老式打包(intake 转人答)、上游测试
子集在本机预检死(物化拒绝 → 该任务如实停在 accepted 后、ready 前)、
C 扩展可选件(pyyaml)按纯 Python 轮回落。这些都是产品要面对的真实
分布,不做任务替换。

**3.3 勘误条款**:清单 URL 为凭记忆写就;开跑时若某 URL 404/非官方仓,
更正为同名官方仓属**勘误**(旁注记录),换成别的库属**换任务(禁止)**。

## 4. 预算(冻结)

- 每任务契约默认预算盒:400K in / 40K out / 30 min / ≤3 轮 / 单发;
- **批总名义 in 帽 = 6.0M**(含重发);触帽立即停批,已跑的如实结算;
- 起草层(gpt-5.5)每任务一次,名义 ≤10K in/任务,计入批帽。

## 5. 指标定义(冻结;唯一出口 scripts/tool_metrics.py)

| 指标 | 定义 |
|---|---|
| submitted | 清单任务数(=12) |
| accepted | 存在 url 匹配的**冻结**契约(confirm 过;sidecar 在) |
| acceptance_rate | accepted / submitted |
| tool_ready | 末次真发 verdict ∈ PASS_* 且注册表有导出项 |
| tool_ready_rate | tool_ready / accepted —— **必须与 acceptance_rate 成对引用**([G4]:单引后者=准入闸可刷指标) |
| replay_success | 自动重装口径:临时拷贝→删 .venv→./build.sh→--help exit 0(`scripts/m4_replay_check.py`,append-only 记账)。**如实弱于**每发已跑过的 clean replay(后者含全量验收);能力级真实输入抽验并入 false_success |
| false_success | 人工审计单 `m4_audits.jsonl`:对每个 tool_ready 工具,操作员+用户用**非样例真实输入**各至少一次,输出不满足 statement 语义即 flagged;audited/flagged 双数报 |

## 6. 台账与留痕

每发(fake 彩排+真发)照记 runs.jsonl + PRODUCT 旁挂(HARNESS_SELFCHECK
/ PRODUCT_ONBOARDING 口径同 M1/M2);draft_meta(起草用量)随 draft 束
归档;m4_replay.jsonl / m4_audits.jsonl append-only;批结束
`tool_metrics.py --write` 出 docs/m4_metrics.json 并入库。

## 7. 终止条件

清单跑完,或批帽触顶,或用户叫停。中途 harness 侧缺陷修复照常提交
(全批受益,不算换任务);修复导致的已跑任务复测 = 重发条款。

## 8. 修订纪律

本文冻结后只许追加「勘误/旁注」小节,不许改动 §1–§7 正文;任何口径
变化 = 新批次新预注册。
