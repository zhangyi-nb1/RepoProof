# RepoAdoptBench-mini — consolidated results

Two adoption tasks, six runs, one agent (mini-swe-agent 2.4.6 +
deepseek-v4-pro, native tool-calls, temperature 0, 20-model-call
budget). Every number below comes from a committed evidence bundle
(`docs/evidence/…`) with a verified trace chain and a 10/10
verify-bundle. **No run below reached PASS_ADAPTED — every verdict is
an honest FAIL**, each with a deterministic failure reproduction.

rank_bm25 provenance wording: source_commit=`47aa3ddf`,
source_relation_to_release=after_tag_0.2.2,
upstream_declared_version=0.2.2,
build_metadata_workaround=PKG_INFO_injection. (The pinned commit is
NOT the official 0.2.2 tag itself.)

| Run | Task | Mode | Capability | Regression | Policy | Replay | Verdict | Model calls | Cmds | Tokens in/out | Adaptation | Agent wall | Failure type | Harness capture point |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| chonkie-direct | v3 | direct (no agent) | 4/33 | 4/4 | PASS | failure_reproduction PASS | FAIL | 0 | 0 | — | 0 files | — | (baseline) | reference oracle |
| chonkie-agent | v3 | agent baseline | **31/33** | 4/4 | PASS | failure_reproduction PASS | FAIL | 20 (LimitsExceeded) | 30 | not recorded | 1 file / 134 ln | 126.5s | CONTRACT_REQUIREMENT_OMISSION | oracle `test_upstream_errors_wrapped` |
| chonkie-budget (4A) | v3 | + budget visibility | 31/33 | 4/4 | PASS | failure_reproduction PASS | FAIL | 20 (LimitsExceeded) | 32 | not recorded | 1 file / 121 ln | 180.6s | CONTRACT_REQUIREMENT_OMISSION | same; budget visibility = null result |
| chonkie-ledger (4B) | v3 | + coverage ledger | 31/33 | 4/4 | PASS | failure_reproduction PASS | FAIL | **17 (Submitted)** | 33 | 251,387 / 11,412 | 1 file / 105 ln | 155.1s | CONTRACT_REQUIREMENT_OMISSION (+ self-report vs verification gap: ledger said 12/12) | oracle; first voluntary submit |
| bm25-direct | v4 | direct (no agent) | 1/12 | 3/3 | PASS | failure_reproduction PASS | FAIL | 0 | 0 | — | 0 files | — | (baseline) | reference oracle |
| bm25-agent | v4 | agent (budget+ledger) | **9/12** | 3/3 | PASS | failure_reproduction PASS | FAIL | 20 (LimitsExceeded) | 35 | 290,819 / 11,122 | 1 file / 335 ln | 172.5s | SEMANTIC_SUBSTITUTION (+ HARNESS_SIGNAL_IGNORED: ledger 0/9) | oracle `test_rankings_match_pinned_reference` (public AND held-out) |

Notes:
- "Tokens not recorded" for the first two agent runs predates the
  litellm usage hook (Gate 4B infra); UNKNOWN is never written as 0.
- Both token-recorded runs exceeded the contract's
  `max_input_tokens_total=250000` while Policy passed — a contract
  integrity hole fixed in Gate 5.1 (real pre-call enforcement +
  policy check); historical results are preserved unchanged.
- Coverage Ledger status: experimental, default OFF,
  cross_task_effect_not_supported (drove an early submit on chonkie,
  ignored entirely on rank_bm25).
