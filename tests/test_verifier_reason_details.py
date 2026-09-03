"""裁决者的拒绝理由必须能被修复方读到(incident-verifier-reason-detail-not-carried-*)。

不变量:verify() 可选返回 `reason_details`(code → ≤200 字公开一句话);Harness 只
接受已出现的 reason code 的解释、截断超长、丢弃未知键;没有该键的旧 verifier 照常。
自检的分歧诊断随之带上 `CODE: 解释`,让 reference 修复知道裁决者到底要什么。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_semantic_fixtures", Path(__file__).with_name("test_workspace_semantic.py")
)
_fx = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fx)

_DETAILED_VERIFIER = """from pathlib import Path
import miniworkspace

def verify(input_path: Path, artifact_path: Path) -> dict:
    miniworkspace.render("x")
    return {
        "ok": False,
        "reason_codes": ["SECTION_ENCODING_MISMATCH", "TABLE_ORDER_MISMATCH"],
        "checked_commitment_ids": ["render-workspace"],
        "reason_details": {
            "SECTION_ENCODING_MISMATCH": (
                "README section 'Sheets' must list one `- name: <sheet>` line per workbook sheet"
            ),
            "TABLE_ORDER_MISMATCH": "t" * 400,
            "NOT_A_REPORTED_CODE": "ignored",
        },
    }
"""


def test_reason_details_are_carried_bounded_and_scoped_to_reported_codes(tmp_path: Path) -> None:
    evidence = _fx._run(_fx._world(tmp_path, verifier=_DETAILED_VERIFIER))
    assert evidence.passed is False
    assert set(evidence.reason_codes) >= {"SECTION_ENCODING_MISMATCH", "TABLE_ORDER_MISMATCH"}
    details = dict(evidence.reason_details)
    assert details["SECTION_ENCODING_MISMATCH"].startswith("README section 'Sheets' must list")
    assert len(details["TABLE_ORDER_MISMATCH"]) == 200
    assert "NOT_A_REPORTED_CODE" not in details


def test_verifier_without_details_is_still_accepted(tmp_path: Path) -> None:
    evidence = _fx._run(_fx._world(tmp_path))
    assert evidence.passed is True
    assert dict(evidence.reason_details) == {}


def test_selfcheck_disagreement_diagnostics_include_details(tmp_path: Path, monkeypatch) -> None:
    from repoproof.ui.services import product_jobs

    probe_spec = importlib.util.spec_from_file_location(
        "_probe_fixtures", Path(__file__).parent / "ui" / "test_reference_reproducibility_probe.py"
    )
    probe = importlib.util.module_from_spec(probe_spec)
    assert probe_spec.loader is not None
    probe_spec.loader.exec_module(probe)
    draft, _runs = probe._prepare(tmp_path, monkeypatch, drift=False)
    monkeypatch.setattr(
        "repoproof.verification.workspace_semantic.run_workspace_semantic_verifier",
        lambda **_k: type(
            "S",
            (),
            {
                "passed": False,
                "reason_codes": ["SECTION_ENCODING_MISMATCH"],
                "reason_details": {"SECTION_ENCODING_MISMATCH": "README section 'Sheets' must list one line per sheet"},
                "evidence": None,
            },
        )(),
    )
    result = product_jobs.propose_workspace_fixture_candidates(draft, n=1, offline=True)
    assert result["ok"] is False
    assert result["reason_codes"] == ["WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"]
    assert result["diagnostics"][0] == "SECTION_ENCODING_MISMATCH"
    assert "SECTION_ENCODING_MISMATCH: README section 'Sheets' must list one line per sheet" in result["diagnostics"]
