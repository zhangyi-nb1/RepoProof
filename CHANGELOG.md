# Changelog

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
