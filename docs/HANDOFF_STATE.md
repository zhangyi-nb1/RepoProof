# RepoProof — Handoff State (authoritative snapshot)

> Purpose: the single in-repo status anchor for AI/human handoff.
> Update ONLY at gate boundaries; history below is append-only.
>
> **2026-09-01 continuation checkpoint:** C3–C5 的后续新 task version 与
> Textual v3 收口发生在下方 Current status 之后。继续 M6.2 前先完整阅读
> [`HANDOFF_CODEX_M6_2_CONTINUATION.md`](HANDOFF_CODEX_M6_2_CONTINUATION.md)；
> 它追加新事实，不改写本文件记录的正式首轮失败终态。

## Current status (2026-09-02, M6.2 closed locally: 9 first-pass terminal states kept, 8/8 follow-up ACTIVE, promotion gate met)

**主产品定位不变：GitHub 单能力 → 经独立验证的本地工具。M6.2 的
`workspace_bundle_v1` 已在受支持范围内完成资格批次：首轮九个正式终态一字未改，
八个真实案例各以新 task version 达到 `VERIFIED_TOOL_READY + ACTIVE + package OK`。**

| Anchor | Value |
|---|---|
| 本地状态 | `codex/m6-2-workspace-bundle-qualification`，HEAD `fd058584af1aa04f02801cbcde602cc9a27856e2`；本节所述 Core/测试/文档改动与新增证据均在**未提交工作树**，未推送、未发布 |
| 工程身份 | 收口时可执行 `src/repoproof` 树哈希 `bdf389f4cf4473543b56fc5e69a71a7df8b01a556e38a871c0163d68730e9341`；每个 run/incident/evidence 各自绑定产生它时的 framework 身份，不追改 |
| Profile 状态 | `workspace_bundle_v1 = SUPPORTED`（本节生效）。冻结晋级门 `profile_promotion_gate` 四项全部满足：B1、B2 ACTIVE；复杂 ACTIVE 六例（≥4）；SQLite/二进制工作区（Datasette v3、Trafilatura v1）；可运行应用工作区（Datasette v3、Textual v3、marimo v3、research-project-starter v3）。成熟度只在文档层落账，代码无 EXPERIMENTAL 开关；MCP 对目录工具仍固定拒绝 `WORKSPACE_BUNDLE_MCP_NOT_SUPPORTED` |
| 冻结协议 | 不变：`docs/m6_2_workspace_bundle_qualification_v2.yaml`，SHA-256 `57ef6d57919ac098584dd1513d1ed6019e5395907d3ab7f468d08438e5913ce6` |
| 首轮正式终态 | 不改写：N0 `EXPECTED_REJECTION`；B1 `UPSTREAM_CONFORMANCE_ENVIRONMENT`；B2 `DRAFTER_INVALID_MODEL_OUTPUT`；C1 `FIXTURE_INPUT_DUPLICATE`；C2 `FIXTURE_BUILDER_FAILED`；C3 `WORKSPACE_OUTPUT_SCHEMA_PROJECTION_MISMATCH`；C4 `DRAFT_CREATION_FAILED+LIFECYCLE_MISMATCH`；C5 `DRAFT_CREATION_FAILED+EXTERNAL_SIDE_EFFECT_MISMATCH`；C6 `EXTERNAL_GATEWAY_UNAVAILABLE+DRAFTER_TIMEOUT`。九份 `runs/m6-2-qualification-planning/<case>/case-result.json` 原样 |
| 修复后终态（新 task version） | B1 `tool-research-project-starter-v3` / run `…-20260902-005027`；B2 `tool-csvkit-tool-v1` / `…-20260902-014025`；C1 `tool-pdfplumber-tool-v1` / `…-20260902-020425`；C2 `tool-trafilatura-tool-v1` / `…-20260902-035547`；C3 `tool-networkx-tool-v4` / `…-20260901-013543`；C4 `tool-datasette-tool-v3` / `…-20260901-164106`；C5 `tool-textual-taskdesk-v3` / `…-20260901-180812`；C6 `tool-marimo-tool-v3` / `…-20260902-000237`。八例均：历史 `VERIFIED_TOOL_READY`、clean replay PASS、fresh audit `FRESH_INPUT_PASS`、registry+ledger 重算 `ACTIVE`、package `OK`、repair 0。中间版本（marimo v1/v2、starter v1/v2、textual v2 REVOKED、networkx v4 一次 REVOKED 后再审）全部保留 |
| 资格记录 | append-only `docs/qualification_runs/m6_2_workspace_bundle_v2/`：`m6-2-workspace-bundle-v2-first-pass-20260902.json`（九案首轮，逐字来自冻结 case-result，绑定 `38b1b10` / 树 `4ec8f553…`，文件 SHA `6674a8a6…`）与 `m6-2-workspace-bundle-v2-follow-up-20260902.json`（八案 PASSED，语义证据按 Core 自身路径 ledger `evidence_sha256` → `evidence/release-audits` 外层文档 → 嵌套 `SemanticVerifierEvidenceV2` 绑定，绑定当前 framework，文件 SHA `04ff2777…`）。两份 `counts_toward_*` 全 false |
| 零模型回归 | `scripts/workspace_case_replay.py`（冻结 `oracle_snapshot/test_capability.py` 原样执行 + task 密封 wheelhouse + Harness 测试工具链 + 导出包离线重建）；每次 Core 修改后重跑，收口时八工具 8/8 PASS，最新证据 `runs/evidence/workspace-replays/workspace-replay-20260902T080401Z.json`（M6.3 十一项 Harness 改动后重跑，8/8 PASS） |
| 本轮通用 Harness 修复 | 六项，各有 `ProductIncidentV1` + 匿名前/后控制 JUnit（`runs/harness-controls/`）+ `HarnessChangeEvidenceV1`（`runs/harness-changes/`）+ Core 特例扫描零新增：`admission-secret-executable-read-v1`（密钥必需=AST 可执行读取，全树确定性扫描）、`import-hook-transparent-args-digest-v1`（量具参数摘要不得向被测抛异常）、`conformance-execution-root-probe-v1`（cwd 探测不猜）、`oracle-collection-scope-v1`（隐藏验收只收集 oracle 顶层测试模块）、`fresh-audit-per-proposal-materialization-v1`（提案逐个物化+公开异常类+排除反馈，不连坐）、`conformance-admitted-test-surface-v1`（准入面=pytest 实际收集面）。另一单例非安全事故 `workspace-candidate-lock-canonicalization-v1` 只记录不改 Core |
| conformance 覆盖注记 | 三个冻结任务包（networkx v4、datasette v3、trafilatura v1）的 `conformance.json` 为 `SKIPPED/0 节点`，不改写；准入面修复对之后的物化生效（同树上现可选 3/3/3 节点）。datasette 的零选中含 `asyncio_mode=strict` 全异步这一诚实档位限制 |
| 台账与事实文件 | `benchmarks/v2/runs.jsonl` 440 行（append-only，本批 `counts_toward_*` 全 false）；`docs/v2_gate.json`、`docs/product_summary.json` 由官方脚本重建；`scripts/check_public_claims.py` 通过；`tests/test_run_classification.py` 宿主覆盖棘轮追加五个 Product 宿主 |
| 起草自检自修（09-02 晚追加） | 机器起草的 workspace 控制件在人审前由 Harness 自动物化、判定（候选生成尺子 + verifier 判别力探针）并按站位有界自修（builder/verifier×2/reference，上限 3，事务回滚）；报告 `draft_selfcheck.json` 绑定控制件指纹，readiness 以 `DRAFT_SELF_CHECK_*` 阻塞冻结。证据 `harness-change-draft-self-check-bounded-repair-v1/v2`（五事故同指纹 `3e0c167e3213252b`）；真实缺陷草稿端到端演示 v1–v3 FAILED（各修一处机制缺陷）→ **v4 PASSED 零人工**（`runs/evidence/draft-selfcheck-demo/`）。CLI `tool self-check`，`tool add` 自动执行 |
| M6.3 出题草案 | `docs/m6_3_complex_workspace_qualification_v1.yaml`（DRAFT_NOT_FROZEN，SHA `5dfb74eabc94908f…`）：N0 = 用户的实时余额监控想法作预期拒绝负控；c1–c8 复杂案例（xlsx/pptx/SVG 仪表盘+SQLite/PNG/静态站/ics/ipynb/mo），tag→commit 已解析，wheelhouse 与 7 个新 validation profile 未冻结 |
| M6.3 phase 1（09-02 下午） | 用 `tool autopilot`/批次驱动跑 N0+c1–c8 至彩排：首轮 N0 EXPECTED_REJECTION ✓，c1–c8 全败（c1/c3 `WORKSPACE_CONTRACT_INVALID`；c2/c4/c7 preflight `REFERENCE_GOLDEN_MISMATCH`；c5/c6/c8 自检未过）。每例追到 Harness 环节并按“两独立任务同指纹”授权改机制，本轮新增七份 `HarnessChangeEvidenceV1`：`drafter-projection-repair-diagnostics-v1`（合同拒绝的字段级公开诊断进修复上下文/`DraftError.diagnostics`）、`autopilot-failed-substage-projection-v1`（子站 code/detail/owner + 每站 payload 落盘）、`sealed-runtime-lock-canonical-v1`（密封锁=规范形；黄金树分歧逐路径给类型）、`reference-failure-public-location-v1`（reference 异常带 `Type: msg @ reference_impl.py:行 函数`）、`reference-reproducibility-probe-v1`（候选生成隔 ≥2 s 重跑 reference，漂移即 `WORKSPACE_REFERENCE_NOT_REPRODUCIBLE`）、`contract-structural-defects-v1`（Core 闭包重复规则编译期去重；结构码路由到第四修复位 `contract`，角色集/交付形态不变否则回滚）、`verifier-repair-observation-excerpts-v1`（裁决者修复观察含有界文本摘录/zip 成员/魔数）。单例待第二起：`golden-identity-zip-metadata-v1`（尺子把 zip 元数据当内容）、`pinned-checkout-shadows-built-distribution-babel-v1`（钉版源码树缺构建产物）。phase-1 复跑写 `attempt-N/`（驱动 append-only）。第三轮：**c2 `tool-python-pptx-tool-v2`、c4 `tool-pillow-tool-v3` 零人工到达 `PAUSED_AT_REHEARSAL`**；追加评证 `contract-structural-defects-v2`（修复 schema 自带 `$defs` + 供应商拒绝原话）、`validator-parity-single-ruler-v1`（Core/导出 runtime 六个结构 profile 单尺，安全例外首起即修）、`verifier-reason-details-v1`（裁决者 `reason_details` 进证据与分歧诊断）。第四轮：**c1 `tool-xlsxwriter-tool-v1` 也到达 `PAUSED_AT_REHEARSAL`**（三例达标：c1 v1、c2 v2、c4 v3）；phase 2 首跑三例在 Agent 供应商预检 `PROVIDER_UNAVAILABLE`（http 503，零 Agent 调用）暂停，待网关恢复复跑；评证追加 `verifier-reason-details-v1`、`autopilot-failed-substage-projection-v2`（阻塞子站投影）。驱动 phase-2 曾覆盖 c1/c2/c4 顶层首轮报告（已修为 `phase2-attempt-N/`，损失已在 EXPLORATION_LOG 诚实记录）。c3（归属策略第二把尺子）、c8（钉版源码树缺数据）、c7（上游限流未映射）各为单例待第二起；c5/c6 界内未收敛；冻结协议待 phase 1 收敛 |
| 模型通道（2026-09-03） | GPT 侧网关额度用尽持续 503。新增**显式** Claude 网关通道:`REPOPROOF_DRAFTER_BACKEND=anthropic-gateway` + `src/repoproof/agents/anthropic_gateway.py`（Anthropic 协议、结构化输出=强制工具调用,拿不到 `tool_use` 即 `ANTHROPIC_STRUCTURED_OUTPUT_NOT_ENFORCED`,不收散文）;入口 `scripts/run_with_claude_gateway.sh`（凭据从 Claude Code 设置读入、仅传子进程,仓库不留第二份密钥）。**裸改 `.env` 不可行**:该网关的 OpenAI 兼容 shim 对 Claude 接受 `json_schema/strict` 却不强制（假成功类事故 `incident-openai-shim-schema-not-enforced-for-claude-v1`,证据 `harness-change-anthropic-enforced-drafting-channel-v1`）。Agent 侧零改代码,`PROVIDER_READY`/native 协议。phase 2 三例（c1/c2/c4,claude-sonnet-5）全 FAIL,同一签名:`LimitsExceeded` @ 20 次调用、实现未写、oracle 0/N;`max_model_calls: 20` 冻结在任务合同,不得为通过而上调 —— 模型侧结果,如实记账 |
| 题面过拟合与模型对照（2026-09-03） | 用户质疑是否存在过拟合/欺瞒。查证:`src/` 无按模型名分支的行为代码（模型名只出现在注释与事故记录）;唯一按模型命令风格调过的 context projector 本批未启用。**但确有对“当初唯一用过的模型”的过拟合**:Agent 题面声称 sandboxed Linux container（实为 macOS 宿主会话目录）且从不给绝对工作目录,GPT 恰好无视该声明直接开工,Claude 按容器约定 `cd /root` 后花 15/20 步找路。三例同指纹立案 → `harness-change-agent-task-statement-truthful-environment-v1`（题面据实描述 + 按运行渲染绝对工作目录 + 预告扫描规则）。效果:策略拒绝 1/3/1 → 0/0/0,找路耗步 ~15 → 0。**修复后同题对照**（冻结预算 20 次调用）:sonnet-5 三例 0 写入全 FAIL;**opus-5 的 c2/c4 `PASS_ADAPTED` 且 `VERIFIED_TOOL_READY` 并导出**（c1 撞输入 token 预算）。两例随后卡 fresh audit `WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT`（新输入上冻结控制件分歧,单例待第二起）。此前“GPT 同预算完成过”的说法已更正:GPT 从未跑过这三题的真发站 |
| M6.3 phase 1 第 6–9 轮（09-03，Claude 通道 opus-4.8） | 每轮都把一类 Harness 缺陷追到根：`runtime-closure-disagreement-routing-v1`（`WORKSPACE_RUNTIME_*` 分歧码路由+entrypoint 归 reference 写）、`delivery-shape-self-contradiction-v1/v2`（文档自相矛盾点名字段+修复上下文不再崩）、`verifier-verdict-consistency-named-v1`（通过却带原因码→机制码+规则进提示词）、`projection-diagnostics-everywhere-v1`（所有投影拒绝带 loc/msg）。c7 自检已能 1 轮通过并冻结 `tool-nbformat-tool-v2`，倒在 preflight smoke（合同 smoke_command 引用不存在的 `spec.json`）——自检不跑 smoke 第九轮修成 `selfcheck-runs-smoke-v1`（第十轮生效：c6/c7 都在冻结前抓到 smoke 失败）。第十轮再修两类：`structural-validation-path-details-v1`（结构码每行带路径/规则/外链）、`smoke-command-semantics-taught-v1`（三份提示词写明 smoke 单独运行须退 0 + 投影拒绝非成员文件参数）。第十一轮：**c6 `tool-icalendar-tool-v1` 零人工到达 `PAUSED_AT_REHEARSAL`（第四例）**；再修三类：`contract-repair-cannot-weaken-validator-v1`（安全例外：合同修复把 html_v1 降成 text_utf8_v1 让外链码消失）、`selfcheck-continues-after-unapplied-repair-v1`（回滚后交给下一位而不是终局）、`structural-contract-failure-alternates-owner-v1`（奇合同偶 reference）。第十二轮：**c7 `tool-nbformat-tool-v4` 零人工到达 `PAUSED_AT_REHEARSAL`（第五例）**；c5 追到回执代理丢 lru_cache 属性把上游打死（`import-hook-function-metadata-v2`，测量有效性例外）。c6/c7 phase 2 首打全败于零写入（Agent 整轮反推黄金比对含应用文件/README、封存路径、跨样例常量文件），修 `workspace-statement-teaches-public-fixtures-v1`（题面带公开样例摘要）；复打后 **c6 `tool-icalendar-tool-v1` 一轮 PASS → 新输入抽查通过 → 盘上 ACTIVE（M6.3 首个全程零人工到 ACTIVE）**，驱动误报 FRESH_AUDIT_FAILED 已修（`autopilot-fresh-audit-real-payload-v1`，c4 两次同病）；c7 仍零写入 → 题面 v2 点名应用文件先读。c7 attempt-3 能力 6/6 却因自测输出写进包内超补丁预算判 FAIL → 修 `agent-scratch-location-v1`（会话给 `REPOPROOF_SCRATCH_DIR`，题面教计数规则）。**c7 attempt-4 `tool-nbformat-tool-v4` 全程零人工到 ACTIVE（第二例）**。c5 第十四轮合同修复两次被拒理由不见 → 修 `repair-rejection-reasons-travel-v1`（拒绝码与诊断行随行至重试/记录/下一位）；c5 第十五轮两个新单例（修复改标签为 UserInputError、FIXTURE_REJECTED 不轮换）；c1 phase 2 倒在 zip 容器元数据（第二起）→ 修 `golden-identity-zip-canonical-v1`（验收等价性按容器成员，已冻结任务需重冻结受益）。c1 重冻结第 6 轮倒在归属筛查（第二起，'vendor' 列名）→ 修 `reference-ownership-policy-single-ruler-v1`。c1 第 7 轮第一份文档 schema 被拒即终局 → `projection-diagnostics-everywhere-v2`（schema 拒绝带 json path 进有据修复）。c5 第十六轮四轮四缺陷各修一次、倒在 3 次修复上限（单例）；c1 第 8/9 轮倒在 xlsx 容器内成员漂移不点名（单例）；c3 pygal 自检通过并冻结 v1、彩排倒在一致性预检（第三起）→ 修 `conformance-node-runnability-v2`（冻结前逐个执行候选）；c3 attempt-4 倒在 SVG 生成 id 漂移三轮不中（与 c1 xlsx 同根，第二起）→ 修 `divergence-locus-named-v1`（分歧行点名成员/行号+实际侧摘录）。**c3 attempt-5 `tool-pygal-tool-v2` 零人工到达 `PAUSED_AT_REHEARSAL`（第六例）**；phase 2 真发 4 步 PASS → READY 导出，新输入抽查倒在冻结控制件分歧（与 c2 pptx-v2 同形，第二起）→ 修 `selfcheck-fresh-agreement-probe-v1`（冻结前先用一个新输入探 reference↔裁决者一致性）。c3 attempt-6 `tool-pygal-tool-v3` 到彩排（新输入探针通过）；phase 2（v3）真发零写入——冻结件 SVG 注释带冻结日期（探针天级盲区，伪认证）→ 修 `reference-wall-clock-date-scan-v1`（安全例外首起即修）。c3 attempt-7 四轮四缺陷各修一次再倒在上限（与 c5 同形，第二起）→ 修 `selfcheck-bound-counts-stalls-v1`（预算按停滞计，硬上限 6）。c3 attempt-8 `tool-pygal-tool-v4` 五轮四修到彩排（停滞预算生效）；phase 2（v4）真发 PASS → READY 导出，新输入抽查再分歧（`SUMMARY_BALANCE_MISMATCH, MODEL_SVG_BAR_VALUE`，诊断随行生效；第三起）；c5/c1/c8 最后一轮各一次均失败并记入终态。**M6.3 探索批收口**：`docs/m6_3_closeout.md` + `m6_3_terminal_states.json`；终态 ACTIVE c4/c6/c7、READY 未 ACTIVE c2/c3、失败 c1/c5/c8、N0 预期拒绝成立；晋级门未达成；29 份 HarnessChangeEvidenceV1；`static_site_v1` 未实现；协议仍 DRAFT_NOT_FROZEN，收口时 SHA-256 `5dfb74eabc94908fdff213de9671245247e3d58ab2a341cffc1ea3e6dc81a67b`（记录，非预注册冻结）。收口后续：c2 `tool-python-pptx-tool-v3` 重冻结到彩排（双新输入探针冻结前抓到裁决者季度字段错）；c3 attempt-9 失败暴露 builder 诊断裸类 → 修 `builder-failure-diagnostics-v1`（两仓库同指纹）。c2 v4 净室 replay 绿（判定尺生效）、抽查 REVOKED（emoji 输入 adapter exit 2，AGENT_ADAPTER，需 v5）；c3 attempt-10 机制全生效仍败（binding-control 路由单例 `38b1c4063e8f5dfe`）；`static_site_v1` 落地（清单第七项，合同可选 `directory_profiles`）。**一切未提交未推送** |
| 本地质量线 | 全量 pytest `PYTEST_EXIT=0`：第 39 轮（09-03）2331 passed / 60 skipped / 0 failed（第 35 轮 2320/60/0；第 19–25 轮各有 4–5 个台账过期项，皆为新增 run 后 gate/summary 未重建或 hosts_covered 棘轮未追加，官方脚本重建后复跑全绿）（M6.2 收口时 2131/60/0）（退出码直接落文件核对，不经管道）；Ruff 0；mypy 188 文件 0；`git diff --check` 通过；Streamlit 双入口 render smoke 与 product-mode 90/90 |

