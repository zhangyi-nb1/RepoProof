# Changelog

## Unreleased — 2026-08-31 · M6.2 verified offline workspace candidate

- Added a deterministic pre-repository intent safety gate. Explicit credentials,
  runtime network/browser use, long-running lifecycle, GPU/remote runtime and
  irreversible external effects now stop with stable public reasons before a
  clone, drafter, Agent, repair round or export; the credentialled irreversible
  combination has its own dominant reason code.
- Added exact consumption of preregistered wheelhouse bytes. A draft may carry
  a no-follow `wheelhouse/` plus hash manifest; Product build verifies the
  complete file set and hashes, copies it atomically into the execution
  wheelhouse and refuses to re-resolve equivalent packages from an index.
- Made every property in newly model-authored delivery requirements mandatory
  in the provider-enforced JSON schema. Compatibility defaults still load old
  records, but can no longer turn an omitted browser or external-side-effect
  declaration into a new safe claim.
- Added additive ToolSpec v4 and experimental `workspace_bundle_v1`: one local
  file or directory produces one new atomic offline workspace directory.
- Added no-follow path/resource enforcement, deterministic directory manifests
  and tree hashes, generic format checks, task-owned semantic verification,
  bounded runnable smoke checks and input/artifact/upstream-result
  counterfactual controls.
- Extended clean replay, fresh audit, package identity, registry projection and
  Studio to directory artifacts. MCP refuses the profile; deterministic ZIP is
  transport only.
- Added frozen fixture builders and scenario blueprints so LLMs propose cases
  but cannot author trusted PDF/SQLite/directory truth bytes.
- Added public-only `ProductIncidentV1`, evidence-gated generic Harness changes
  and preregistered case-identity scans. Non-safety changes require matching
  incidents from two independent task versions.
- Added the RFC, execution runbook and nine-case preregistration. Protocol v2
  freezes 178 exact wheel files for B1/B2/C1-C6 and authorizes the fixed default
  gateway + mini-swe batch; pushing and publishing remain unauthorized. N0 has
  the expected zero-Agent rejection, but no workspace case is yet qualified.

## v0.2.0 — 2026-08-26 · GitHub capability → verified local tool

产品定位收敛的第一个发布:主线从"任意 Repository Adaptation"改为
"GitHub 单能力 → 经独立验证、可撤回的本地工具"。

### 产品线

- RFC-010 M0–M6 全部关闭:章程、首个工具闭环、半自动 intake、单命令旅程
  (`tool add/build/list/audit/withdraw/mcp`)、两批共 24 个真实公开仓库、
  Studio(Streamlit)接同一 Core 事实源 + 项目方预览 + 2 名目标用户理解测试。
- RFC-011 M5:ToolSpec v2 输出合同 + T6–T9 装配期检查 + append-only 运营
  发布状态(`ACTIVE` / `REVIEW_REQUIRED` / `REVOKED`),`historical_verdict`
  与 `operational_status` 双口径并列;MCP 仅对历史 READY + 当前 ACTIVE 开放,
  生成的 adapter 每次 list/call 复核账本。
- RFC-013 CapabilityPlanV1:证据化 surface 检测(签名 / file:line / 单必选
  参数 → 三档 confidence)、六条确定性路由、用户确认闸 + 执行闸。
- DIRECT_WRAP 确定性快路径:受信模板装配,零 agent 零模型,过同一条独立
  验证链拿 `PASS_DIRECT`。
- FailureAssessmentV1:九种 Product 终止码的纯读取侧投影,含 owner /
  repairability / 公开失败指纹。

### 判定与证据

- **主仓完整性进入最终判定**(`apply_integrity_to_verdict`):此前完整性对账
  排在 completion gate 之后、只落 report 不参与 verdict。修复后 `self_ok=false`
  → `BLOCKED/MAIN_DIR_INTEGRITY_UNATTRIBUTED`,原判定保留在
  `verdict_before_integrity`,trace 加 `gate.integrity_override`。
- **执行闸重查全部语义前提**:此前只查 `confirmed + sha`,而 sha 防的是
  "确认后被改",防不了"从未合法确认过";新增 `assert_plan_matches_source`
  把 plan 绑定 draft 上游 url + commit。
- 保护目录改为**结构性发现**(本仓 + 兄弟 git 仓),不再硬编码个人路径 ——
  硬编码在别人机器上等于保护集合为空。
