"""No-model evidence demos (Gate 8C).

Three subcommands, ZERO LLM calls, zero provider dependency:

- ``demo list``    — the case registry
- ``demo verify``  — recompute the completion-gate decision from a
  COMMITTED evidence bundle and check it matches the recorded verdict
  (proves verdicts derive from verifier data, not narrative)
- ``demo replay``  — re-run the committed PASS_ADAPTED adapter against
  the frozen oracle in a FRESH container (proves the artifact, not the
  agent session, carries the capability)

Rules: read-only over docs/evidence/ (redacted public copies; their
original trace-chain shas are recorded in each run manifest); never
fabricates runs; never touches history.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

CASES: dict[str, dict] = {
    "frontmatter-v2-pass": {
        "kind": "positive",
        "evidence": "docs/evidence/gate72-corrected-spec-run",
        "report": "report.json",
        "headline": "corrected-spec real-agent run — capability 18/18 incl. held-out → PASS_ADAPTED",
        "task": "adopt-frontmatter-local-ingest-v1-v2",
        "adapter": "agent_adapter.py",
        "oracle": "oracle/adopt-frontmatter-local-ingest-v1-v2",
        "consumer": "fixtures/consumer_rag_ingest_v2",
        "upstream": "upstream-cache/upstream-dc7c0af5466b",
        "wheelhouse": "upstream-cache/wheelhouse-dc7c0af5466b",
        "expected_capability": (18, 18),
    },
    "chonkie-agent-fail": {
        "kind": "negative",
        "evidence": "docs/evidence/gate3c-real-run",
        "report": "report.json",
        "headline": "highly complete agent artifact (31/33) rejected — honest FAIL, reproduced in clean room",
        "task": "adopt-chonkie-local-chunking-v3",
    },
    "bm25-agent-fail": {
        "kind": "negative",
        "evidence": "docs/evidence/gate5-second-repo",
        "report": "report.json",
        "headline": "schema-perfect but semantically substituted BM25 (9/12) rejected by behavioral reference",
        "task": "adopt-rank-bm25-local-search-v1",
    },
}

_COUNTS = re.compile(r"passed_checks=(\d+).*?total_checks=(\d+)")


def _counts(text: str | None) -> tuple[int, int] | None:
    m = _COUNTS.search(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def demo_list() -> dict:
    return {
        "cases": [
            {"case": name, "kind": c["kind"], "task": c["task"], "headline": c["headline"]}
            for name, c in CASES.items()
        ],
        "model_calls": 0,
    }


def demo_verify(project_root: Path, case: str) -> dict:
    """Recompute the gate decision table over the committed evidence."""
    spec = CASES[case]
    ev = project_root / spec["evidence"]
    rep = json.loads((ev / spec["report"]).read_text(encoding="utf-8"))

    cap = _counts(rep.get("capability"))
    reg = _counts(rep.get("regression"))
    replay_text = rep.get("replay") or ""
    m_mode = re.search(r"mode=(\w+)", replay_text)
    replay_mode = m_mode.group(1) if m_mode else None
    replay_pass = "status=PASS" in replay_text
    policy_ok = bool(rep.get("policy"))
    budget_exhausted = bool(rep.get("budget_exhausted"))
    missing_external = bool(rep.get("missing_external"))

    # completion-gate decision table, recomputed from evidence fields
    if missing_external:
        recomputed = "BLOCKED"
    elif (
        cap and cap[0] == cap[1]
        and reg and reg[0] == reg[1]
        and policy_ok
        and not budget_exhausted
        and replay_mode == "clean_adoption"
        and replay_pass
    ):
        recomputed = "PASS_ADAPTED"
    else:
        recomputed = "FAIL"

    recorded = rep.get("final_verdict") or rep.get("verdict")
    return {
        "case": case,
        "kind": spec["kind"],
        "task_id": rep.get("task_id"),
        "run_id": rep.get("run_id"),
        "inputs_to_gate": {
            "capability": f"{cap[0]}/{cap[1]}" if cap else None,
            "capability_failed_tests": rep.get("capability_failed_tests"),
            "host_regression": f"{reg[0]}/{reg[1]}" if reg else None,
            "policy": "PASS" if policy_ok else None,
            "replay_mode": replay_mode,
            "replay": "PASS" if replay_pass else "FAIL/none",
            "budget_exhausted": budget_exhausted,
        },
        "task_package_root": rep.get("task_package_root_hash"),
        "adaptation_root": rep.get("adaptation_root"),
        "trace_sha256": rep.get("final_trace_sha256"),
        "trace_chain_ok_at_run_time": rep.get("trace_chain_ok"),
        "verifier_result_hashes": rep.get("verification_result_hashes"),
        "recorded_verdict": recorded,
        "recomputed_verdict": recomputed,
        "verdict_recomputation_matches": recomputed == recorded,
        "agent_claim_consulted": False,
        "model_calls": 0,
        "evidence_path": spec["evidence"],
    }


def demo_replay(project_root: Path, case: str) -> dict:
    """Fresh-container re-run of the committed adapter (positive cases)."""
    spec = CASES[case]
    if spec["kind"] != "positive":
        return {"error": f"case {case} is a negative case; replay demo is for the positive artifact"}
    from repoproof.runner.calibration import run_oracle_with_adapter

    ev = project_root / spec["evidence"]
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(dir=project_root / "runs") as td:
        adapter_dir = Path(td)
        shutil.copy2(ev / spec["adapter"], adapter_dir / "adapter.py")
        result = run_oracle_with_adapter(
            project_root=project_root,
            upstream=project_root / spec["upstream"],
            wheelhouse=project_root / spec["wheelhouse"],
            oracle_dir=project_root / spec["oracle"],
            adapter_dir=adapter_dir,
            consumer_dir=project_root / spec["consumer"],
            user=f"{os.getuid()}:{os.getgid()}",
        )
    totals = result.get("totals") or {}
    expected = spec["expected_capability"]
    ok = (
        result.get("exit_code") == 0
        and totals.get("tests") == expected[1]
        and totals.get("failures") == 0
        and totals.get("errors") == 0
    )
    return {
        "case": case,
        "replayed_artifact": f"{spec['evidence']}/{spec['adapter']}",
        "container": "fresh (created and destroyed for this demo)",
        "capability": (
            f"{totals.get('tests', 0) - totals.get('failures', 0) - totals.get('errors', 0)}"
            f"/{totals.get('tests')}"
        ),
        "expected": f"{expected[0]}/{expected[1]}",
        "replay_ok": ok,
        "model_calls": 0,
    }
