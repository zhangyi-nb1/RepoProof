# RepoProof — Handoff State (authoritative snapshot)

> Purpose: the single in-repo status anchor for AI/human handoff.
> Update ONLY at gate boundaries; history below is append-only.

## Current status (2026-08-29, M6.1 Product Journey Reliability closed locally)

**主产品线仍是 GitHub 单能力 → 经独立验证的本地工具。M6.1 没有扩展
M7，也没有恢复旧宿主适配路线；本批只修复 Studio → Core 的产品旅程，
使受支持任务稳定到达 ACTIVE，或以唯一责任、原因码和下一步停止。**

| Anchor | Value |
|---|---|
| 本地分支 | `codex/product-journey-stabilization`，从 `29c3156` 开始；本节描述本地关闭状态，不代表已推送 GitHub |
| 状态事实源 | UI 不再从日志猜结论：`ProductJobStateV2` 只描述进程事实，`ProductActionResultV1` 描述动作结果，运营状态每次从 Core registry + append-only release ledger 重算 |
| Journey | `ProductJourneyRefV1` 原子保存导航关系；Studio 默认恢复未结束任务，普通用户不再手工复制草稿路径、task id 或结果 JSON |
| 预检 | 合同/版本/commit、锁文件、wheelhouse、离线安装、upstream import、公开 reference 样例和输出合同在 Agent 前执行；Harness/Upstream/Contract/User Input 故障零模型停止 |
| Repair | 首次实现 + 最多两轮 repair；仅 `AGENT_ADAPTER` 的公开失败可修复；无 diff、重复指纹无进展、范围漂移、环境故障和预算耗尽均有确定性 stop code |
| Product/Lab 隔离 | Product 完整性只覆盖任务拥有的合同、oracle、固定 upstream、adapter 和产物；实际越界写仍阻止；Lab/legacy 保留全局宿主完整性规则 |
| 原三仓资格 | `junitparser v1`、`markdown-it-py v4`、`python-docx v2` 均为历史 `VERIFIED_TOOL_READY`、clean replay PASS、当前 `ACTIVE`、package `OK` |
| 扩展三仓资格 | `jsonschema v8`、`feedparser v7`、`pypdf v2` 均从 Studio 完成合同确认、三样例、零模型演练、真实 Agent 构建、独立验证、clean replay 与 fresh audit；最终同样为 `ACTIVE` + package `OK` |
| Conformance 加固 | 上游 pytest 改为能力相关的模块级 node 选择，忽略 upstream pytest 插件配置；仅从上游自有 exact-pinned test/dev requirements 有界补依赖。pypdf 实录选 3 个节点，补 `pyyaml==6.0.2` 与 `pillow==12.2.0`，3/3 PASS 后才调用 Agent |
| 指标边界 | 本批所有 `PRODUCT` / `HARNESS_SELFCHECK` 与 `PRODUCT_ONBOARDING` 行的四个 `counts_toward_*` 字段均为 false；共享台账记录案例，但绝不计 Benchmark Lab 模型能力 |
| 资格事实源 | `docs/m6_1_qualification.yaml` 与 `docs/m6_1_extended_qualification.yaml`；每例钉住 task id、run id、历史结论、clean replay 和当前运营状态 |
| 本地质量线 | 1664 tests collected；全量 pytest 退出 0（1604 passed + 60 skipped），显式 Product journey/Streamlit smoke 17/17；Ruff 全仓 0 错；mypy 170 个源码文件 0 错；`git diff --check` 通过 |
| 对外 claim | 仅可说“六个记录过的、受支持范围内的 UI Product Journey 达到 ACTIVE”；不得外推为任意仓库成功率，也不得把 Product 发次写成模型能力成绩 |

不变铁律：Agent 自述不算成功；冻结合同、历史 run、旧 ledger 与旧指标不
改写；held-out 不向 Agent 泄漏；fresh audit 决定当前运营状态；本地提交与
远端 GitHub 状态严格区分。

## Previous status (2026-08-25, M0–M6 closed; Verified Tool Onboarding harness Gate 0–4 closed)