- 上游采用回执:HMAC 签名 + 运行时实际加载模块 hash + 输入 digest + 采纳
  谓词四重绑定,缺采纳谓词一律判不通过。

### 诚实账

- `pyspellchecker` v1 假成功(冻结题面声明 JSON、oracle 验纯文本)保留为
  历史证据,运营资格撤回,冻结合同与真跑均未改写。
- **19 发 PRODUCT 记 PASS 而 `main_dir_integrity=MISMATCH`**(完整性当时不
  参与判定),10 发绑定已导出工具、8 个当时 ACTIVE。裁决:记事实 + 强制
  限定句,不撤回、不重跑;逐发 append-only 勘误,限定句由
  `check_public_claims.py` 机器钉死。工具功能证据不受影响(clean replay +
  fresh-input 抽查为独立证据线,均已通过)。
- 台账 product-* 编号勘误:08-25 批误从 51 起编与 08-23 批九连撞,改编为
  product-76..84;现 1..84 连续无缺号、撞号 0。

### 工程

- **CI 落地**:ruff 全仓 0 错 / mypy 可信链八包 0 错(豁免为显式登记的棘轮)
  / pytest 全量且 slow 不跳过。上线前 Linux 容器预演咬出五条真缺陷,含
  "保护目录 lower 化路径被当 fs 路径访问 → ext4 上快照静默漏保护"。
- 新增第二个机器可读事实源 `docs/product_summary.json`(extraction-only),
  `check_public_claims.py` 同步覆盖产品口径。
- `docs/PROJECT_MAP.md` 单页地图:代码分区(= mypy 边界)、四套编号对照、
  判定词汇三层。Benchmark Lab 执行驱动(`host_guided.py` 等)标注 **FROZEN**
  —— 功能面冻结但未退役,判定/安全缺陷照修。
- 面试材料(`CLAIMS_MATRIX` / `RESUME_CLAIMS` / `INTERVIEW_GUIDE`)重写到
  新定位,数字全部绑两个事实源。

### 已知未完成

OS 级隔离(M7,EXPERIMENTAL);8 个受完整性限定影响的工具尚未在干净环境
复样重跑;M6 两份用户测试原始记录表尚未归档;第三批真仓与真实模型演示
待授权。

## Unreleased — 2026-08-24 · M5 contract coherence and operational release state

- Added additive Tool Contract v2 output contracts for text, JSON, objects,
  arrays, and JSON Lines. New drafts must pass deterministic T6–T9 checks;
  existing frozen v1 contracts and sidecars remain unchanged.
- Generated public/held-out tests, release audits, and MCP adapters now parse
  actual stdout independently of golden-output equality, closing the M4
  `pyspellchecker` false-success class. Output-contract and release-ledger/MCP
  JSON paths reject the non-standard constants `NaN`, `Infinity`, and
  `-Infinity`, plus numeric overflow such as `1e400` and `-1e400` that would
  otherwise become a non-finite float.
- Added a strict append-only operational decision ledger with
  `REVIEW_REQUIRED`, `ACTIVE`, and `REVOKED`; `tool audit`, `tool withdraw`,
  `tool import-audits`, registry projection, and fail-closed MCP enforcement.
- Preserved historical `VERIFIED_TOOL_READY` facts while adding operational
  metrics. M4 batch two now reports historical READY 10, operational READY 9,
  and false-success 1/10 from the machine fact source.
- Migrated 22 existing fresh-input audit records by source hash: 21 ACTIVE and
  one REVOKED. Tool packages, manifests, frozen contracts, runs, and source
  audit ledgers were not rewritten.
- Added guarded same-command task-version upgrades: preflight runs before a
  real model call; candidates stage on the destination filesystem; the new
  REVIEW_REQUIRED decision is appended before atomic package switching; old
  package bytes move unchanged under `.repoproof-versions`; and the registry is
  atomically updated with `previous_versions`. Same-task replacement,
  downgrade, lineage mismatch, registry/package mismatch, and legacy MCP
  servers that still need detaching fail closed. A missing or drifting registry
  also blocks upgrade. The registry atomic replace is the commit point:
  catchable pre-commit failures restore the old package, while an interruption
  observed after commit preserves the consistent new package and registry.
  `SIGKILL`, power loss, or failed recovery can require manual inspection of
  canonical, archive, staging, and registry state; no universal crash rollback
  is claimed.
