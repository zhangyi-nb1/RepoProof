# RepoProof 单页地图(10 分钟版)

> 本页是全项目唯一的"防迷路"入口:名词、编号、代码分区、判定词汇的
> 对照表。细节以链接目标为准;本页只负责让你知道**该读哪里、词是什么意思**。

## 30 秒版本

**RepoProof 把公开 GitHub 仓库里的一个明确能力,包装成经独立验证、可
干净重放、带运营状态的本地 CLI 工具。** 核心立场:coding agent 的
"我做完了"永远不算数——判定只出自 agent 摸不到的验证链(隐藏验收、
回归基线、策略执法、干净重放、主仓完整性对账)。

当前主链(2026-08-25,Verified Tool Onboarding Harness):

```text
URL+一句话 → 静态分析 → CapabilityPlanV1(证据+确定性路由,用户确认)
  → DIRECT_WRAP(受信模板,零 agent) 或 AGENT_ADAPT(有界修复循环)
  → 同一条独立验证链 → 判定 → 导出/注册表/MCP + append-only 运营账本
```

## 10 分钟阅读路径

1. [README.md](../README.md) —— 产品是什么、工作流图(2 分钟)
2. 本页的编号对照与词汇表(3 分钟)
3. [docs/VERIFIED_TOOL_ONBOARDING_NEXT_STAGE_GUIDE.md](VERIFIED_TOOL_ONBOARDING_NEXT_STAGE_GUIDE.md) —— 现行架构基准(5 分钟)

想看演进故事:[docs/PROJECT_EVOLUTION.md](PROJECT_EVOLUTION.md);
想看面试口径:[docs/INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md)。

## 代码地图:产品可信链 vs Lab 冻结区

一句话:**除 Lab 冻结区外全部源码都有类型兜底和 CI;历史研究资产显式冻结。**
(mypy 的豁免边界与这张表逐行一致 —— 见 `pyproject.toml [tool.mypy]`。)

| 分区 | 包/文件 | 状态 |
|---|---|---|
| 产品主编排 | `runner/tool_pipeline.py`(384 行) | 在役,新逻辑落这里 |
| 产品可信链 | `adoption/`(analyzer/plan/intake/assembly/repair)、`verification/`、`harness/`、`domain/`、`persistence/`、`execution/`、`receipts/`、`probes/` | 在役,mypy 0 错 |
| 产品运营 | `runner/tool_export|registry|release|mcp|paths|host_bridge` | 在役,mypy 0 错(2026-08-26 摘出豁免) |
| 展示面 | `ui/`(Streamlit Studio,不参与判定)、`cli.py` | 在役,mypy 0 错(2026-08-27 摘出豁免) |
| 产品 Agent 连接器 | `agents/codex_cli_backend.py`、`codex_hook_guard.py` | 在役,mypy 0 错;仅 Product Mode,不计 Lab 成绩 |
| mini-swe / DSH 历史后端线 | `agents/` 其余执行件(E 轨已关闭,DSH 功能面随 Lab 冻结) | mini-swe 保留 API 兼容;DSH 仅 Lab;mypy 0 错 |
| **Lab 冻结区** | `runner/host_guided.py`、`baseline.py`、`guided_repair.py`、`agent_run.py`、`sidecar_session.py`、`calibration.py`、`demo.py`、`scaffold.py` | **FROZEN 2026-08-25**;mypy 唯一豁免,逐文件列名(整包通配会给新增模块开暗门) |

渐进队列已清空:类型覆盖是**棘轮**,名单只许减。新增模块默认受检,
不得靠加 override 绕过。

冻结区的特殊件:`host_guided.py`(3900+ 行)**功能面冻结但没有退役**——
产品的彩排与真发仍由 `tool_pipeline` 调用它执行,其验证链就是判定来源。
冻结 = 不再新增研究面功能;判定/安全缺陷照修。不拆分重构:单人项目里
宣布冻结比拆 4000 行便宜一百倍,且不引入回归风险。

## 编号系统对照(四套,只有两套现行)

| 编号系 | 什么 | 状态 |
|---|---|---|
| **M0–M7** | RFC-010 产品里程碑:M0 章程 → M1 首工具闭环 → M2 半自动 intake → M3 单命令+注册表+MCP → M4 两批 24 真实仓 → M5 输出合同+运营账本 → M6 Studio+用户测试 → M7 强回执 sidecar(EXPERIMENTAL) | **现行**;M0–M6 已关,M7 部分 |
| **新阶段 Gate 0–4** | 2026-08-25 指导文档的关门序:0 事实收口 → 1 CapabilityPlanV1 → 2 修复控制器产品化 → 3 DIRECT_WRAP → 4 Studio 收口 | **现行**;全部已关 |
| MVP Gate 0–7.x(数字) | 2026 早期 Benchmark MVP 的证据链关卡(Gate 5 SEMANTIC_SUBSTITUTION、Gate 6/7 量具修正等),见 PROJECT_EVOLUTION | 历史,已完成 |
| RFC-008 Gate A–F(字母) | Guided Adoption UI 线的实施序 | 历史,已完成 |