关闭边界：本节是本机工作树事实，不代表远端 CI 已运行；八例是**记录案例**，不是任意仓库
成功率；`SUPPORTED` 表示该交付拓扑在受支持范围（公开 Python、单一明确能力、本地 CPU、离线
工作区）内已完成资格批次，不表示 MCP 或服务型仓库支持。

不变铁律：Agent 自述不算成功；冻结合同、历史 run、旧 ledger 与旧指标不改写；held-out 只隐藏
实例字节，不隐藏规范；Product 发次不计 Benchmark；本地工作树与远端 GitHub 严格区分。

## Previous status (2026-08-31, M6.2 qualification v2 frozen; N0/B1/B2/C1/C2 terminal, C3 next)

**主产品定位不变：GitHub 单能力 → 经独立验证的本地工具。M6.2 只新增
一种实验性交付拓扑 `workspace_bundle_v1`，让受控输入生成离线多文件工作区；
没有启动 M7 sidecar，也没有恢复旧宿主适配产品线。**

| Anchor | Value |
|---|---|
| 本地状态 | `codex/m6-2-workspace-bundle-qualification`，基线 `main @ 0a8034a`；当前工程 HEAD `38b1b10`，本节列出的提交均仅在本地，未推送、未发布 |
| 工程身份 | 当前可执行 `src/repoproof` 树哈希 `4ec8f553aa66ab7592861cad202342bde59417d6af996a0fb6666d22d4a78ea9`；每个既有终态继续绑定产生它时的 framework commit/树哈希，后续通用修复不改写历史身份 |
| Profile 状态 | `workspace_bundle_v1 = EXPERIMENTAL`；`cli_v2` 旧语义不变；MCP 稳定拒绝 `WORKSPACE_BUNDLE_MCP_NOT_SUPPORTED` |
| 合同与执行 | additive ToolSpec v4 + `WorkspaceArtifactContractV1`；一个本地文件/目录 → 一个调用前不存在的新目录；临时构建、四层验证通过后原子落位，失败清理半成品 |
| 可信证据 | Harness 在 Agent 外生成 `ArtifactManifestV1` 和目录树哈希；结构、通用格式、task-owned 语义 verifier、可运行 smoke 四层独立；输入/产物目录/upstream-result 三项反事实；clean replay 与 fresh audit 重新取证 |
| Product/UI | `ProductActionResultV2` 仍将 Worker/Pipeline/Operational 分开；Studio 支持蓝图 → 冻结 builder → 输入/期望树预览与确认 → 目录 fresh audit；工具库可重新验证、打开目录和生成确定性 ZIP |
| 事故与 repair | 每个失败 Agent 轮及每个失败 v4 Product action追加 public-only `ProductIncidentV1`；只有公开 `AGENT_ADAPTER` + 实际 diff 可 repair。意图安全现按凭证、网络、浏览器、生命周期、运行时和外部副作用分类，并区分可撤销/不可逆外部写入；匿名正控保证本地敏感数据离线处理不被误拒。非安全单例仍不得改 Core |
| 特例门 | 自动扫描九个 prereg case id、仓库身份和 commit；M6.2 新通用模块为零命中。旧 Lab 已有 `browser-use`/`pdfplumber` 命中被显式列为冻结基线，不冒充本次新增 |
| 冻结协议 | `docs/m6_2_workspace_bundle_qualification_v2.yaml`，SHA-256 `57ef6d57919ac098584dd1513d1ed6019e5395907d3ab7f468d08438e5913ce6`；固定 N0 → B1/B2 → C1–C6、默认 LiteLLM/API 网关起草和 mini-swe 实现，批次内禁止切换后端；旧 v1 `BLOCKED_BEFORE_EXECUTION` 记录保留不改 |
| Wheelhouse | B1/B2/C1–C6 共 **178 个** macOS arm64 / Python 3.12 wheel 已逐文件冻结名称、大小与 SHA-256，并绑定八个目录 root；流水线只能消费预注册字节，缺失、额外或篡改均在 Agent 前停止 |
| 零模型 canary | `workspace_assembler` 完整链已通过装配、四层公共控制、导出和 fresh audit 到 `ACTIVE`；JUnit SHA-256 `b61e615a1b1a6d8b743c1b3d773df782eefe9b86a5170b2cb174be50b384a572`，只证明通用 fixture，不代替八仓资格 |
| N0 终态 | `n0-credentialled-browser-side-effect = EXPECTED_REJECTION`；原因 `UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT`，责任 `USER_INPUT`，0 仓库执行、0 Agent、0 repair、0 导出。随后匿名矩阵补齐在线 API、持续监控和可撤销外部写入表达，仍保护本地离线账单处理不被关键词误拒 |
| B1 终态 | `b1-cookiecutter-research-project = FAILED`；Journey `6ecd00052933496f8f665b8ce410118f` 已完成仓库分析、口语需求采用、v4 合同审核、三组真实输入/期望工作区确认与冻结装配。正式 rehearsal 在上游 conformance 预检因冻结 wheelhouse 缺少所选公开测试节点需要的 `pytest-mock` 而 `BLOCKED`：责任 `HARNESS`，原因 `UPSTREAM_CONFORMANCE_ENVIRONMENT`，0 Agent、0 repair、0 导出。冻结任务不补依赖、不换节点、不改写 |
| B2 终态 | `b2-csvkit-reconciliation-workspace = FAILED`；Journey `a90d320c1d5c47aeaacf85295ca1f108` 在一次起草与一次公开投影修正后仍未形成合法 workspace 合同，责任 `EXTERNAL`、原因 `DRAFTER_INVALID_MODEL_OUTPUT`，0 Agent、0 repair、0 导出；没有为了案例通过而放宽协议 |
| C1 终态 | `c1-pdf-evidence-review = FAILED`；Journey `0259b595a5e84815bb6e02ef9642d3f9` 的三种自然场景被 builder 生成成同一精确输入，通用唯一性门以 `FIXTURE_INPUT_DUPLICATE` 停止，责任 `CONTRACT`，0 Agent、0 repair |
| C2 终态 | `c2-offline-web-briefing = FAILED`；Journey `264d21c622ee4dd9be1b97739a7ec942` 的 builder 未遵守 `FixtureBlueprintV1.parameters` 协议，以 `FIXTURE_BUILDER_FAILED` 停止，责任 `CONTRACT`，0 Agent、0 repair |
| 通用 authoring 修复 | C1 与 C2 两个独立仓库形成同一 `FIXTURE_BLUEPRINT_PARAMETER_BINDING_MISMATCH` 公开指纹。匿名负控先失败、修复后通过；`tool_drafter` 现明确蓝图只有五个顶层字段，并在合同起草期拒绝未显式绑定 `blueprint['parameters']` 的 builder。证据见 `HarnessChangeEvidenceV1`，Core 特例扫描零新增命中；C1/C2 历史终态不重跑、不改写 |
| 真实执行事实 | 当前正式批次为 **N0 1 个预期拒绝、B1/B2/C1/C2 4 个唯一失败终态、0 个真实 Agent 发次、0 个新增 ACTIVE workspace**。这些事实首先暴露准入、合同和 fixture 层问题，尚未形成 workspace Agent 成功率或模型能力结论 |
| 本地质量线 | `38b1b10` 的 fixture authoring 定向 pytest、资格协议特例扫描、Ruff 与 `git diff --check` 通过；此前 `a5108b7` 全量 pytest、Ruff、mypy 为 0。批次关闭前仍必须重跑全量质量线 |

