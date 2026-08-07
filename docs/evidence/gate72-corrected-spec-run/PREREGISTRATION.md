# Gate 7.2 — Preregistration (committed BEFORE the single real run)

A **corrected-spec positive case**: after Gate 7.1 made the contract
adequate (RequirementSpec + truth table + public tests), fixed the
Contract→Prompt projection (PromptManifest) and sank deterministic
input validation into the host InputContractGuard, this run asks
whether a real agent can complete the REMAINING adapter
responsibility. It is NOT a single-variable experiment vs Gate 7 (the
task version, schema, prompt surface and guard all changed together);
no "one variable improved X" claim may be made from it.

## Frozen bindings

- Task: `adopt-frontmatter-local-ingest-v1-v2` (Gate 7's v1 untouched)
- TaskPackage root: `667b4ce3ae4e00d99d3f33fe681e2ae7afc4e1bd21a503f367029a326abc3349`
- Contract sha: `6fc81af7adc079827d0997a26437e5d720fd2bdc16468aaf6bfc1b991d2f329f`
- RequirementSpec sha: `3a3cc6188b09e05755622b0d836311f91284196dc0ff3a29307a70022bfe8f8d`
- PromptManifest sha: `781bb906944e6629bcd3476a639af38ef4384e5c718729e600e63febd546ee81`
- Rendered prompt sha (frozen projection): `83931a19074b3015749101d83be85948cb9d7fabf7f1d73c1925a7ee8501f4b1`
- Public test collection: 18 capability + 3 regression nodes,
  manifest sha `e6028becb92159f7e933bffc47d4e0dd0d50452544089502519c6a85108c922e`
- InputContractGuard sha: `f05f989656021fe6a01904c24f4038b2c75a56ac06939d52c42121f51c5a844b`
- Image: `python@sha256:4766d8b510c428e595d74b9cc5bbb2fae8e26316fffb4adc89908d79aacd58a2`
- ContractAdequacyGate: ADEQUATE (13/13) at commit 02e50a7; the gate
  re-runs before preflight — INVALID_TASK_SPEC aborts with zero calls.

## Provider / model (unchanged from Gate 7)

deepseek-v4-pro, openai-compatible, native tool calling,
temperature 0; expected canonical provider-config hash
`21f537380c779f8f8348a5cdd4be8034cba6aa2cc8c895a341bb2dc0f5b57d90`
(same as the Gate 7 run). Provider unavailable → BLOCKED, stop.

## Budgets (unchanged from Gate 7 — no relaxation for known failures)

20 model calls / 40 commands / 400k in / 40k out tokens / patch 8
files 400 lines / policy unchanged.

## Harness feature flags

- Coverage Ledger: OFF
- Budget observation text: OFF (`--budget-visibility` NOT passed);
  budgets recorded in trace only
- No critic, no reflection, no repeated-action guard, no recovery
  agent — the only new mechanisms are Gate 7.1's deterministic
  spec-side gates.

## Rules

ONE run. No re-run for any outcome, no human patches, no oracle
feedback to the agent, no model/budget changes. Verdict PASS_ADAPTED
only via Capability ∧ HostRegression ∧ Policy ∧ clean_adoption
Replay; otherwise honest FAIL with responsibility attribution
(HOST_INPUT_GUARD vs ADAPTER vs HARNESS), and no further Front Matter
prompting/harness work afterwards.

## Preregistered expectation (stated only here + final report)

Expected: PASS_ADAPTED. The adapter-side risk that remains is honest:
Gate 7's cross-domain text=None omission is now host-owned (guard),
but flag semantics and error wrapping are still the agent's to get
right from the public truth table and runnable public tests.

## Command

`repoproof agent-run --contract contracts/adopt-frontmatter-local-ingest-v1-v2.yaml`
