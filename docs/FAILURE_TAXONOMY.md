# Failure Taxonomy

Typed failures observed by ACTUALLY RUNNING the harness — each entry
links a task, run, trace evidence and its handling status. Categories
are added only when a real instance exists.

| Type | Definition | Instance (task / run) | Evidence | Status |
|---|---|---|---|---|
| CONTRACT_REQUIREMENT_OMISSION | The agent skips a requirement written in the public contract but not exercised by the sample inputs | chonkie v3 / runs `145257`, `151829`, `154259` | oracle `test_upstream_errors_wrapped[*]` failing on text=None (`docs/evidence/gate3c-real-run/`, `gate4a-…`, `gate4b-…`) | OPEN (agent-side; deliberately never hand-patched) |
| SEMANTIC_SUBSTITUTION | The agent replaces the pinned upstream capability with its own semantically different implementation | rank_bm25 v4 / run `160831` | `test_rankings_match_pinned_reference` — scores (c-001, 3.660713) vs pinned (c-001, 4.325285) on public AND held-out (`docs/evidence/gate5-second-repo/`) | OPEN (agent-side) |
| BUDGET_EXHAUSTED | A contract budget is genuinely exhausted; hard goals unmet ⇒ FAIL, never BLOCKED | token overrun: 251,387 and 290,819 input tokens vs 250,000 contract cap while Policy passed (runs `154259`, `160831`) | run manifests in `gate4b-intervention/`, `gate5-second-repo/` | **FIXED (Gate 5.1)**: TokenBudgetedModel pre-call gate + max_tokens remaining cap + policy token check + FAIL/BUDGET_EXHAUSTED mapping |
| HARNESS_SIGNAL_IGNORED | The agent ignores a harness-provided signal entirely | rank_bm25 v4 / run `160831` — ledger untouched (0/9) while every observation carried `[LEDGER]` | `ledger.final` trace event; `gate5-second-repo/trace.jsonl` | RECORDED; ledger marked experimental, default OFF |
| BUILD_METADATA_INCOMPATIBILITY | Pinned-source builds fail on packaging metadata expectations (git-or-PKG-INFO version schemes vs git-archive staging) | rank_bm25 wheelhouse build | custom `version.py` needed PKG-INFO; staged injection `Version: 0.2.2` recorded in commit `ca72c02` | WORKED AROUND + documented (THIRD_PARTY_NOTICES wording) |
| TASK_SPECIFIC_HARDCODE | Harness code hardwires first-task names, breaking portability | distribution/env-probe/wheel-select/probe-script/ledger-source hardcodes found during Gate 5 | commit `ca72c02` diff | **FIXED**: contract-driven (`SourceRepo.distribution`, `Acceptance.probe_script`, `Capability.coverage_requirements`) with v1–v3 defaults |
| PROVIDER_UNAVAILABLE | The model provider backend is down; typed BLOCKED, zero agent construction | gpt-5.5 proxy episode (Gate 3B/3C prep) | `docs/evidence/gate3-preflight/blocked_provider.json` | RESOLVED (user-directed provider change) + ProviderAdmissionGate added |
