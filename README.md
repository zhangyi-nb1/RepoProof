# RepoProof

**RepoProof is an evidence-driven harness for verifying whether an
agent-generated open-source capability adaptation actually satisfies a
frozen adoption contract.**

## The problem

Coding agents routinely REPORT success. "I integrated the library,
all done" is a claim, not evidence — and in our recorded runs, agents
produced adapters that were 94% correct (31/33 checks) yet still
unusable, invented their own BM25 scoring instead of calling the
pinned upstream, and trusted a contaminated prompt over source code
they had already read. Adopting an open-source capability into a host
project needs a verdict that does not come from the agent.

## How it works

```
Task Contract → Contract Adequacy → Single Coding Agent
     → Frozen Adaptation → Independent Verification
     → Clean Replay → Completion Gate
```

- **One autonomous agent loop.** The agent is
  [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent)'s
  `DefaultAgent` — exactly one, no critic/reflection/multi-agent.
  RepoProof itself is the application + harness + verification
  protocol around it.
- **The agent cannot read the oracle or held-out fixtures.** It sees
  the public contract, public examples, runnable public tests, and
  the consumer source — never the acceptance tests.
- **Agent claims never produce a PASS.** The completion gate consumes
  structured verifier results only (capability, host regression,
  policy, replay); `claim_complete` events are ignored by
  construction, pinned by tests.
- **PASS_ADAPTED exists only when** capability AND host regression
  AND policy AND a `clean_adoption` replay in a fresh container all
  pass.
- **Contract adequacy is checked before any agent starts.** A typed
  RequirementSpec (owner / severity / public text / examples / oracle
  bindings) plus a 13-check deterministic ContractAdequacyGate refuse
  inadequate specs as `INVALID_TASK_SPEC` with zero model calls —
  because our own Gate 7 proved that an underspecified contract
  produces failures that are the task author's fault, not the agent's.
- **Docker is used for isolation, disposal and replay** (non-root,
  cap-drop ALL, network=none at test time, digest-pinned images) —
  it is NOT presented as a security sandbox for malicious code
  (see [SECURITY.md](SECURITY.md)).

## Recorded cases (all numbers: [docs/benchmark_summary.json](docs/benchmark_summary.json))

### ✅ Positive: Front Matter corrected-spec case — PASS_ADAPTED

A real deepseek-v4-pro agent wrote a 1-file / 67-line adapter that
calls the pinned python-frontmatter, splits the record flags per the
public truth table, projects metadata JSON-safe (dates → ISO), and
wraps upstream parse errors — then submitted voluntarily at 16 of its 20
allowed model calls. Independent verification: capability **18/18** including
held-out inputs, host regression 3/3, policy clean, and a
`clean_adoption` replay in a fresh container. Responsibility is
explicit: deterministic input validation (text=None, missing fields,
bad ids) is done by the HOST's InputContractGuard — that part is not
agent capability, and the docs never count it as such.
Evidence: [docs/evidence/gate72-corrected-spec-run/](docs/evidence/gate72-corrected-spec-run/).

### ❌ Negative: Chonkie — 31/33 and still FAIL

An earlier agent adapted the Chonkie chunking library to 31/33
capability checks — regression passed, policy clean, a highly
complete artifact. The independent verifiers refused it anyway: it
never wrapped upstream errors on malformed input, the same failure
reproduced deterministically in a clean container, and the verdict
stayed **FAIL**. High completion is not adoption.
Evidence: [docs/evidence/gate3c-real-run/](docs/evidence/gate3c-real-run/).

### ❌ Negative: rank_bm25 — semantic substitution

The agent produced schema-perfect rankings (9/12) from its OWN BM25
arithmetic instead of the pinned upstream's — behavioral reference
testing caught score drift on public and held-out corpora alike.
Evidence: [docs/evidence/gate5-second-repo/](docs/evidence/gate5-second-repo/).

## No-model demo (reproducible without any provider)

```bash
.venv/bin/repoproof demo list
.venv/bin/repoproof demo verify --case frontmatter-v2-pass
.venv/bin/repoproof demo verify --case chonkie-agent-fail
.venv/bin/repoproof demo replay --case frontmatter-v2-pass   # fresh container, no LLM
```

`demo verify` recomputes the completion-gate decision from the
committed verifier evidence; `demo replay` re-runs the committed
PASS_ADAPTED adapter against the frozen oracle in a new container.
Neither calls a model. Walkthroughs: [docs/DEMO.md](docs/DEMO.md),
[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Boundaries (read before quoting numbers)

- Scope today: **public Python repos, Linux containers, CPU-first
  capability-adoption tasks** — three capability domains recorded
  (chunking, BM25 ranking, front-matter parsing), each requiring
  human task engineering (contract, oracle, controls).
- 12 recorded runs, **1 PASS_ADAPTED**, 11 honest FAILs. Nothing here
  guarantees adaptation success or claims to work with any repo.
- The Gate 7.2 positive case is a **corrected-spec** result — the
  task specification was repaired between attempts, so it is NOT a
  single-variable improvement claim.
- Budget-awareness ablation returned a null result; the Coverage
  Ledger is experimental and default-off. Neither supports a success
  claim — the negative results are kept.
- Traces are tamper-EVIDENT (hash-chained), not tamper-proof.
- Claim discipline is machine-checked:
  [docs/CLAIMS_MATRIX.md](docs/CLAIMS_MATRIX.md) +
  `scripts/check_public_claims.py`.

## Quickstart

```bash
# prerequisites: docker daemon (tested via colima on Apple Silicon), python 3.12
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                       # host tests (no docker/model needed)
.venv/bin/repoproof demo verify --case frontmatter-v2-pass
.venv/bin/repoproof task init --help   # scaffold a new DRAFT task
.venv/bin/repoproof task check --task-id <id>
```

## Layout

```
contracts/            frozen task contracts + RequirementSpecs (+ sha sidecars)
oracle/<task>/        held-out acceptance: capability + regression tests
fixtures/             consumer projects + negative-control adapters
src/repoproof/        domain / harness / agents / execution / verification / runner
docs/evidence/        committed, redaction-scanned run evidence bundles
docs/benchmark_summary.json   machine-readable fact source for all numbers
runs/                 (gitignored) live per-run trace, artifacts, verification
```

Docs: [ARCHITECTURE](docs/ARCHITECTURE.md) ·
[PROJECT_EVOLUTION](docs/PROJECT_EVOLUTION.md) ·
[BENCHMARK](docs/BENCHMARK.md) ·
[FAILURE_TAXONOMY](docs/FAILURE_TAXONOMY.md) ·
[CLAIMS_MATRIX](docs/CLAIMS_MATRIX.md) ·
[HANDOFF_STATE](docs/HANDOFF_STATE.md)

## Provenance

Evolved from the author's LocalFlow harness project; concepts
referenced read-only, all code re-implemented
([docs/lineage.md](docs/lineage.md)). License: Apache-2.0.
