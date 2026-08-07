# Gate 6 — Preregistration (recorded BEFORE the single real run)

Committed before the agent run; the run happens exactly once and its
verdict is final regardless of outcome (PASS_ADAPTED / FAIL / BLOCKED —
no re-runs for a better result).

## Task

- Contract: `contracts/adopt-frontmatter-local-ingest-v1.yaml`
  (sha in sidecar; task package root in `*.package.json`).
- Upstream: python-frontmatter, pinned `dc7c0af5466b…` — which IS the
  official `v1.3.0` release tag (no build-metadata workaround needed,
  unlike rank_bm25).
- Deliberately low-complexity and solvable-by-design: calling the
  pinned library is the path of least resistance (structured
  `Post` object; zero randomness / floats / strategy branches), to
  test whether the harness can ground a first honest PASS_ADAPTED —
  not to inflate difficulty stats. BENCHMARK.md will label this row's
  difficulty accordingly.

## Frozen run configuration (single variable-free run)

- Provider: deepseek-v4-pro via REPOPROOF_* env (user-directed since
  Gate 3C), native tool-calls, temperature 0.
- `repoproof agent-run --contract contracts/adopt-frontmatter-local-ingest-v1.yaml --budget-visibility`
- Coverage Ledger: OFF (Gate 5.1 default; experimental status).
- Budgets: 20 steps / 400k input / 40k output tokens (relaxed vs prior
  tasks — preregistered here and pinned by
  `tests/test_gate6_positive_task.py`; benchmark rows must disclose it).

## Preregistered expectation (stated ONLY here + final report)

- Expected: **PASS_ADAPTED** via C∧R∧P then clean_adoption replay.
- If FAIL: taxonomy-type the failure honestly; no re-run.
- The expectation appears nowhere in the contract, prompt, oracle or
  any agent-visible surface.

## Controls already on record (pre-run)

- Positive control (trusted reference adapter): 11/11 PASS.
- Negative control (regex fence-stripper): FAIL on
  `test_records_match_pinned_reference[public+held]`.
- Direct baseline: honest FAIL — capability 1/11, regression 3/3
  (run `adopt-frontmatter-local-ingest-v1-20260807-170633`).
- Discovery: first baseline attempt BLOCKED on a real portability gap
  (distribution name ≠ import name); fixed contract-driven via
  `source_repo.import_module` (blocked run preserved:
  `…-20260807-170447`).
