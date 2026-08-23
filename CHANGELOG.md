# Changelog

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
