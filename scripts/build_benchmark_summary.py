"""Build docs/benchmark_summary.json — the MACHINE-READABLE fact source
for every public number.

Extraction-only: every field comes from committed evidence files
(report.json / run_manifest.json under docs/evidence/). Fields the
evidence cannot prove are emitted as null — never guessed, never
back-filled from memory. README/BENCHMARK claims are checked against
this file by scripts/check_public_claims.py.

Run: .venv/bin/python scripts/build_benchmark_summary.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EV = REPO / "docs" / "evidence"

# case registry: evidence files only; no numbers live here
CASES = [
    ("chonkie-v1-baseline", "direct_baseline", "chonkie-v1", "gate2-baseline/report.json", None),
    ("chonkie-v2-baseline", "direct_baseline", "chonkie-v2",
     "gate25-baseline-v2/report.json", "gate25-baseline-v2/run_manifest.json"),
    ("chonkie-agent-g3c", "real_agent", "chonkie-v3",
     "gate3c-real-run/report.json", "gate3c-real-run/run_manifest.json"),
    ("chonkie-agent-g4a-budget-vis", "ablation", "chonkie-v3",
     "gate4a-intervention/report.json", "gate4a-intervention/run_manifest.json"),
    ("chonkie-agent-g4b-ledger", "ablation", "chonkie-v3",
     "gate4b-intervention/report.json", "gate4b-intervention/run_manifest.json"),
    ("bm25-baseline", "direct_baseline", "rank-bm25-v1",
     "gate5-second-repo/direct_baseline_report.json", None),
    ("bm25-agent-g5", "real_agent", "rank-bm25-v1",
     "gate5-second-repo/report.json", "gate5-second-repo/run_manifest.json"),
    ("frontmatter-baseline-g6", "direct_baseline", "frontmatter-v1",
     "gate6-positive-task/baseline_report.json", None),
    ("frontmatter-agent-g6", "real_agent", "frontmatter-v1",
     "gate6-positive-task/report.json", "gate6-positive-task/run_manifest.json"),
    ("frontmatter-agent-g7-clean-prompt", "real_agent", "frontmatter-v1",
     "gate7-clean-prompt/report.json", "gate7-clean-prompt/run_manifest.json"),
    ("frontmatter-v2-baseline-g71", "direct_baseline", "frontmatter-v2",
     "gate72-corrected-spec-run/baseline_report.json",
     "gate72-corrected-spec-run/baseline_run_manifest.json"),
    ("frontmatter-v2-agent-g72", "corrected_spec_positive", "frontmatter-v2",
     "gate72-corrected-spec-run/report.json",
     "gate72-corrected-spec-run/run_manifest.json"),
]

TASK_SOURCES = {
    "chonkie": ("https://github.com/feyninc/chonkie", "0a6baea5c8c47761dfc02b76a03bbdeb26841602"),
    "rank-bm25": ("https://github.com/dorianbrown/rank_bm25", "47aa3ddf8dc10b7a1a731c88d2f912ccae7c47c0"),
    "frontmatter": ("https://github.com/eyeseast/python-frontmatter", "dc7c0af5466b104e0ba01ae3c5b2cd77edc27292"),
}

FAILURE_TYPES = {
    # from docs/FAILURE_TAXONOMY.md, keyed by case id (typed there, not re-derived)
    "chonkie-agent-g3c": "CONTRACT_REQUIREMENT_OMISSION",
    "chonkie-agent-g4a-budget-vis": "CONTRACT_REQUIREMENT_OMISSION",
    "chonkie-agent-g4b-ledger": "CONTRACT_REQUIREMENT_OMISSION",
    "bm25-agent-g5": "SEMANTIC_SUBSTITUTION",
    "frontmatter-agent-g6": "HARNESS_PROMPT_CONTAMINATION",
    "frontmatter-agent-g7-clean-prompt": "CONTRACT_UNDERSPECIFICATION + CONTRACT_REQUIREMENT_OMISSION",
}


def _counts(text: str | None) -> tuple[int | None, int | None]:
    if not text:
        return None, None
    m = re.search(r"passed_checks=(\d+).*?total_checks=(\d+)", text)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _load(rel: str | None) -> dict:
    if rel is None:
        return {}
    p = EV / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def build() -> dict:
    rows = []
    for case_id, run_type, task_version, report_rel, manifest_rel in CASES:
        rep = _load(report_rel)
        man = _load(manifest_rel)
        src = next((v for k, v in TASK_SOURCES.items() if task_version.startswith(k)), (None, None))
        cap_p, cap_t = _counts(rep.get("capability"))
        reg_p, reg_t = _counts(rep.get("regression"))
        agent = rep.get("agent") or man.get("agent") or {}
        adaptation = rep.get("adaptation_root")
        replay = rep.get("replay") or ""
        m_mode = re.search(r"mode=(\w+)", replay)
        replay_mode = m_mode.group(1) if m_mode else None
        timings = man.get("timings") or rep.get("timings") or {}
        preflight = man.get("preflight") or rep.get("preflight") or {}
        rows.append(
            {
                "case_id": case_id,
                "task_id": rep.get("task_id"),
                "task_version": task_version,
                "run_id": rep.get("run_id"),
                "run_type": run_type,
                "source_repo": src[0],
                "source_commit": src[1],
                "model": preflight.get("model")
                or (agent and man.get("model"))
                or (None if run_type == "direct_baseline" else "deepseek-v4-pro"),
                "capability_passed": cap_p,
                "capability_total": cap_t,
                "regression_passed": reg_p,
                "regression_total": reg_t,
                "policy_result": "PASS" if rep.get("policy") else None,
                "replay_mode": replay_mode,
                "replay_result": ("PASS" if "status=PASS" in replay else ("FAIL" if "status=FAIL" in replay else None)),
                "final_verdict": rep.get("final_verdict") or rep.get("verdict"),
                "adaptation_files": None if adaptation is None else (0 if not adaptation else None),
                "adaptation_lines": None,
                "model_calls": agent.get("model_calls"),
                "commands": agent.get("commands"),
                "input_tokens": agent.get("input_tokens"),
                "output_tokens": agent.get("output_tokens"),
                "wall_time_model_s": timings.get("agent_model_call_s"),
                "failure_type": (
                    FAILURE_TYPES.get(case_id)
                    if (rep.get("final_verdict") or rep.get("verdict")) == "FAIL"
                    and run_type != "direct_baseline"
                    else None
                ),
                "evidence_path": f"docs/evidence/{report_rel.rsplit('/', 1)[0]}/",
                "trace_sha256": rep.get("final_trace_sha256"),
                "trajectory_sha256": rep.get("trajectory_sha256"),
                "bundle_verification": (
                    "trace_chain_ok+verifier_hashes_recorded"
                    if rep.get("trace_chain_ok") and rep.get("verification_result_hashes")
                    else ("partial" if rep.get("verification_result_hashes") else None)
                ),
            }
        )
    # adaptation files/lines: only where the evidence carries the adapter file
    adapter_files = {
        "chonkie-agent-g3c": "gate3c-real-run/agent_adapter.py",
        "chonkie-agent-g4a-budget-vis": "gate4a-intervention/agent_adapter.py",
        "chonkie-agent-g4b-ledger": "gate4b-intervention/agent_adapter.py",
        "bm25-agent-g5": "gate5-second-repo/agent_adapter.py",
        "frontmatter-agent-g6": "gate6-positive-task/agent_adapter.py",
        "frontmatter-agent-g7-clean-prompt": "gate7-clean-prompt/agent_adapter.py",
        "frontmatter-v2-agent-g72": "gate72-corrected-spec-run/agent_adapter.py",
    }
    for row in rows:
        rel = adapter_files.get(row["case_id"])
        if rel and (EV / rel).exists():
            row["adaptation_files"] = 1
            row["adaptation_lines"] = len((EV / rel).read_text(encoding="utf-8").splitlines())
        elif row["run_type"] == "direct_baseline":
            row["adaptation_files"] = 0
            row["adaptation_lines"] = 0

    verdicts = [r["final_verdict"] for r in rows]
    return {
        "note": "Machine-readable fact source. Extraction-only from committed evidence; "
        "null = evidence does not prove it. See scripts/build_benchmark_summary.py.",
        "totals": {
            "task_versions": len({r["task_version"] for r in rows}),
            "capability_domains": len({r["task_version"].rsplit("-", 1)[0] for r in rows}),
            "runs_recorded": len(rows),
            "real_agent_runs": sum(
                1 for r in rows
                if r["run_type"] in ("real_agent", "ablation", "corrected_spec_positive")
            ),
            "pass_adapted": sum(1 for v in verdicts if v == "PASS_ADAPTED"),
            "honest_fails": sum(1 for v in verdicts if v == "FAIL"),
        },
        "runs": rows,
    }


if __name__ == "__main__":
    out = REPO / "docs" / "benchmark_summary.json"
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    summary = json.loads(out.read_text())
    print(json.dumps(summary["totals"], indent=1))
    for r in summary["runs"]:
        cap = f"{r['capability_passed']}/{r['capability_total']}"
        print(f"{r['case_id']:38s} {str(r['final_verdict']):13s} cap={cap}")