**RepoProof 的主产品线已从任意 Repository Adaptation 收敛为
GitHub Capability → Verified Local Tool。RFC-010 的章程、首个工具闭环、
半自动 intake、单命令旅程、两批真实仓指标均已落地；RFC-011 又补齐
输出合同一致性与 append-only 运营发布状态。M6(Studio 接同一 Core
事实源 + 人工 Preview Validated)已于 2026-08-25 关门。当前主链 =
`docs/VERIFIED_TOOL_ONBOARDING_NEXT_STAGE_GUIDE.md` 的 Verified Tool
Onboarding Harness:analyzer → CapabilityPlanV1(RFC-013,确定性路由
+用户确认)→ DIRECT_WRAP / AGENT_ADAPT 双路线同一验证链 →
FailureAssessmentV1 九码;REPAIR-VALIDATION-1(terra/luna)已按预注册
收官。**

| Anchor | Value |
|---|---|
| 产品方向 | `docs/PRODUCT_REDIRECTION.md` + `docs/rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md` |
| M0–M3 | 全部关闭；CLI 主旅程=`tool add/build/list/audit/withdraw/mcp` |
| M4 批次一 | 12 个真实仓均通过流水线、重放与运营审计；见 `docs/EXPLORATION_LOG.md` |
| M4 批次二 | 12 submitted / 11 accepted / 10 历史流水线 READY / 9 运营可用 / 1 false-success。**引用这行数字必须同时带完整性限定句**(下一行) |
| **完整性限定(2026-08-26)** | 主仓完整性对账曾排在 completion gate 之后、不参与判定(P0-2)。清点存量:**19 发 PRODUCT 记 PASS 而 `main_dir_integrity=MISMATCH`**,10 发绑定已导出工具、8 个当时 ACTIVE —— 即这 8 个工具的**交付发次在现行完整性闸下应判 BLOCKED**。裁决:记事实 + 强制限定句,不撤回运营资格;历史 verdict 一字不改,19 发逐发有 append-only 勘误行,`check_public_claims.py` 机器钉死该限定句。工具功能证据不受影响(clean replay + fresh-input 抽查是独立证据线,均已通过) |
| **干净复样已取得(2026-08-26)** | 预注册 `INTEGRITY-RESAMPLE-1-20260826`:8 道冻结题原样重跑于确认静默窗,**8/8 `PASS_ADAPTED` + `main_dir_integrity=ok`**,472,949 in / 30,737 out(批帽 1.2M,估算 724K,实际省 35%);P3 彩排 8/8 也全 `integrity=ok`(零模型成本)。复样**不追改原发 verdict、不替换工具包/registry/release ledger**。19 发中 15 发所属任务已覆盖;剩 4 发属 `jsonschema-report`(REVIEW_REQUIRED)与 `pyspellchecker`(REVOKED),均非 ACTIVE。映射见 `product_summary.json.ledger.clean_resample_by_task`。**换模型(gpt-5.5→terra)属非受控变量,本批不产出模型对比结论** |
| 批次二锚点 | `c5c958d` (`M4 批次二收官:9 个运营可用+1 false-success 撤回`) |
| 对外事实源 | **两个,永不合并**:`docs/product_summary.json`(Product,`scripts/build_product_summary.py`)+ `docs/benchmark_summary.json`(Lab)。一致性由 `scripts/check_public_claims.py` 在 CI 强制;产品发次 `task_seen=true`,不进模型能力/held-out 分母 |
| 批次二原始指标 | `docs/m4_metrics.json` + append-only audit/classification ledgers |
| 发次编号 | `run_classifications.jsonl` 的 product-* 现为 **1..84 连续无缺号、撞号 0**(2026-08-26 勘误:08-25 批误从 51 起编,与 08-23 批九连撞,改编为 product-76..84;主键始终是 run_id) |
| False success | `tool-pyspellchecker-tool-v1`:冻结声明 JSON、reference/example/oracle 却验纯文本；运营 READY 已撤回，冻结史和真跑均未改写/重跑 |
| M5 输出合同 | 新 draft=ToolSpec v2；T6–T9 + actual stdout runtime parsing；37 份旧冻结合同原样加载 |
| M5 发布状态 | 本机 release ledger 22 条迁移决定：21 ACTIVE / 1 REVOKED；另 2 个早期 dogfood 无 fresh audit，保持 REVIEW_REQUIRED |
| M5 本地提交锚点 | `034bdf1`；M5 关闭,后续随 M6/新阶段一并推送 origin |
| MCP 执法 | 仅历史 READY + 当前 ACTIVE 可生成；M5 adapter 每次 list/call 复核 ledger；pre-M5 非 ACTIVE adapter 明示 `LEGACY_SERVER_MUST_BE_DETACHED` |
| M6 整合锚点 | 工程实现 `d7c1278`；`3818ccb` no-ff 保留 UI 历史；2026-08-24 项目方三固定案例预览通过(P0=0,P1=5 全修复)并合回 `main`；**2026-08-25 两名目标用户三案例理解测试完成(P0=0,P1+2 条已修复并经复验)——M6 关门**。目标用户测试为项目方自报,原始记录表归档位 `docs/evidence/m6_user_tests/` 尚待投入(见该目录 README);在归档落位前,只可声明「项目方报告测试完成」,不可声明「仓库内证据可独立审计」 |
| M6 可信整合 | Core-only registry 投影；historical/operational/package health 三栏；ProductJobStateV2；Studio/Lab 共享 Core 写锁；Product/Lab 原生分账 |
| 当前质量基线 | 本机全量 `1493 passed + 60 skipped + 0 failed`(2026-08-28,docker 停时形态;共收集 1553 项);**CI 三 job 全绿**(.github/workflows/ci.yml:ruff 全仓 0 错 + mypy 0 错 + pytest 全量);**mypy 覆盖除 Lab 冻结区外的全部源码**(2026-08-26 摘在役 runner 七件 19 错;2026-08-27 摘 ui/agents/cli 63 错 —— 其中两枚真崩溃:`tool plan --repo` 漏传必填 cache_root、运行活动页 `st.progress(None)` 抛 StreamlitAPIException,均已补回归钉);渐进队列清空,豁免只剩冻结区逐文件列名(棘轮只减不增) |
| 代码分区 | `docs/PROJECT_MAP.md`(单页地图):产品可信链 vs **Lab 冻结区(FROZEN 2026-08-25)**;host_guided 功能面冻结但仍是产品彩排/真发执行引擎,判定/安全缺陷照修 |
| 后端资格 | Product Mode 缺省 mini-swe + LiteLLM/API 网关；Codex CLI/ChatGPT 订阅路径完整保留为显式回退（仅产品不计分）；DSH 仅冻结 Lab |
| M7 分支现状 | `codex/m7-managed-sidecar-tools @ 7ac1a09` 已推送；强 U1–U4 回执已落地(取证会话+攻击矩阵自证);仍缺 v3 全链 E2E、OS 级隔离、导出包 replay、授权真仓 —— EXPERIMENTAL,功能面冻结 |
| 下一阶段基准 | `docs/VERIFIED_TOOL_ONBOARDING_NEXT_STAGE_GUIDE.md`(2026-08-25):Verified Tool Onboarding Harness;Gate 0 事实收口 → Gate 1 CapabilityPlanV1+确定性路由 → Gate 2 有界修复控制器产品化 → Gate 3 DIRECT_WRAP → Gate 4 Studio 收口 |
| 当前阶段门 | **M6 Preview Validated 已关闭(2026-08-25:项目方预览+2 名目标用户三案例测试完成,P0=0;P1 计 7 条全部修复并经用户复验)。M7 强 receipt 已落地/OS 隔离未关闭**;发布、第三批真仓或任何新真实模型发次仍需授权 |
| 面试材料 | **2026-08-26 重写完毕**(此前停在 2026-08-07 Gate 8 口径):`CLAIMS_MATRIX`(两事实源 + C1–C21 + F1–F17)、`RESUME_CLAIMS`(三版本)、`INTERVIEW_GUIDE`;DEMO 两份不重写,加定位头指向 `scripts/demo_direct_wrap.py` |
| 保护目录 | **结构性发现**(2026-08-26):本仓自身 + 兄弟 git 仓,不再硬编码个人路径;退化可观测 + 单测钉死"本仓自身必须在保护列表里"。追加仍走 `REPOPROOF_PROTECTED_DIRS` |
| 发次编号(更新) | product-* 现为 **1..100 连续无缺号、撞号 0**(INTEGRITY-RESAMPLE-1 占 85..100,彩排/真发成对) |
| 挂账未做 | ~~① 8 个工具干净环境复样重跑~~ **已于 2026-08-26 完成(8/8 干净)**;② M6 两份用户测试原始记录表归档;③ 真实模型演示与第三批真仓授权;④ M7 OS 级隔离;⑤(新)`jsonschema-report` 交付发次仍无干净复样(该工具 REVIEW_REQUIRED,未 ACTIVE) |

