# Lineage — LocalFlow → RepoProof

RepoProof evolved from the author's prior project **LocalFlow** (local
agent execution harness). Per the migration rules, LocalFlow was
consulted **read-only** at commit
`14603d5cddbf6b0fe5db2d5c098f5563b62eeade` and is not modified by this
project.

## Concepts referenced (design-level, no code copied)

| RepoProof module | Referenced LocalFlow idea | Relationship |
|---|---|---|
| `src/repoproof/harness/trace.py` | append-only `trace.jsonl` run trace | Re-implemented; RepoProof adds a per-line SHA-256 hash chain (tamper-evident), which LocalFlow's trace does not have |
| `src/repoproof/harness/policy.py` | single policy-checked dispatch path | Re-implemented; rules rewritten for upstream/oracle/adaptation trust zones |
| `src/repoproof/verification/*` | verifier registry + verify-as-gate | Re-implemented; four RepoProof-specific verifiers (capability / host regression / policy / clean-room replay) |
| `src/repoproof/harness/budget.py` | drift/step budget idea | Re-implemented as step + wall-time + per-command budgets |
| `src/repoproof/execution/docker_backend.py` | Docker workspace lifecycle experience | Re-implemented as task-level disposable containers (create → argv exec → destroy) |
| (Gate 3, planned) checkpoint / human request | stage-level checkpoint/resume | Not yet implemented in RepoProof |

## Code copied or adapted from LocalFlow

None. All RepoProof source files are new implementations.

If any future change copies or adapts LocalFlow source, it MUST be
recorded here with: LocalFlow source commit, original file, scope of
the copy/adaptation, license note, and why re-implementation was not
feasible.

## Explicitly retired (not migrated)

LocalFlow's react loop (plan-first stepwise loop), rule/LLM file
planners, skills/packs, multi-role agent_team layer, agent-server, the
generic LLM client, and file-level rollback. Route B (frozen at Gate
1): the single autonomous loop will be **mini-swe-agent** (Gate 3);
RepoProof keeps orchestration deterministic and puts control, budget,
verification and replay OUTSIDE the agent.
