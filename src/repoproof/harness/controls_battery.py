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


def classify_negative_control(nodes: list[dict], must_fail_nodes: list[str]) -> str:
    """负控一次运行 → 判词。负控必须**真红**才算"拦下了作弊"。

    2026-08-16(HB 首发 skipped≠failed 同病扫查):原式把"非 passed"
    一律记作失败,于是一个因平台标记 / 导入失败而被 **跳过** 的必红用例
    会冒充 ``FAILED_AS_EXPECTED`` —— 控制这一轮根本没考,却发了一张
    "已验证"的证书。这是与首发缺陷反方向的同一个病:那边把跳过当红,
    这边把跳过当"红得正是时候"。两处都要 fail-closed。
    """
    failed_nodes = {n["node_id"] for n in nodes if n["outcome"] in ("failed", "error")}
    skipped_nodes = {n["node_id"] for n in nodes if n["outcome"] == "skipped"}
    hit = [m for m in must_fail_nodes if any(m in n for n in failed_nodes)]
    if failed_nodes and len(hit) == len(must_fail_nodes):
        return FAILED_AS_EXPECTED
    skipped_must = sorted(m for m in must_fail_nodes
                          if any(m in n for n in skipped_nodes))
    if skipped_must:
        # 把"跳过"写进判词本身,不让它混进 NOT_REJECTED 之类的别的病名。
        return f"MUST_FAIL_NODE_SKIPPED:{skipped_must}"
    if not failed_nodes:
        return "NOT_REJECTED"
    return f"WRONG_NODES:missing={sorted(set(must_fail_nodes) - set(hit))}"


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
        nc_nodes = _run(nc.path).get("nodes", [])
        summary[f"negative_control_{nc.label}"] = classify_negative_control(
            nc_nodes, nc.must_fail_nodes)
    return summary
