# RepoProof v0.1.0 — Release Notes

**Evidence-driven harness for verifying whether an agent-generated
open-source capability adaptation actually satisfies a frozen
adoption contract.**

## Headline

A real coding agent (mini-swe-agent + deepseek-v4-pro) earned the
project's **first PASS_ADAPTED** under full independent verification:
capability 18/18 including held-out inputs, host regression 3/3,
policy clean, and a clean-room replay in a fresh container — after
the task specification was made machine-checkably adequate
(RequirementSpec + public truth table + 13-check adequacy gate +
host-owned input guard). The same system had previously REJECTED
highly complete artifacts (chonkie 31/33, rank_bm25 9/12) as honest
FAILs with deterministic failure reproduction — that discipline is
the product.

## What's in the box

- One autonomous agent loop, everything else deterministic
- Frozen contracts / adequacy gate / hash-pinned prompt projection
- Independent Capability / Regression / Policy / Replay + a
  completion gate that never reads agent claims
- Tamper-evident traces, content-addressed artifacts, committed
  redaction-scanned evidence bundles
- **No-model demos**: `repoproof demo verify|replay` recompute
  verdicts from evidence and replay the PASS_ADAPTED adapter in a
  fresh container — no provider needed
- Task scaffolding: `repoproof task init|check` (DRAFT →
  READY_TO_FREEZE pipeline, no auto-guessing, no auto-freeze)
- Machine-readable fact source + forbidden-claims checker keeping
  README/benchmark/resume wording honest

## Scope and non-goals

Public Python repos, Linux containers, CPU-first tasks; three
capability domains recorded. NOT: any-repo support, success
guarantees, a malicious-code sandbox, a production platform, or a
general agent-improvement claim. Negative experimental results
(budget-awareness null; coverage ledger unproven) are preserved, not
hidden.

Full history: [CHANGELOG.md](CHANGELOG.md) ·
facts: [docs/benchmark_summary.json](docs/benchmark_summary.json) ·
claims: [docs/CLAIMS_MATRIX.md](docs/CLAIMS_MATRIX.md)
