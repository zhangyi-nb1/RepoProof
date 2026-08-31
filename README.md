# RepoProof

[![CI](https://github.com/zhangyi-nb1/RepoProof/actions/workflows/ci.yml/badge.svg)](https://github.com/zhangyi-nb1/RepoProof/actions/workflows/ci.yml)

**RepoProof turns one capability from a pinned public GitHub repository into a
CLI-first local file tool or offline workspace, then independently verifies the
result before reporting `VERIFIED_TOOL_READY`.**

New here? Start with the one-page map: [docs/PROJECT_MAP.md](docs/PROJECT_MAP.md)
(code zones, milestone/gate numbering across generations, and the verdict
vocabulary — 10 minutes).

The product is designed for a common gap: finding useful open-source code is
easy, while turning one of its capabilities into a dependable local command
still requires repository analysis, environment setup, wrapper code, testing,
and careful acceptance. RepoProof manages that workflow and keeps the final
verdict outside the coding agent.

## Product workflow

```text
GitHub repository + an initially vague work need
              ↓
static evidence + 2–3 LLM requirement suggestions
              ↓
human adopts or lightly edits one plain-language description
              ↓
four-state admission
              ↓
CapabilityPlanV1 (RFC-013): surface evidence, support status, and a
deterministic route — DIRECT_WRAP or AGENT_ADAPT. The analyzer detects
surfaces only; whether the located callable matches the user's intent is
confirmed by the user, and only a confirmed SUPPORTED plan may execute.
              ↓
LLM-assisted DRAFT (never a frozen contract)
              ↓
human review of semantics and golden examples
              ↓
frozen Tool Contract
              ↓
DIRECT_WRAP: trusted-template assembly, zero agent actions, must pass
with a zero diff — or AGENT_ADAPT: one bounded coding-agent repair loop
(failed rounds roll back; every failure maps to FailureAssessmentV1)
              ↓
independent capability / interface / policy verification
              ↓
clean replay from the delivered dependency lock
              ↓
historical VERIFIED_TOOL_READY + exported tool
              ↓
REVIEW_REQUIRED → fresh non-example audit
              ↓
ACTIVE RepoProof-managed MCP / upgrade release (or append-only REVOKED)
```

The LLM suggestion step is a writing aid, not an acceptance authority. Adopting
a suggestion only refills the editable requirement field; it does not create a
journey, freeze a contract, generate expected output, or mark a tool verified.
User-facing artifacts are not limited to JSON. The supported `cli_v2` profile
delivers one deterministic UTF-8 file, including RIS, TSV, Markdown and
self-contained XHTML/HTML. M6.2 adds an **experimental**
`workspace_bundle_v1` profile: one local file or directory becomes one new,
atomic, offline multi-file workspace. Its structure, formats, task semantics,
runnable smoke behavior and directory tree hash are independently checked;
binary files may exist only as contract-declared workspace members with
format/magic validation. This profile is not yet qualified as `SUPPORTED`.

Workspace tools use `bin/<tool> <input> --out-dir <new-directory>`. They reject
existing output directories, links, special files, path escape and resource
limit violations. MCP deliberately returns
`WORKSPACE_BUNDLE_MCP_NOT_SUPPORTED`; Studio's deterministic ZIP is a transport
copy, never the trusted verdict object.

The coding agent receives only the public contract, public examples, and
runnable public tests. Held-out examples and the acceptance oracle are never
placed in its prompt or disposable workspace. The Product Mode Codex connector
also installs a RepoProof `PreToolUse` hook that rejects explicit reads outside
that session and records denials. This command detector is intentionally
described as defense in depth, not a hostile-code security boundary; Codex
Product runs are therefore never counted as Benchmark Lab measurements. The
agent's own completion claim never produces a passing verdict.

## Quickstart

Prerequisites: Python 3.12 and Git. Real Product Mode builds default to
mini-swe using the configured OpenAI-compatible API gateway. Studio repository
summaries, online contract drafting and example input suggestions default to
the same gateway through LiteLLM. The official Codex CLI authenticated with a
ChatGPT subscription (`codex login`) remains an explicit fallback: select
`--agent-backend codex-cli`, set `REPOPROOF_DRAFTER_BACKEND=codex-cli`, or use
`scripts/run_ui_codex.sh`. Docker is still used by the
Benchmark Lab and selected replay paths; it is an isolation and reproducibility
mechanism, not a boundary for running hostile code.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 1. Analyze a public repository and create an editable proposal.
.venv/bin/repoproof tool add \
  --repo https://github.com/owner/project \
  --capability "describe the one capability you want" \
  --draft-out ./tool-draft

# 2. Review draft.yaml, reference_impl.py, and the golden examples.

# 3. Freeze, rehearse, run the agent once, verify, replay, export, and register.
#    A successful export is historical VERIFIED_TOOL_READY but operationally
#    REVIEW_REQUIRED until the next step.
.venv/bin/repoproof tool build --draft-dir ./tool-draft

# Optional ChatGPT-subscription fallback instead of the Product default:
# .venv/bin/repoproof tool build --draft-dir ./tool-draft \
#   --agent-backend codex-cli

# 4. Audit with a fresh non-example input and independently prepared truth.
.venv/bin/repoproof tool audit <tool-name> \
  --input /path/to/fresh-input \
  --expected-file /path/to/fresh-expected

# 5. Inspect both states; MCP exposure is allowed only while ACTIVE.
.venv/bin/repoproof tool list
.venv/bin/repoproof tool mcp <tool-name>
```

`tool add` may return `READY`, `NEED_INFORMATION`, `RISK_REVIEW`, or
`UNSUPPORTED`. Refusing a task outside the supported boundary is an intended
product outcome. `tool build` uses a fake rehearsal as a pre-budget gate; a
failed rehearsal does not start the real coding-agent run.

`tool list` deliberately reports two facts: `historical_verdict` is the
immutable result under the frozen task, while `operational_status` is the
current append-only release decision (`REVIEW_REQUIRED`, `ACTIVE`, or
`REVOKED`). A damaged decision ledger fails closed. `tool withdraw` keeps the
package and evidence but prevents new MCP generation; M5-generated adapters
also recheck the ledger on every list/call. A pre-M5 adapter is not rewritten
destructively, so `tool list` marks it `LEGACY_SERVER_MUST_BE_DETACHED` when
the tool is not ACTIVE.

This operational state is an application-level RepoProof control, not an
operating-system execution policy. The original `bin/<tool-name>` remains on
disk and a user who invokes it directly can still run it; `REVOKED` and
`REVIEW_REQUIRED` are enforced only in RepoProof-managed audit, MCP
generation/runtime, and upgrade/release paths. Managed upgrades also validate
the ledger fail closed and force every new task version back to
`REVIEW_REQUIRED` before package switching. Pre-M5 MCP clients must be detached
by the operator when flagged.

Managed package consumers bind one identity across the canonical directory,
`tool.json`, and required `evidence/provenance.json`: directory name =
`manifest.name` = `provenance.tool`, `task_id` must be exactly
`tool-<name>-vN`, and manifest/provenance run and contract hashes must match.
Package installation/upgrade, registry mutation, MCP generation, and managed
audit/withdraw paths serialize on the shared install lock; compound release
operations acquire the release lock only after it. The default read-only
`tool list` does not take that lock and fails closed on an observed intermediate
state. A generated MCP adapter holds both locks from its ACTIVE check through
tool execution and result publication, so withdrawal or replacement cannot
race between those steps.

Rebuilding the same command as a strictly newer task version uses a guarded
upgrade path. RepoProof checks lineage and version before any real model call,
stages the candidate on the destination filesystem, appends its
`REVIEW_REQUIRED` decision before switching packages, moves the unchanged old
package under `.repoproof-versions/`, and atomically records it in
`previous_versions`. Same-task replacement, downgrade, lineage mismatch,
missing or drifting registry identity, or an attached legacy MCP server is
rejected. The registry atomic replace is the commit point: a catchable failure
before it restores the old package, while an interruption observed after it
keeps the consistent new package and registry. The append-only new
`REVIEW_REQUIRED` decision is never erased, so recovery remains fail closed.
`SIGKILL` or power loss can interrupt between filesystem renames and requires
an operator to inspect package, archive, staging, and registry state.

Managed package trees reject symlinks and special files. The sole compatibility
exception is the existing top-level `.venv`, treated as a reproducible
environment; `adaptation.patch` may neither create nor modify it. Control files,
locks, archives, generated MCP files, and MCP `--out` publication use
containment/no-follow checks. `--out` is produced at a fresh temporary path by
that invocation, contract-validated, then atomically published; stale or linked
output files are not reused.

## What is independently checked

- The task contract is frozen before implementation and must pass deterministic
  adequacy checks.
- Capability behavior is tested against user-confirmed public and held-out
  examples.
- Tool Contract v2 carries a machine-executable output contract. T6–T9 reject
  missing or contradictory structured-output truth before a real model call,
  and public, held-out, audit, and MCP paths parse actual stdout independently
  of the golden text. These output-contract JSON paths are strict: the
  non-standard numeric tokens `NaN`, `Infinity`, and `-Infinity`, plus numeric
  overflow such as `1e400` or `-1e400`, are rejected.
- Runtime import receipts and provenance checks verify that the delivered tool
  actually uses the pinned upstream capability.
- CLI behavior checks cover help, exit-code semantics, deterministic output,
  malformed input where applicable, and stdout/stderr discipline.
- Policy checks protect frozen surfaces, budgets, and forbidden runtime actions.
- Clean replay rebuilds from the delivered lock file and reruns verification in
  a fresh environment.
- Failure still produces evidence; missing measurements are not treated as
  success.

Internally the stable completion gate still uses `PASS_ADAPTED` /
`PASS_DIRECT`; Product Mode renders either successful local-tool outcome as
`VERIFIED_TOOL_READY`.

## Current evidence and honest limits

RFC-010 milestones M0 through M4 and RFC-011 M5 are complete. The first two dogfood tools
(`pdf-table` and `html2md`) exercised the full product path, followed by two
preregistered real-repository batches.

The latest batch-two fact source records:

| Measure | Recorded result |
|---|---:|
| Submitted repositories | 12 |
| Accepted for execution | 11 |
| Historical pipeline READY results | 10 |
| Successful clean-replay checks | 10 |
| ACTIVE for RepoProof-managed exposure after fresh-input audit | 9 |
| False-success findings | 1 |

**Host-integrity qualifier — read this with every number above.** Main-repo
integrity reconciliation used to run *after* the completion gate and was only
written to `report.json`, so it never entered the verdict (fixed 2026-08-25,
`apply_integrity_to_verdict`). Counting the backlog afterwards found 19 PRODUCT
runs recorded as PASS while `main_dir_integrity` was `MISMATCH`; 10 of them are
bound to exported tools and 8 of those are currently ACTIVE. 用这些数字时必须同
时说明:其中 8 个工具的**交付发次在现行完整性闸下应判 BLOCKED**(当时完整性不
参与判定,且未记归因)。历史 verdict 一字不改;每一发都有 append-only 勘误行
(`benchmarks/v2/run_classifications.jsonl`),`scripts/check_public_claims.py`
把这句限定机器钉死。

**Re-sampled on 2026-08-26 (INTEGRITY-RESAMPLE-1).** All eight frozen tasks were
re-run under the current gate in a verified quiet window: **8/8 PASS_ADAPTED with
`main_dir_integrity=ok`**, 472,949 input tokens. That proves the frozen task plus
the pinned upstream *does* pass cleanly today; it does **not** retroactively make
the original delivery run clean, and it deliberately did not replace any tool
package, registry entry, or release decision. Every ACTIVE tool flagged above now
has a clean re-sample; the two export-bound runs still without one belong to
`jsonschema-report` (REVIEW_REQUIRED) and `pyspellchecker` (REVOKED) — neither is
ACTIVE. See [product_summary.json](docs/product_summary.json)
(`ledger.clean_resample_by_task`).

What none of this touches: the tools' functional evidence. Clean replay and the
fresh non-example audit are independent lines that never depended on the original
run's host integrity, and both passed.

The flagged `pyspellchecker` v1 result is deliberately preserved as historical
evidence: its frozen statement declared JSON while its examples and oracle
accepted plaintext. Its RepoProof-managed release status was withdrawn without
rewriting the frozen contract or rerunning the model. The M4 operator audits
were migrated by source hash into the local append-only release ledger: 21
tools are ACTIVE, `pyspellchecker-tool` is REVOKED, and the two earlier dogfood
tools remain REVIEW_REQUIRED because no fresh audit was fabricated for them. See
[m4_metrics.json](docs/m4_metrics.json) and the append-only
[exploration log](docs/EXPLORATION_LOG.md).

These are recorded case results, not a claim about arbitrary repositories.
Product Mode currently targets public Python repositories, one clear
capability, local CPU execution, simple-to-medium dependencies, and explicit
file-oriented input/output. GPU-heavy, distributed, account-bound, private,
or whole-application integration tasks remain outside the v1 promise.

## Product Mode and Benchmark Lab

RepoProof keeps two concerns in one repository but off each other's critical
paths:

- **Product Mode** optimizes the GitHub capability → local tool journey and
  records each run with `test_mode=PRODUCT`.
- **Benchmark Lab** retains preregistration, blind/held-out research tasks,
  mutation checks, model comparisons, and historical `PASS_ADAPTED` / honest
  failure evidence. Product runs do not inflate benchmark model scores.

The default Product Mode backend is mini-swe using the configured API provider.
The official Codex CLI remains a first-class fallback using the local ChatGPT
subscription login. RepoProof can reuse Codex's native agent loop while retaining
its own contract, bounded repair controller, independent verification, clean
replay, evidence, and release governance. Internal Codex model-call counts are
not exposed, so RepoProof records logical `codex exec` invocations and reported
token usage without fabricating a call count or dollar cost. Codex Product runs
are ineligible for Benchmark Lab scoring. The DSH
integration remains part of the frozen Benchmark Lab research line and is not a
Studio Product Mode choice. See
[ADR: Codex CLI Product backend](docs/adr/ADR-CODEX-CLI-PRODUCT-BACKEND.md).

Studio's three assistant-only actions—repository summary, Tool Contract draft,
and candidate example inputs—default to the LiteLLM/API gateway. The Codex
subscription fallback runs with every tool denied and an enforced output schema.
Either route produces untrusted draft material: candidate expected outputs still
come from executing the pinned upstream, and a human must confirm every golden
example.

## Repository layout

```text
src/repoproof/adoption/       intake, analysis, drafting, confirmation, assembly
src/repoproof/runner/         product pipeline, export, registry, MCP adapter
src/repoproof/verification/   independent verifiers and completion gate
contracts/                    frozen contracts and requirement specs
tool_tasks/                   materialized local-tool tasks and archived drafts
oracle/                       held-out acceptance tests (never delivered)
controls/                     positive and synthetic-negative verifier controls
docs/evidence/                committed, redaction-scanned evidence bundles
benchmarks/                   Benchmark Lab preregistrations and append-only ledgers
runs/                         live run artifacts (gitignored)
```

Key documents:

- [Product redirection](docs/PRODUCT_REDIRECTION.md)
- [Local Tool Product Charter](docs/rfc/RFC-010-LOCAL-TOOL-PRODUCT-CHARTER.md)
- [Implemented M5: contract coherence and release state](docs/rfc/RFC-011-TOOL-CONTRACT-COHERENCE-AND-RELEASE-STATE.md)
- [Tool Contract schema](docs/TOOL_CONTRACT_SCHEMA.md)
- [Tool package layout](docs/TOOL_PACKAGE_LAYOUT.md)
- [`VERIFIED_TOOL_READY` decision mapping](docs/TOOL_READY_GATE.md)
- [Natural-requirement, multi-format qualification runbook](docs/M6_1_NATURAL_REQUIREMENTS_MULTIFORMAT_RUNBOOK.md)
- [Authoritative handoff state](docs/HANDOFF_STATE.md)
- [Security boundaries](SECURITY.md)

RepoProof is Apache-2.0 licensed. It evolved from the author's LocalFlow harness
concepts; the lineage is documented in [docs/lineage.md](docs/lineage.md).
