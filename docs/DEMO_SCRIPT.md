# Demo scripts (30s / 2min / 5min) — no live model, ever

> **定位说明(2026-08-26)**:下面三段话术属于 **Benchmark Lab** 口径
> (判定协议 / 31 之 33 / 首个 PASS_ADAPTED),依然真实可演,但已不是
> 产品主线的开场白。**Product Mode 的当前口径**见
> [INTERVIEW_GUIDE.md](INTERVIEW_GUIDE.md) 的 30 秒 / 90 秒版本 ——
> 那里的数字绑 [product_summary.json](product_summary.json),并且带着
> 强制的完整性限定句。演示实体用 `scripts/demo_direct_wrap.py`。

## 30-second version

> "Coding agents say 'done'. RepoProof decides whether that's true.
> Here's a real agent adapter that scored 31 out of 33 acceptance
> checks — and RepoProof still failed it, because it broke on
> malformed input and the failure reproduced in a clean container.
> [run `demo verify --case chonkie-agent-fail`]
> And here's the case that actually earned a pass: independent
> capability, regression, policy AND a clean-room replay — the
> verdict is computed from verifier evidence; the agent's own claim
> is never consulted.
> [run `demo verify --case frontmatter-v2-pass`]"

## 2-minute version (recommended order)

1. **Show the task contract** — `contracts/adopt-frontmatter-local-ingest-v1-v2.yaml`:
   frozen statement, budgets, sha sidecar; point at the RequirementSpec
   (owner / severity / public text / oracle bindings).
2. **Show the isolation** — agent mounts (upstream ro, consumer ro,
   adaptation rw) in `docs/ARCHITECTURE.md`; oracle and held-out
   fixtures never enter the agent container.
3. **Verify the negative bundle** — `demo verify --case chonkie-agent-fail`.
4. **Say why 31/33 still fails** — the two missed checks are the
   upstream-error contract; the completion gate has no partial
   credit, and the failure reproduced deterministically in a fresh
   container. High completion ≠ adoption.
5. **Verify the positive bundle** — `demo verify --case frontmatter-v2-pass`.
6. **Show the clean replay** — `demo replay --case frontmatter-v2-pass`:
   the committed 67-line adapter re-earns 18/18 in a brand-new
   container, zero model calls.
7. **Show the verdict** — PASS_ADAPTED came from
   C ∧ R ∧ P ∧ clean_adoption; point at the recomputation line.
8. **Close** — "the agent's self-report is not an input to any of
   this. That's the point."

## 5-minute technical version

Add to the 2-minute flow:

- **Contract adequacy** (after step 1): show
  `repoproof adequacy-check --contract …` output — 13 deterministic
  checks; explain Gate 7's lesson (a rule that lived only in YAML
  comments produced a defensible-but-wrong agent reading —
  task-author fault, typed as CONTRACT_UNDERSPECIFICATION, fixed by
  RequirementSpec + truth table + this gate).
- **Responsibility split** (after step 5): open the consumer's
  `guard.py` — deterministic input validation is HOST code with a
  stable error code; the agent never re-implements it and gets no
  credit for it.
- **Negative controls** (anywhere): the frozen TaskPackage carries a
  controls summary — a flag-conflation cheat, a regex splitter, a
  bad-conversion adapter and a raw-exception adapter all
  FAILED_AS_EXPECTED before any agent ran.
- **Honest limits** (close): 12 recorded runs, 1 PASS_ADAPTED; the
  positive case is corrected-spec, NOT a single-variable improvement;
  budget-awareness ablation was null; ledger is experimental-off.

Rule for all versions: never call a live model during a demo.
