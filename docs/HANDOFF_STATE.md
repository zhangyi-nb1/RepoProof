# RepoProof — Handoff State (authoritative snapshot)

> Purpose: the single in-repo status anchor for AI/human handoff.
> Update ONLY at gate boundaries; history below is append-only.

## Current status (2026-08-24, M0–M5 closed + M6 merged to main; project-owner preview passed + M7 candidate)

**RepoProof 的主产品线已从任意 Repository Adaptation 收敛为
GitHub Capability → Verified Local Tool。RFC-010 的章程、首个工具闭环、
半自动 intake、单命令旅程、两批真实仓指标均已落地；RFC-011 又补齐
输出合同一致性与 append-only 运营发布状态。M6 已把 Studio 接到同一 Core
事实源，但人工 Preview Validated 门尚未关闭。M7 已形成 fail-closed managed
sidecar 候选实现，只扩展当前本地工具产品；可信门未关闭，因此不能 ACTIVE。**

| Anchor | Value |
|---|---|
| 产品方向 | `docs/PRODUCT_REDIRECTION.md` + `docs/rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md` |
| M0–M3 | 全部关闭；CLI 主旅程=`tool add/build/list/audit/withdraw/mcp` |
| M4 批次一 | 12 个真实仓均通过流水线、重放与运营审计；见 `docs/EXPLORATION_LOG.md` |
| M4 批次二 | 12 submitted / 11 accepted / 10 历史流水线 READY / 9 运营可用 / 1 false-success |
| 批次二锚点 | `c5c958d` (`M4 批次二收官:9 个运营可用+1 false-success 撤回`) |
| 批次二事实源 | `docs/m4_metrics.json` + append-only audit/classification ledgers |
| False success | `tool-pyspellchecker-tool-v1`:冻结声明 JSON、reference/example/oracle 却验纯文本；运营 READY 已撤回，冻结史和真跑均未改写/重跑 |
| M5 输出合同 | 新 draft=ToolSpec v2；T6–T9 + actual stdout runtime parsing；37 份旧冻结合同原样加载 |
| M5 发布状态 | 本机 release ledger 22 条迁移决定：21 ACTIVE / 1 REVOKED；另 2 个早期 dogfood 无 fresh audit，保持 REVIEW_REQUIRED |
| M5 本地提交锚点 | `034bdf1`；本地 `main` 已关闭 M5，未推送 |
| MCP 执法 | 仅历史 READY + 当前 ACTIVE 可生成；M5 adapter 每次 list/call 复核 ledger；pre-M5 非 ACTIVE adapter 明示 `LEGACY_SERVER_MUST_BE_DETACHED` |
| M6 整合锚点 | 工程实现 `d7c1278`；`3818ccb` no-ff 保留 UI 历史；**2026-08-24 项目方三固定案例预览通过(P0=0,P1=5 全修复)后已 no-ff 合回 `main` 并推送 origin**；2 名目标用户理解测试仍待补 |
| M6 可信整合 | Core-only registry 投影；historical/operational/package health 三栏；ProductJobStateV2；Studio/Lab 共享 Core 写锁；Product/Lab 原生分账 |
| M7 候选锚点 | `8f6b43e` + clean-worktree 修复 `0d19e7d`；分支 `codex/m7-managed-sidecar-tools`，基于 M6、未合并、未推送 |
| M7 已成立范围 | ToolSpec v3 固定 sidecar profile；每次调用动态 loopback；CLI 单链；10 文件机器锚；发布 marker/registry/task 绑定；v3 MCP 硬阻断 |
| M7 当前可信状态 | **EXPERIMENTAL / REVIEW_REQUIRED**；强 U1–U4 receipt 已落地(2026-08-25:验收期取证会话=hook 注入 server 进程发签名链回执+交付面双跑,U4 等于式采纳;自证=正例全绿+五类攻击矩阵各自精确杀;host_guided v3 接线复用 A1 归因/gate 管道)。仍缺:v3 任务 host_guided 全链 E2E、OS 级网络/进程隔离、真实导出包 clean replay、单独授权真实仓 —— 不能称 verified、不能 ACTIVE |
| 当前质量基线 | M5=`1324 passed + 60 skipped`；M6 纯提交隔离工作树全量 pytest 退出 0（1455 collected）；M7 `0d19e7d` 干净工作树=`1434 passed + 63 skipped + 0 failed`；改动面 Ruff 与 diff-check 通过 |
| 后端资格 | Product Mode 缺省 mini-swe；DSH 旗标保留但工具谱系未资格化 |
| 当前阶段门 | **M6 项目方预览已过、2 名目标用户测试待补；M7 强 receipt(开发中,用户 2026-08-24 授权)/OS 隔离未关闭**；main/分支推送已获授权执行；发布、第三批真仓或任何新真实模型发次仍需授权 |

不变铁律：验证面无 LLM；held-out 对 agent 零泄漏；冻结合同与历史台账
不可改写；FAIL 也留完整证据；没量到即判死；Product Mode 与 Benchmark
Lab 分账，不用产品发次充模型能力成绩。

范围约束：当前只开发“GitHub Capability → Verified Local Tool”。旧的任意仓
适配定位与 Benchmark Lab 仅保留隔离、历史兼容和只读研究边界；不新增旧路线
功能、模型比较、研究任务、计分指标或 Lab UI。

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
