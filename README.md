# RepoProof

**Evidence-driven harness for verifiable open-source capability
adoption.** A coding agent will diagnose and minimally adapt a target
capability from a pinned public repo inside disposable containers —
and an **independent verification layer outside the agent** decides
whether the result actually works: capability tests, host regression,
policy checks, and a clean-room replay. `PASS` is earned from
executable evidence, never from an agent's self-claim.

> Status: **Gate 2 vertical slice.** The deterministic evidence chain
> is real and runnable today; the autonomous agent is deliberately not
> wired yet (Gate 3).

## What exists today (Gate 2)

- **Frozen Task Contract** (`contracts/*.yaml` + `.sha256` sidecar) —
  goal, environment, forbidden actions, budgets, acceptance commands.
  The runner refuses tampered contracts.
- **Trust zones** — pinned read-only `upstream` snapshot (git commit
  verified), read-only hash-guarded `oracle` (capability + regression
  tests), persistent `adaptation` products zone, and an **ephemeral
  in-container execution copy** destroyed with the container.
- **Docker execution backend** — create → argv exec (with
  in-container timeouts) → destroy; CPU/memory/PID limits;
  `network=none` at verification time (probed from inside).
- **Append-only, tamper-evident trace** — every action, policy
  decision, exit code, artifact and verdict in one JSONL stream with a
  per-line SHA-256 hash chain (`repoproof verify-trace`).
- **Content-addressed artifacts** — stdout/stderr, pip logs, probe
  dumps and manifests stored by SHA-256 and referenced from events.
- **Four independent verifiers + completion gate** —
  Capability / HostRegression / Policy / Replay; the gate consumes
  structured results only and **ignores `claim_complete` events by
  construction** (pinned by tests). No clean-room replay → no final
  PASS.
- **First real task admitted** — `adopt-chonkie-local-chunking-v1`:
  adopt [Chonkie](https://github.com/feyninc/chonkie) (pinned MIT
  commit `0a6baea`, CPU-only, offline, base install only) into a small
  RAG consumer fixture. The committed **direct-adoption baseline** run
  records the real gap between upstream output and the host
  `ChunkRecord` contract as a granular failed-test list.

### Measured baseline (evidence: `docs/evidence/gate2-baseline/`)

Real run on linux/arm64 containers (aarch64 verified in-container;
`chonkie-1.7.0 + chonkie-core-0.10.2 + tokie-0.1.4 + numpy-2.5.1` all
installed cleanly on arm64):

| Check | Result |
|---|---|
| Direct-adoption verdict (completion gate) | **FAIL** — honest: naive integration is not enough; no adapter was attempted |
| Capability checks | **8 of 11 failed**: upstream ids are per-call unstable (`chnk_<hex>`), records lack `document_id`/`ordinal`/`metadata`, schema differs from `ChunkRecord`, offsets don't slice back, upstream errors unwrapped; 3 passed (JSON-serializable, input not mutated, blank doc → 0 records) |
| Host regression | 4/4 passed (adoption path broke nothing) |
| Clean-room replay | **consistent** — fresh containers + fresh venv + fresh execution tree reproduced the identical failed-test set and normalized probe hash |
| Trace | 78 events, tamper-evident hash chain verifies |
| Budget | 11 scripted steps per pass (limit 20), ~105 s wall |

This failed-test list is the future agent's job description — the
solution is deliberately NOT pre-written anywhere in this repo.

## What does NOT exist yet (honest non-goals of this slice)

- No agent and no LLM calls (mini-swe-agent lands at Gate 3 as the
  single autonomous loop).
- No final Chonkie adapter — writing it is the future agent's job;
  shipping it now would poison the benchmark.
- No typed-failure recovery, no repeated-action guard, no
  HumanRequest state machine (these must be justified by real failure
  traces first).
- No MySQL, no FastAPI, no web UI.
- Docker here means **isolation, disposal and replay** for
  human-admitted public repos — **not** a hardened sandbox for
  malicious code (see SECURITY.md).

## Quickstart

```bash
# prerequisites: docker daemon (tested via colima on Apple Silicon), python 3.12
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                       # host unit tests (no docker needed)
./reproduce.sh                         # full evidence chain incl. baseline + replay
.venv/bin/repoproof verify-trace --run-dir runs/<run_id>
```

## Layout

```
contracts/            frozen task contracts (+ sha256 sidecars)
oracle/<task>/        read-only acceptance: capability + regression tests
fixtures/consumer_rag host consumer fixture (the project adopting the capability)
src/repoproof/        domain / harness / execution / verification / persistence / runner
runs/                 (gitignored) per-run trace, artifacts, verification, report
upstream-cache/       (gitignored) pinned upstream snapshots
docs/lineage.md       LocalFlow → RepoProof provenance rules
```

## Provenance

Evolved from the author's LocalFlow harness project; concepts
referenced read-only, all code re-implemented (docs/lineage.md).
License: Apache-2.0.
