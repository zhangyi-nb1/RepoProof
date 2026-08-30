"""Second four-repository Product qualification is fixed before execution."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
V2 = REPO / "docs" / "m6_1_multiformat_qualification_v2.yaml"
V3 = REPO / "docs" / "m6_1_multiformat_qualification_v3.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_v3_keeps_the_same_pinned_upstreams_but_changes_every_capability() -> None:
    previous = _load(V2)
    current = _load(V3)

    assert current["schema_version"] == 3
    assert current["result"]["status"] == "NOT_RUN"
    assert current["batch_id"] != previous["batch_id"]
    assert current["extends_recorded_support_from"] == previous["batch_id"]
    assert [case["repository"] for case in current["cases"]] == [
        case["repository"] for case in previous["cases"]
    ]
    assert [case["resolved_commit"] for case in current["cases"]] == [
        case["resolved_commit"] for case in previous["cases"]
    ]
    assert {case["name"] for case in current["cases"]}.isdisjoint(
        {case["name"] for case in previous["cases"]}
    )


def test_v3_exercises_distinct_environments_difficulty_and_io_shapes() -> None:
    document = _load(V3)
    cases = document["cases"]

    assert [case["complexity"] for case in cases] == [
        "basic_to_medium",
        "medium",
        "higher",
        "medium_to_high",
    ]
    assert len({case["application_environment"] for case in cases}) == 4
    assert [case["input_artifact"]["format"] for case in cases] == [
        "RIS",
        "TSV",
        "CSV edge list",
        "multi-record FASTA",
    ]
    assert [case["expected_artifact"]["media_type"] for case in cases] == [
        "text/csv",
        "text/html",
        "text/tab-separated-values",
        "text/markdown",
    ]
    assert [
        case["expected_artifact"]["validation_profile"] for case in cases
    ] == [
        "csv_table_v1",
        "safe_self_contained_xhtml_v1",
        "tsv_table_v1",
        "markdown_document_v1",
    ]
    assert len({case["intended_tool_name"] for case in cases}) == 4
    assert all(
        case["expected_artifact"]["extension"] != ".json" for case in cases
    )


def test_v3_keeps_the_human_journey_and_public_rule_boundary() -> None:
    document = _load(V3)
    intent = document["intent_policy"]
    journey = document["journey_policy"]

    assert intent["initial_request_is_intentionally_vague"] is True
    assert intent["repository_analysis_precedes_drafting"] is True
    assert intent["hidden_normative_rules_forbidden"] is True
    assert intent["missing_commitment_is_not_agent_repair_work"] is True
    assert journey["ui_only"] is True
    assert journey["example_candidates_are_llm_proposed"] is True
    assert journey["expected_outputs_are_upstream_derived"] is True
    assert journey["minimum_confirmed_success_examples"] == 3
    assert journey["confirmed_examples_survive_regeneration"] is True
    assert journey["prepared_user_upload_required"] is False
    for case in document["cases"]:
        assert len(case["public_commitments_required_before_freeze"]) >= 6
        assert "hidden_acceptance_rules" not in case


def test_v3_allows_only_generic_harness_repairs_without_restarting_passes() -> None:
    execution = _load(V3)["execution_policy"]

    assert execution["fixed_drafter_backend"] == "litellm"
    assert execution["fixed_agent_backend"] == "mini-swe"
    assert execution["generic_harness_repairs_are_allowed"] is True
    assert execution["repository_or_case_specific_core_patches_are_forbidden"] is True
    assert execution["completed_cases_are_not_restarted_after_a_generic_repair"] is True
    assert execution["contract_or_harness_failures_do_not_consume_agent_repair_rounds"] is True
    assert execution["agent_adapter_attempt_budget"] == 3
    assert execution["product_results_never_count_toward_benchmark_metrics"] is True


def test_v3_case_identities_never_enter_product_core() -> None:
    document = _load(V3)
    forbidden = {
        str(case[value]).lower()
        for case in document["cases"]
        for value in ("repository", "resolved_commit", "intended_tool_name")
    }
    offenders: list[str] = []
    for path in sorted((REPO / "src" / "repoproof").rglob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        matches = sorted(value for value in forbidden if value in source)
        if matches:
            offenders.append(f"{path.relative_to(REPO)}: {matches}")

    assert offenders == []
