# No-model demo walkthrough

> **定位说明(2026-08-26)**:本页的三个 case 是 **Benchmark Lab** 时代的
> 证据复算演示。它们没有过期——命令照常可跑、结论照常可复算——但它们
> 展示的是"判定协议"这一面,不是当前产品主线。
>
> 想看 **Product Mode**(GitHub 能力 → 本地工具)的零模型全链演示,用:
>
> ```bash
> .venv/bin/python scripts/demo_direct_wrap.py
> ```
>
> 那条演示自包含、零网络、零真实模型、零主仓污染(产物全在
> `/tmp/rp_direct_demo/`),走完 intake 静态分析 → CapabilityPlanV1
> (SUPPORTED + DIRECT_WRAP,带 file:line 证据)→ 人工确认三项 →
> 受信模板装配 → 同一条独立验证链 → `PASS_DIRECT`。
> 产品链路总览见 [PROJECT_MAP.md](PROJECT_MAP.md)。

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