读旧文档遇到 "Gate 3C" "Gate D" 之类:先看它属于哪一代,别跨代对号。

## 判定词汇:三层,不可混用

**第 1 层 · 单次构建的 verdict(一发一个,永不改写)**
`PASS_ADAPTED`(agent 有界修复后过全门)/ `PASS_DIRECT`(受信模板零
agent 过全门)/ `FAIL` / `BLOCKED`(前置闸拒发或完整性覆盖)。

**第 2 层 · 历史验收(historical,不可改写)**
`VERIFIED_TOOL_READY` = 当时通过独立验收的冻结结论。它**永远保留**,
但**不代表今天可用**。

**第 3 层 · 运营现状(operational,append-only 账本)**
`ACTIVE`(fresh-input 抽查通过,可生成 MCP)/ `REVIEW_REQUIRED`(差一次
新输入抽查)/ `REVOKED`(停用;历史成绩不抹)。

historical 与 operational 是**双口径并列**,不是新旧替代:一个工具可以
"历史 VERIFIED_TOOL_READY + 运营 REVOKED" —— 这正是 false-success 被
新输入审计抓出后的诚实形态(实例:pyspellchecker,M4 批次二)。

## RFC 索引(12 个)

现行:**RFC-010**(产品章程)、**RFC-011**(输出合同+运营发布状态)、
**RFC-013**(CapabilityPlanV1:证据化计划+确定性路由+用户确认)。
历史(演进记录,读旧文档时查):001 host-analyzer、002 repository-
analyzer、003 admission、004 plan-only、005 human-gate、006 repair-loop、
007 example-assembly、008 guided-adoption UI(Gate A–F)、009
host-integrated tasks。没有 RFC-012。

## 对外数字只出自两个事实源

| 事实源 | 覆盖 | 重建 |
|---|---|---|
| `docs/product_summary.json` | **Product Mode**:84 发产品运行、两批真实仓、运营状态、完整性存量 | `scripts/build_product_summary.py` |
| `docs/benchmark_summary.json` | **Benchmark Lab**:MVP 时代冻结的 12 发快照 | `scripts/build_benchmark_summary.py` |

**两者永不合并**;一致性由 `scripts/check_public_claims.py` 在 CI 里强制。
产品发次 `task_seen=true`,一律不进模型能力/held-out 分母。

一条必须跟着数字走的限定句(2026-08-26 外部审查):主仓完整性对账曾排在
completion gate 之后、不参与判定,清点存量发现 19 发 PRODUCT 记 PASS 而
`main_dir_integrity=MISMATCH`,10 发绑定已导出工具、8 个当时 ACTIVE ——
即这 8 个工具的**交付发次在现行完整性闸下应判 BLOCKED**。历史 verdict
一字不改,逐发有 append-only 勘误行;checker 把这句限定机器钉死。
工具功能证据不受影响:干净重放与 fresh-input 抽查是独立证据线,均已通过。

**已复样(2026-08-26,INTEGRITY-RESAMPLE-1)**:8 道冻结题在静默窗内按现行闸
重跑,**8/8 PASS_ADAPTED + `integrity=ok`**(472,949 in)。复样证明的是
"这道冻结题 + 钉版上游今天确实能干净通过";它**不**追改原发 verdict,也
**不**替换任何工具包 / registry / 发布决定。19 发中 15 发所属任务已有干净
复样,剩 4 发属 `jsonschema-report`(REVIEW_REQUIRED)与 `pyspellchecker`
(REVOKED)—— 均非 ACTIVE。映射见 `product_summary.json`
的 `ledger.clean_resample_by_task`。

## 证据在哪(全部 append-only)

- `benchmarks/v2/runs.jsonl` —— 每一发真跑一行(FAIL/BLOCKED 也记)
- `benchmarks/v2/run_classifications.jsonl` —— 发次口径分账(产品发次
  不充模型能力成绩);勘误 = 追加覆盖行,不改旧行
- `runs/<run_id>/` —— 单发全证据包(trace 哈希链、report.json、快照)
- `docs/EXPLORATION_LOG.md` —— 状态条目流水;`docs/LESSONS_LOG.md` —— 教训
- `docs/evidence/` —— 结构化证据归档(含 M6 用户测试占位,见其 README)
