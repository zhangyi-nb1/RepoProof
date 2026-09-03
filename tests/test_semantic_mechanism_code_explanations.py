"""语义筛自己的机制码也要带公开解释(incident-semantic-mechanism-code-unexplained-*)。

不变量:裁决者的原因码已带 reason_details;Harness 控制组产生的机制码
(INPUT_BINDING_CONTROL_FAILED / ARTIFACT_BINDING_CONTROL_FAILED /
UPSTREAM_RESULT_BINDING_CONTROL_FAILED / UPSTREAM_CALL_NOT_OBSERVED /
COMMITMENT_COVERAGE_MISMATCH)同样必须带一句"观察到什么、违反哪条规则"的解释,
COMMITMENT_COVERAGE_MISMATCH 还要列出缺失/多余的 commitment id。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from repoproof.verification.workspace_semantic import run_workspace_semantic_verifier

_spec = importlib.util.spec_from_file_location(
    "_semantic_fixtures", Path(__file__).with_name("test_workspace_semantic.py")
)
_fx = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fx)

_INPUT_BLIND_VERIFIER = '''from pathlib import Path
import miniworkspace

def verify(input_path: Path, artifact_path: Path) -> dict:
    miniworkspace.render("x")
    ok = (artifact_path / "README.md").read_text().startswith("# ")
    return {"ok": ok, "reason_codes": [] if ok else ["NO_HEADING"], "checked_commitment_ids": ["render-workspace"]}
'''


def _run(world, required):
    return run_workspace_semantic_verifier(
        verifier_id="workspace-semantics-v1",
        verifier_source=world["verifier"],
        input_path=world["input"],
        artifact_dir=world["artifact"],
        python_exe=sys.executable,
        upstream_dir=world["upstream"],
        import_module="miniworkspace",
        upstream_commit="a" * 40,
        workspace_contract_sha256="b" * 64,
        intent_confirmation_sha256="c" * 64,
        required_commitment_ids=required,
        isolation_required=False,
    )


def test_input_binding_control_failure_is_explained(tmp_path: Path) -> None:
    evidence = _run(_fx._world(tmp_path, verifier=_INPUT_BLIND_VERIFIER), ["render-workspace"])
    assert evidence.passed is False
    assert "INPUT_BINDING_CONTROL_FAILED" in evidence.reason_codes
    detail = dict(evidence.reason_details)["INPUT_BINDING_CONTROL_FAILED"].lower()
    assert "input" in detail and ("accept" in detail or "still" in detail)


def test_commitment_coverage_mismatch_lists_missing_and_extra_ids(tmp_path: Path) -> None:
    evidence = _run(_fx._world(tmp_path), ["render-workspace", "index-page"])
    assert evidence.passed is False
    assert "COMMITMENT_COVERAGE_MISMATCH" in evidence.reason_codes
    detail = dict(evidence.reason_details)["COMMITMENT_COVERAGE_MISMATCH"]
    assert "index-page" in detail and "missing" in detail.lower()


def test_drafting_prompt_teaches_reproducibility_up_front() -> None:
    from repoproof.adoption.intake import tool_drafter

    lowered = tool_drafter._SYSTEM.lower()
    assert "reproducible" in lowered and "clock" in lowered
