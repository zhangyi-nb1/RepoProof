"""Positive/negative control battery — run at freeze time, results
frozen into the TaskPackageManifest and re-checked by the
ContractAdequacyGate. A task whose positive control cannot pass, or
whose cheats are not rejected, is an INVALID_TASK_SPEC before any
agent exists."""

from __future__ import annotations

import os
from pathlib import Path

from repoproof.domain.models import TaskContract
from repoproof.harness.requirement_spec import RequirementSpec

PASS = "PASS"
FAILED_AS_EXPECTED = "FAILED_AS_EXPECTED"


def run_controls_battery(
    project_root: Path,
    contract: TaskContract,
    spec: RequirementSpec,
    *,
    upstream: Path,
    wheelhouse: Path,
) -> dict[str, str]:
    """Returns {'positive_control': ..., 'negative_control_<label>': ...}.
    Any value other than PASS / FAILED_AS_EXPECTED marks the battery
    (and therefore adequacy) as failed."""
    from repoproof.runner.calibration import run_oracle_with_adapter

    if spec.controls is None:
        return {"positive_control": "MISSING_CONTROLS_SPEC"}

    oracle_dir = project_root / "oracle" / contract.task_id
    consumer_dir = project_root / Path(contract.target_project.path)
    user = f"{os.getuid()}:{os.getgid()}"

    def _run(adapter_rel: str) -> dict:
        return run_oracle_with_adapter(
            project_root=project_root,
            upstream=upstream,
            wheelhouse=wheelhouse,
            oracle_dir=oracle_dir,
            adapter_dir=project_root / adapter_rel,
            consumer_dir=consumer_dir,
            user=user,
        )

    summary: dict[str, str] = {}
    pos = _run(spec.controls.positive)
    totals = pos.get("totals") or {}
    if pos["exit_code"] == 0 and totals.get("failures") == 0 and totals.get("errors") == 0:
        summary["positive_control"] = PASS
    else:
        summary["positive_control"] = f"FAIL:exit={pos['exit_code']}"

    for nc in spec.controls.negatives:
        failed_nodes = {n["node_id"] for n in _run(nc.path).get("nodes", []) if n["outcome"] != "passed"}
        hit = [m for m in nc.must_fail_nodes if any(m in n for n in failed_nodes)]
        if failed_nodes and len(hit) == len(nc.must_fail_nodes):
            summary[f"negative_control_{nc.label}"] = FAILED_AS_EXPECTED
        elif not failed_nodes:
            summary[f"negative_control_{nc.label}"] = "NOT_REJECTED"
        else:
            missing = sorted(set(nc.must_fail_nodes) - set(hit))
            summary[f"negative_control_{nc.label}"] = f"WRONG_NODES:missing={missing}"
    return summary