不变铁律：验证面无 LLM；held-out 对 agent 零泄漏；冻结合同与历史台账
不可改写；FAIL 也留完整证据；没量到即判死；Product Mode 与 Benchmark
Lab 分账，不用产品发次充模型能力成绩。

## Previous status (2026-08-08, after RFC-008 Gate A–E)

**Guided Adoption Delivery(RFC-008)A–E 全部落地:普通用户可在中文
UI 内走完 分析(空目录模式/八策略)→ 计划确认(Human Gate 扩展)→
装配冻结 → 单次或 ≤3 轮有界修复(公开反馈)→ 独立验证 → Bundle
导出(EXPORT_ONLY)→ 三级安全写回(fixture 已验证)。**

| Anchor | Value |
|---|---|
| Gate A(审计+RFC-008) | `d08e1a2` |
| Gate B(分析/Plan 接线) | `4452e7e` + 独立验证三反例修复 `113d287` |
| Gate C(期望草稿/Staging/Bundle) | `91a8858` |
| Gate D(GUIDED_ADOPTION 多轮) | `edb2504`(真实模型运行:见 PREREG-gateD,首跑留用户) |
| Gate E(Apply/Rollback) | `bcc8f32`(仅 fixture 验证;真实项目写入 = UI 三步确认停点) |
| 独立验证 | 每个 Gate 由与实现者不同的 agent 对抗复核(Gate B:12/12 通过) |
| 铁律不变 | 单自主循环;held-out 零泄漏(测试钉死);循环永不宣布成功;FAIL 也交付 Bundle;UI 结论=Core 结论 |

