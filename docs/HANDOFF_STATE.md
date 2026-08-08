# RepoProof — Handoff State (authoritative snapshot)

> Purpose: the single in-repo status anchor for AI/human handoff.
> Update ONLY at gate boundaries; history below is append-only.

## Current status (2026-08-08, after RFC-008 Gate A–E)

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
