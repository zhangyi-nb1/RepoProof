# Project Evolution — how the mechanisms were EARNED

None of the harness below was designed up front. Each mechanism
exists because a real recorded failure demanded it; the negative
results are kept on the record.

```
LocalFlow (file-ops harness, prior project)
  └─ business scope proved too narrow → new problem chosen:
RepoProof — verifiable open-source capability adoption
  ├─ Gate 2/2.5   deterministic evidence chain BEFORE any agent:
  │               frozen contracts, trust zones, trace hash chain,
  │               reference-calibrated oracles, negative controls
  ├─ Gate 3A–3C   one real agent (mini-swe-agent + deepseek-v4-pro):
  │               chonkie 4/33 → 31/33 — and an honest FAIL
  │               (missed upstream-error wrapping; replayed clean)
  ├─ Gate 4A      budget-state observations → NULL RESULT (kept)
  ├─ Gate 4B      Coverage Ledger → first voluntary Submit,
  │               outcome unchanged 31/33 (self-report ≠ verification)
  ├─ Gate 5/5.1   second domain rank_bm25 → SEMANTIC_SUBSTITUTION
  │               (agent invented its own BM25) + token budgets made
  │               real after a paper-only cap was exposed
  ├─ Gate 6       preregistered solvable task FAILED — the harness
  │               caught ITS OWN bug: HARNESS_PROMPT_CONTAMINATION
  │               (hardcoded first-task text leaking into prompts)
  ├─ Gate 7       clean-prompt re-run: 1/11 → 8/11, still FAIL —
  │               decomposed into CONTRACT_UNDERSPECIFICATION
  │               (a rule living only in YAML comments; task-author
  │               fault) + agent text=None omission (n=2 domains)
  ├─ Gate 7.1     the fix went into the SPEC, not the prompt:
  │               RequirementSpec · ContractAdequacyGate ·
  │               PromptManifest · Responsibility Matrix ·
  │               host InputContractGuard (zero LLM calls)
  └─ Gate 7.2     corrected-spec single run → FIRST PASS_ADAPTED
                  (18/18 + held-out, clean_adoption replay,
                  voluntary submit at 16/20 calls)
```

## What the timeline demonstrates

1. **Problem-first harness building** — measures were added only
   after a real failure trace justified them (rule: no speculative
   guards).
2. **Negative results are preserved** — budget awareness (null),
   Coverage Ledger cross-task effect (unsupported), both still in the
   benchmark and taxonomy; neither is claimed as a win.
3. **The harness audits itself** — two of the nine failure types are
   the harness's own bugs (prompt contamination, contract
   underspecification), found by the same evidence chain that judges
   agents, disclosed with the same severity.
4. **The decisive fix was specification & responsibility, not
   prompting** — the jump to PASS_ADAPTED came from making the
   contract adequate (typed requirements, public truth table,
   runnable public tests) and re-owning deterministic input
   validation to the host, NOT from tuning prompt wording. That is a
   claim about THIS case, not a general law (see CLAIMS_MATRIX F3/F8).
5. **Preregistration held** — every real run was preregistered,
   single-shot, never re-run for a better verdict.