## Previous status (2026-08-07, after Gate 8 — USER-ACCEPTED)

**v0.1.0 released and user-accepted. MVP frozen; UI phase (Gate 9)
begins on top, read-only over all frozen history.**

| Anchor | Value |
|---|---|
| Gate 8 close (MVP freeze) | `97d2810` |
| Release | tag `v0.1.0` + https://github.com/zhangyi-nb1/RepoProof/releases/tag/v0.1.0 |
| Fact source | `docs/benchmark_summary.json` (12 runs, extraction-only) + `scripts/check_public_claims.py` |
| Claim rules | `docs/CLAIMS_MATRIX.md` (9 allowed / 12 forbidden) |
| No-model demos | `repoproof demo list/verify/replay` (verify recomputes gate decisions; replay re-earns 18/18 in a fresh container) |
| Scaffolding | `repoproof task init/check` (DRAFT → READY_TO_FREEZE) |
| Job materials | `docs/RESUME_CLAIMS.md` (3 versions) + `docs/INTERVIEW_GUIDE.md` |

Gate 8 verdict (user acceptance 2026-08-07): benchmark totals — 3
capability domains, 12 recorded runs (7 real-agent), **1
PASS_ADAPTED**, 11 honest FAILs; 183 tests green; zero LLM calls in
Gate 8; history and evidence untouched; LocalFlow untouched.

**Standing hard rules for the UI phase (from the Gate 9 order):**
UI reads Core results only (never re-implements the completion gate);
facts come only from RunManifest / Trace / VerificationResult /
benchmark_summary / Evidence bundles; no history modification; no
LocalFlow access; API keys never persisted or logged; localhost only.

## Previous status (Gate 7.2)

**Core MVP complete. First real PASS_ADAPTED achieved and pushed.**