关闭边界：工程候选与冻结协议都不等于资格关闭。只有 B1/B2 + 至少四个复杂案例 `ACTIVE`（含 SQLite/二进制工作区
与可运行应用）时，profile 才可升级为 `SUPPORTED`。

不变铁律：Agent 自述不算成功；冻结合同、历史 run、旧 ledger 与旧指标不
改写；held-out 只隐藏实例字节，不隐藏规范；Product 发次不计 Benchmark；
本地工作树与远端 GitHub 严格区分。

## Previous status (2026-08-31, M6.1 alternate-workflow qualification closed locally)

**主产品线仍是“GitHub 单能力 → 经独立验证的本地工具”。本次没有扩展
M7 或旧宿主适配线，而是用四个不同工作场景、输入和可读文本产物，验证
Studio → Core → Agent → 独立语义验证 → clean replay → fresh audit 的完整旅程。**

| Anchor | Value |
|---|---|
| 本地分支 | `codex/second-multiformat-qualification`；本节只描述本地事实，未授权推送或发布 |
| 框架锚点 | `4740e84d19c12afe69101667abe60da83a968f09`；可执行 `src/repoproof` 树哈希 `18ce970e463e51c3e101fa48eaabe54adb6e299744f22b95e7d09862dc3473fc` |
| 冻结协议 | `docs/m6_1_multiformat_qualification_v3.yaml`，SHA-256 `5def32f80d8c3f614d81726b1dbcb52c002934ef72d91004eb08da21d7729da4`；已完成案例不因后续通用修复重跑，只从受影响案例的合法断点继续 |
| Append-only 结算 | `docs/qualification_runs/m6_1_multiformat_v3/m6-1-multiformat-v3-20260831.json`；记录状态 `PASSED`，内嵌四份 `SemanticVerifierEvidenceV1` 完整证据并绑定协议、框架、task、run 和 artifact |
| RISpy | `tool-rispy-screening-table-v1` / `tool-rispy-screening-table-v1-20260831-013002`；CSV；历史 `VERIFIED_TOOL_READY`、clean replay PASS、fresh audit PASS、当前 `ACTIVE`、package `OK` |
| Pint | `tool-pint-field-kit-v1` / `tool-pint-field-kit-v1-20260831-015804`；自包含 XHTML；同上五项全部成立 |
| NetworkX | `tool-networkx-dependency-risk-v1` / `tool-networkx-dependency-risk-v1-20260831-022622`；TSV；同上五项全部成立 |
| Biopython | `tool-biopython-fasta-shortlist-v1` / `tool-biopython-fasta-shortlist-v1-20260831-030612`；Markdown；同上五项全部成立 |
| 语义可信边界 | 每仓 task-authored verifier 均通过实际输入、artifact 和 upstream-result 三项反事实控制；Core 只执行统一协议、隔离、身份绑定和上游调用取证，不含四仓领域特判 |
| Repair 加固 | candidate/reference 内部异常按不含消息和输入的安全代码位点指纹分类；只有 manifest + 回执绑定的公开成功样例可作正控；reference 执行故障不再自动改写 truth；四文件控制束 repair 有 durable marker、完整回滚和 fail-closed 恢复 |
| 指标边界 | 四仓真实发与彩排均为 Product 事实，四个 `counts_toward_*` 字段为 false；不能当作 Benchmark Lab 模型能力成绩，也不能外推为任意仓库成功率 |
| 本地质量线 | 1972 tests collected，全量 pytest 退出 0；Ruff 全仓 0 错；mypy 180 个源码文件 0 错；公开 claim 检查、`git diff --check` 与资格定向回归全部通过 |

不变铁律：Agent 自述不算成功；冻结合同、历史 run、旧 ledger 与旧指标不
改写；held-out 不向 Agent 泄漏；fresh audit 决定当前运营状态；本地提交与
远端 GitHub 状态严格区分。

## Previous status (2026-08-29, M6.1 Product Journey Reliability closed locally)

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