- Bound every managed package to its canonical directory, manifest, required
  provenance, exact `tool-<name>-vN` task lineage, run id, and contract hash.
  Package install/upgrade, registry mutation, MCP generation, and managed
  audit/withdraw paths serialize on the shared install lock, with compound
  release operations acquiring release second. The default read-only registry
  listing remains lock-free and fails closed on an intermediate state;
  generated MCP calls hold both locks from ACTIVE checking through execution
  and result publication.
- Hardened package and managed paths against symlink, special-file, and
  containment escapes, and control/output files against hardlinks. The
  existing top-level `.venv` is the sole reproducible environment exception,
  and `adaptation.patch` may not create or change it. MCP `--out` now requires
  a fresh per-call temporary result, validates it no-follow, and atomically
  publishes only after output-contract success. Upgrade preflight validates the
  complete registry before real-model budget is spent, and `audit --build`
  revalidates package-tree safety plus manifest/provenance identity before it
  can execute the rebuilt launcher.
- Clarified the enforcement boundary: operational status controls
  RepoProof-managed audit, MCP generation/runtime, and managed upgrades. It
  does not impose an OS-level ban on manually executing a retained
  `bin/<tool>` file.

## v0.1.0 — 2026-08-07 · MVP freeze: first credible PASS_ADAPTED + reproducible no-model demo

First public release. Research-grade MVP, scope: public Python /
Linux / CPU-first open-source capability-adoption tasks.

### The protocol (built across Gates 2–7.2)

- Frozen Task Contracts (+sha sidecars) with typed RequirementSpecs
  (owner / severity / public text / examples / oracle bindings)
- ContractAdequacyGate: 13 deterministic pre-agent checks;
  inadequate specs are `INVALID_TASK_SPEC` with zero model calls
- PromptManifest: hash-pinned Contract→Prompt projection (one shared
  renderer for freeze / gate / run)
- Host InputContractGuard: deterministic input validation owned by
  the consumer (stable `INVALID_DOCUMENT_INPUT`), never by agents
- Single agent loop (mini-swe-agent `DefaultAgent`) in hardened
  containers (non-root, cap-drop ALL, network=none, digest-pinned)
  with policy causality, real token budgets, append-only hash-chained
  trace
- Independent verification: Capability (reference-calibrated oracle +
  held-out fixtures) / HostRegression / Policy / clean-room Replay;
  Completion Gate ignores agent claims by construction
- Evidence plane: content-addressed artifacts, run manifests,
  redaction-scanned committed bundles, `verify-bundle`

### Recorded results (fact source: docs/benchmark_summary.json)

- 12 recorded runs across 3 capability domains; **1 PASS_ADAPTED**
  (frontmatter-v2 corrected-spec run: 18/18 incl. held-out,
  clean_adoption replay, voluntary submit at 16/20 calls);
  11 honest FAILs incl. chonkie 31/33 and rank_bm25 9/12 rejections
- 9-type failure taxonomy incl. two self-caught harness bugs
  (HARNESS_PROMPT_CONTAMINATION, CONTRACT_UNDERSPECIFICATION)
- Preserved negative results: budget-awareness ablation (null),
  Coverage Ledger (experimental, default off)

### Gate 8 additions (this release)

- `repoproof demo list|verify|replay` — no-model demos: gate-decision
  recomputation over committed evidence + fresh-container replay of
  the PASS_ADAPTED adapter
- `repoproof task init|check` — DRAFT task scaffolding + read-only
  adequacy pre-flight (READY_TO_FREEZE / INVALID_TASK_SPEC)
- Machine-readable fact source (`docs/benchmark_summary.json`,
  extraction-only) + Claims Matrix + deterministic
  `scripts/check_public_claims.py`
- Docs: README repositioning, ARCHITECTURE (four planes),
  PROJECT_EVOLUTION, DEMO/DEMO_SCRIPT, RESUME_CLAIMS,
  INTERVIEW_GUIDE, HANDOFF_STATE

### Boundaries (unchanged by this release)

Not a security sandbox; traces are tamper-evident, not tamper-proof;
no generality claim (each task needs human contract/oracle/controls
engineering); Gate 7.2 is a corrected-spec positive case, not a
single-variable improvement.
