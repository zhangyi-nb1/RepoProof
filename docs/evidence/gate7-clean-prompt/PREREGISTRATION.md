# Gate 7 — Preregistration (recorded BEFORE the single real run)

User-approved gate: re-run the SAME frozen frontmatter task exactly
once with the decontaminated, contract-driven prompt, to attempt the
first credible PASS_ADAPTED closure. Committed before the run; the
verdict is final regardless of outcome — **no re-runs**.

## Delta vs the Gate 6 run (full disclosure)

- Contract file: same task semantics; sha changed
  `9e1efd43…` → `870a2649…` solely because Gate 6's post-run fixes
  added prompt-driving fields (`target_project.package`,
  `target_project.entry_point`) and `source_repo.import_module`.
  Oracle tree, fixtures, reference records, acceptance commands and
  ALL budgets are byte-identical to the Gate 6 run.
- Prompt: rendered by contract-driven `render_agent_prompt`
  (zero cross-task tokens, pinned by `tests/test_agent_prompt.py`);
  eyeballed clean pre-run. This is the ONLY intended variable vs
  Gate 6 (HARNESS_PROMPT_CONTAMINATION removed).
- Everything else frozen and unchanged: provider deepseek-v4-pro via
  REPOPROOF_* env (user-directed), native tool-calls, temperature 0,
  `--budget-visibility`, Coverage Ledger OFF, budgets 20 steps /
  40 commands / 400k in / 40k out tokens.

## Command

`repoproof agent-run --contract contracts/adopt-frontmatter-local-ingest-v1.yaml --budget-visibility`

## Preregistered expectation (stated ONLY here + final report)

- Expected: **PASS_ADAPTED** via C∧R∧P then clean_adoption replay.
- If FAIL: taxonomy-type it honestly; the HARNESS_PROMPT_CONTAMINATION
  fix is then verified only as "prompt clean" (its sufficiency for
  outcome remains unproven); no re-run either way.
- This run also serves as the real-run verification of the Gate 6
  prompt fix, which is currently marked "FIXED (post-run, unverified
  on a real run)" in docs/FAILURE_TAXONOMY.md.

## Controls on record (unchanged from Gate 6, not re-run)

- Positive control 11/11 PASS; negative control rejected;
  direct baseline FAIL capability 1/11, regression 3/3
  (`docs/evidence/gate6-positive-task/`).
