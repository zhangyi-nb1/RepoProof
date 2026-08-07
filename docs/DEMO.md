# No-model demo walkthrough

Everything below runs WITHOUT any LLM provider — it works offline,
never spends a token, and is immune to API outages. All data comes
from committed, redaction-scanned evidence bundles.

## 1. List the cases

```bash
.venv/bin/repoproof demo list
```

Three registered cases: `frontmatter-v2-pass` (the PASS_ADAPTED
artifact), `chonkie-agent-fail` (31/33 → FAIL), `bm25-agent-fail`
(semantic substitution → FAIL).

## 2. Verify the negative case (why 31/33 is still FAIL)

```bash
.venv/bin/repoproof demo verify --case chonkie-agent-fail
```

Prints the exact inputs the completion gate saw — capability 31/33
(failed nodes listed), regression 4/4, policy PASS,
`baseline_failure_reproduction` replay — then RECOMPUTES the decision
table from those inputs and confirms it reproduces the recorded FAIL.
`agent_claim_consulted: false` is structural: claims are never gate
inputs.

## 3. Verify the positive case

```bash
.venv/bin/repoproof demo verify --case frontmatter-v2-pass
```

Same recomputation: capability 18/18 (incl. held-out), regression
3/3, policy PASS, replay `mode=clean_adoption status=PASS` →
recomputed verdict PASS_ADAPTED == recorded verdict. Shows the
TaskPackage root, adaptation root, trace sha and all four verifier
result hashes.

## 4. Replay the PASS_ADAPTED artifact in a fresh container

```bash
.venv/bin/repoproof demo replay --case frontmatter-v2-pass
```

Copies the COMMITTED agent adapter (67 lines) into a brand-new
container with the pinned upstream wheelhouse and re-runs the frozen
capability oracle: expected 18/18, zero model calls. This is the
"the artifact carries the capability, not the agent session" proof.

## Notes

- Public evidence copies are host-path-redacted; each run's original
  trace-chain sha is recorded in its run manifest (verified at run
  time). Live bundles under `runs/` can additionally be checked with
  `repoproof verify-bundle --run-dir …`.
- `demo replay` needs a docker daemon + the pinned caches; `demo
  verify`/`list` need nothing but the repo.
