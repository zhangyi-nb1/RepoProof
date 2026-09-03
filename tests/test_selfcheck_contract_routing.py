"""自检路由:合同结构性缺陷修合同,不修 reference
(incident-selfcheck-contract-defect-misrouted-{mkdocs,xlsx}-v1)。"""

from __future__ import annotations

from repoproof.adoption.intake.draft_selfcheck import repair_target_for


def test_structural_contract_codes_route_to_contract() -> None:
    for diagnostic in ("WORKSPACE_RULE_OVERLAP", "WORKSPACE_PATH_TOO_DEEP", "WORKSPACE_FILE_COUNT_EXCEEDED"):
        assert (
            repair_target_for("WORKSPACE_REFERENCE_CONTRACT_FAILED", round_index=1, diagnostics=(diagnostic,))
            == "contract"
        )
    assert (
        repair_target_for(
            "WORKSPACE_REFERENCE_CONTRACT_FAILED",
            round_index=1,
            diagnostics=("WORKSPACE_FORMAT_UTF8_INVALID,WORKSPACE_RULE_OVERLAP",),
        )
        == "contract"
    )


def test_output_shape_codes_still_route_to_reference() -> None:
    for diagnostic in (
        "WORKSPACE_REQUIRED_ENTRY_MISSING",
        "WORKSPACE_FORMAT_UTF8_INVALID",
        "WORKSPACE_HTML_EXTERNAL_RESOURCE",
    ):
        assert (
            repair_target_for("WORKSPACE_REFERENCE_CONTRACT_FAILED", round_index=1, diagnostics=(diagnostic,))
            == "reference"
        )
    assert repair_target_for("WORKSPACE_REFERENCE_CONTRACT_FAILED", round_index=1) == "reference"


def test_not_reproducible_routes_to_reference() -> None:
    assert (
        repair_target_for(
            "WORKSPACE_REFERENCE_NOT_REPRODUCIBLE", round_index=1, diagnostics=("report.pptx=ZIP_METADATA_ONLY",)
        )
        == "reference"
    )