| Anchor | Value |
|---|---|
| Gate 7 close (v1 fm task, FAIL 8/11) | `b5430bb` |
| Gate 7.1 (contract adequacy, zero LLM) | `02e50a7` |
| Gate 7.2 preregistration | `38314d1` |
| Gate 7.2 close (**PASS_ADAPTED**) | `f428c30` |
| PASS_ADAPTED run | `adopt-frontmatter-local-ingest-v1-v2-20260807-201155` |
| Evidence | `docs/evidence/gate72-corrected-spec-run/` (scanner CLEAN) |

### Gate 7.1 — what was fixed (deterministic, zero model calls)

1. **v2 task** `adopt-frontmatter-local-ingest-v1-v2` (v1 frozen as
   history): ambiguous `has_frontmatter` split into
   `frontmatter_present` + `metadata_nonempty` with a
   container-calibrated public truth table (JSON fences supported,
   TOML absent, unclosed fence unrecognised, trailing-newline strip
   encoded in the operational criterion).
2. **RequirementSpec** — 12 typed requirements (owner / severity /
   public_text / examples / oracle_nodes) + controls battery spec.
3. **ContractAdequacyGate** — 13 deterministic checks; inadequate
   spec ⇒ `INVALID_TASK_SPEC`, agent never starts (zero model calls).
   Caught a real node-id format mismatch during its first freeze.
4. **PromptManifest** — ONE shared Contract→Prompt renderer for
   freeze / gate / run; HARD requirement ids + prompt sha frozen.
5. **Host InputContractGuard** — deterministic input validation
   (text/doc_id types, presence) owned by the CONSUMER, raising
   `IngestError(code=INVALID_DOCUMENT_INPUT)` before any adapter runs.
6. Controls frozen into the TaskPackage: positive 18/18 PASS; 4
   negative controls (flag-conflation / regex / bad-conversions /
   raw-exception) all FAILED_AS_EXPECTED.

### Gate 7.2 — the corrected-spec run (ONE preregistered run)

deepseek-v4-pro, native tool-calls, temp 0, budgets unchanged from
Gate 7, Coverage Ledger OFF, budget observation text OFF.
Result: capability **18/18** (incl. held-out), regression 3/3, policy
clean, replay **clean_adoption PASS**, agent **submitted voluntarily
at 16/20 calls** (241,258 in / 7,301 out tokens; 1 file / 67 lines).
Prompt sha `83931a19…` and provider hash `21f53738…` matched the
preregistration exactly. Verdict: **PASS_ADAPTED**.

### Claim discipline (binding for all downstream material)

- Gate 7.2 is a **corrected-spec positive case**, NOT a
  single-variable experiment vs Gate 7 (task version, schema, prompt
  surface and guard changed together).
- Input-boundary handling (text=None etc.) is **Host Guard work, not
  agent capability**.
- Chonkie 31/33 and rank_bm25 9/12 remain honest FAILs; history and
  benchmark rows are immutable.
- Budget-awareness ablation: null result. Coverage Ledger:
  experimental, default off, cross-task effect not supported.

## Gate history (append-only)

- Gate 0–2.5: repo bootstrap, evidence chain, chonkie v1/v2 baselines.
- Gate 3A/3B/3C: no-model admission hardening; mini-swe-agent 2.4.6
  integration; first real run 31/33 honest FAIL (`gate3-real-agent-baseline` tag).
- Gate 4A: budget-state observations — null result, preserved.
- Gate 4B: Coverage Ledger — first voluntary Submit, outcome unchanged.
- Gate 5/5.1: rank_bm25 portability (9/12 FAIL, SEMANTIC_SUBSTITUTION);
  token budgets made real; RepoAdoptBench-mini consolidated.
- Gate 6: preregistered solvable fm task — FAIL by
  HARNESS_PROMPT_CONTAMINATION (harness's own bug, found and fixed).
- Gate 7: clean-prompt re-run — FAIL 8/11; decomposed into
  CONTRACT_UNDERSPECIFICATION (task-author) + text=None omission
  (agent, cross-domain n=2).
- Gate 7.1/7.2: spec-side fixes → **first PASS_ADAPTED** (above).
- Gate 8 (current): MVP freeze, reproducible no-model demo, v0.1.0.
