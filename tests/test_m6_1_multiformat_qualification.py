"""Static guardrails for the preregistered multi-format qualification batch."""

from __future__ import annotations

from pathlib import Path

import yaml

from repoproof.domain.models import ToolOutputContract

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "docs" / "m6_1_multiformat_qualification.yaml"


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_multiformat_batch_pins_order_and_upstream_identity() -> None:
    document = _manifest()
    cases = document["cases"]
    assert document["result"]["status"] == "NOT_RUN"
    assert [(case["order"], case["name"]) for case in cases] == [
        (1, "rispy-reference-cleanup"),
        (2, "pint-lab-unit-table"),
        (3, "networkx-project-note"),
        (4, "biopython-fastq-qc-report"),
    ]
    assert [
        (
            case["package_version"],
            case["ui_revision"],
            case["ui_revision_kind"],
            case["resolved_commit"],
        )
        for case in cases
    ] == [
        (
            "0.10.0",
            "v0.10.0",
            "tag",
            "b7aae3b2069ced3fb75287711300f2edf0bcac21",
        ),
        (
            "0.25.3",
            "0.25.3",
            "tag",
            "5e79411e1be2dc39c52a536168338773b49fd512",
        ),
        (
            "3.6.1",
            "networkx-3.6.1",
            "tag",
            "7530809bfa1ea7ed6fdf918a4d1431488953cb1f",
        ),
        (
            "1.88",
            "biopython-188",
            "tag",
            "d7e4b8b19399668b09442a5b35765d9186b5f665",
        ),
    ]
    assert all(len(case["resolved_commit"]) == 40 for case in cases)
    assert all("version" not in case for case in cases)
    assert cases[3]["ui_revision"] != cases[3]["package_version"]


def test_multiformat_batch_preregisters_four_non_json_text_artifacts() -> None:
    cases = _manifest()["cases"]
    expected = [
        ("application/x-research-info-systems", ".ris"),
        ("text/tab-separated-values", ".tsv"),
        ("text/markdown", ".md"),
        ("text/html", ".html"),
    ]
    actual = []
    for case in cases:
        contract = ToolOutputContract.model_validate(case["output_contract"])
        assert contract.root_type == "text"
        assert contract.required == {}
        assert "json" not in contract.media_type
        assert case["deliverable"]["transport"] == "utf8_stdout_and_out_file"
        actual.append((contract.media_type, case["deliverable"]["extension"]))
    assert actual == expected


def test_multiformat_batch_preserves_vague_human_intent_and_llm_first_examples() -> None:
    document = _manifest()
    policy = document["journey_policy"]
    assert policy["initial_request_is_intentionally_vague"] is True
    assert policy["requirement_brief_count"] == {"minimum": 2, "maximum": 3}
    assert policy["adopted_brief_remains_user_language"] is True
    assert policy["adoption_does_not_freeze_contract"] is True
    assert policy["example_candidates_are_llm_proposed"] is True
    assert policy["expected_outputs_are_upstream_derived"] is True
    assert policy["minimum_confirmed_success_examples"] == 3
    assert policy["confirmed_example_provenance_required"] == (
        "UPSTREAM_DERIVED_USER_CONFIRMED"
    )
    assert policy["confirmed_example_binding_hash_required"] is True
    assert policy["prepared_user_upload_required"] is False

    forbidden_implementation_terms = (
        "callable", "import ", "root_type", "schema", "tie-break", "--",
    )
    for case in document["cases"]:
        initial = case["initial_user_request"].strip()
        adopted = case["expected_adopted_brief"].strip()
        assert initial and adopted
        assert len(initial) < 180
        assert len(adopted) < 180
        assert not any(term in adopted.lower() for term in forbidden_implementation_terms)
        assert len(case["candidate_scenarios"]) >= 4
        assert sum(item["role"] == "success" for item in case["candidate_scenarios"]) >= 3


def test_every_case_requires_format_semantics_not_just_parseability() -> None:
    document = _manifest()
    assert document["implementation_status"]["case_specific_semantic_verifier_receipts"] == (
        "PENDING_FROZEN_TASKS"
    )
    cases = document["cases"]
    assert all(len(case["hidden_acceptance_rules"]) >= 5 for case in cases)
    assert all(len(case["semantic_verifier_requirements"]) >= 3 for case in cases)

    requirements = "\n".join(
        requirement
        for case in cases
        for requirement in case["semantic_verifier_requirements"]
    ).lower()
    for pinned_library in ("rispy", "pint", "networkx", "biopython"):
        assert pinned_library in requirements
    for semantic_obligation in ("round-trip", "recalculate", "recompute"):
        assert semantic_obligation in requirements
    assert document["verification_policy"] == {
        "generic_media_contract_parsers": [
            "application/x-research-info-systems",
            "text/tab-separated-values",
            "text/markdown",
            "text/html",
        ],
        "semantic_truth_source": "frozen_reference_calling_pinned_upstream",
        "actual_output_compared_with_reference": True,
        "held_out_examples_required": True,
        "case_specific_semantic_requirements_are_closure_gates": True,
    }


def test_batch_discipline_prevents_claims_and_mid_batch_framework_changes() -> None:
    document = _manifest()
    policy = document["execution_policy"]
    assert policy["order_is_fixed"] is True
    assert policy["framework_changes_during_batch"] is False
    assert policy["restart_from_first_case_after_framework_fix"] is True
    assert policy["backend_is_fixed_during_batch"] is True
    assert policy["fixed_agent_backend"] == "mini-swe"
    assert policy["json_user_artifact_forbidden"] is True
    assert policy["binary_output_out_of_scope"] is True
    assert policy["reference_runtime_network"] == "none"
    assert policy["reference_runtime_writes"] == "disposable_directory_only"
    assert policy["reference_isolation_fail_closed"] is True
    assert "No model call" in document["result"]["evidence_scope"]
    assert document["result"]["append_only_execution_record_required"] == [
        "framework_git_commit",
        "framework_tree_sha256",
        "case_to_journey_task_run_mapping",
        "invalidated_batch_and_restart_reason",
    ]
