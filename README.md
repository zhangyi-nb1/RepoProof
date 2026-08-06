# RepoProof

**Evidence-driven harness for verifiable open-source capability
adoption.** A coding agent will diagnose and minimally adapt a target
capability from a pinned public repo inside disposable containers —
and an **independent verification layer outside the agent** decides
whether the result actually works: capability tests, host regression,
policy checks, and a clean-room replay. `PASS` is earned from
executable evidence, never from an agent's self-claim.

> Status: **Gate 3B.** v3 reference-calibrated task package with
> positive/negative oracle controls; mini-swe-agent 2.4.6 wired as the
> single autonomous loop and verified end-to-end with a deterministic
> fake model (no LLM). The first REAL model run is currently BLOCKED on
> provider availability (docs/evidence/gate3-preflight/) — honest
> BLOCKED is a correct outcome here; no silent model switching.

## What exists today (Gate 2 → 2.5)

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

### Measured baseline v2 (evidence: `docs/evidence/gate25-baseline-v2/`)

Gate 2.5 hardened run — v2 task package (root hash committed as
`contracts/adopt-chonkie-local-chunking-v2.package.json`), offline
installs from a content-addressed wheelhouse, digest-pinned image,
non-root cap-drop-ALL containers, per-action policy causality:

| Check | Result |
|---|---|
| Direct-adoption verdict (completion gate) | **FAIL** — honest: naive integration is not enough; no adapter was attempted |
| Capability | `passed_checks=4, failed_checks=42, total_checks=46` across public **and held-out** fixtures × both frozen strategies (sentence, recursive): no strategy/chunk_size honoring, unstable upstream ids, missing attribution/ordinals/metadata, offsets not sliceable, errors unwrapped |
| Host regression | `passed_checks=4, failed_checks=0, total_checks=4` |
| Policy | oracle/upstream intact; per-action-id causality holds; patch budgets enforced (0 adaptation files) |
| Clean-room replay | `mode=baseline_failure_reproduction, status=PASS` — reproduction of a failing baseline can NEVER ground a final PASS (gate-pinned) |
| Trace | 77 events, tamper-evident hash chain verified AFTER `run.end`; final sha256 recorded in `run_manifest.json` |
| verify-bundle | 7/7 integrity checks pass (contract / task package / trace / final sha / artifacts / verification refs / adaptation) |
| Negative control | a cheating one-record-per-doc adapter is REJECTED by the v2 oracle (pinned test) |

The v1 baseline (`docs/evidence/gate2-baseline/`) is preserved as
history. The 42-item failed-check list is the future agent's job
description — the solution is deliberately NOT pre-written anywhere in
this repo.

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
