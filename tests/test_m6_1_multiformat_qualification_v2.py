"""The amended batch exposes rules and leaves the v1 preregistration intact."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
V1 = REPO / "docs" / "m6_1_multiformat_qualification.yaml"
V2 = REPO / "docs" / "m6_1_multiformat_qualification_v2.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_v2_is_a_new_not_run_protocol_instead_of_a_v1_rewrite() -> None:
    old = _load(V1)
    amended = _load(V2)
    assert old["schema_version"] == 1
    assert old["result"]["status"] == "NOT_RUN"
    assert amended["schema_version"] == 2
    assert amended["result"]["status"] == "NOT_RUN"
    assert amended["supersedes_for_future_execution"] == old["batch_id"]
    assert amended["batch_id"] != old["batch_id"]


def test_v2_allows_hidden_inputs_but_never_hidden_rules() -> None:
    document = _load(V2)
    policy = document["intent_policy"]
    assert policy["hidden_normative_rules_forbidden"] is True
    assert policy["hidden_information_is_limited_to"] == [
        "held_out_input_bytes",
        "held_out_expected_output_bytes",
    ]
    assert policy["user_confirms_every_commitment_before_freeze"] is True
    assert policy["missing_commitment_is_not_agent_repair_work"] is True
    for case in document["cases"]:
        assert "hidden_acceptance_rules" not in case
        assert len(case["public_commitments_required_before_freeze"]) >= 5


def test_v2_keeps_gateway_backend_and_non_json_artifact_order_fixed() -> None:
    document = _load(V2)
    execution = document["execution_policy"]
    assert execution["fixed_drafter_backend"] == "litellm"
    assert execution["fixed_agent_backend"] == "mini-swe"
    assert execution["backend_is_fixed_during_batch"] is True
    assert execution["product_results_never_count_toward_benchmark_metrics"] is True
    assert [case["name"] for case in document["cases"]] == [
        "rispy-reference-cleanup",
        "pint-lab-unit-table",
        "networkx-project-note",
        "biopython-fastq-qc-report",
    ]
    assert [case["expected_artifact"]["media_type"] for case in document["cases"]] == [
        "application/x-research-info-systems",
        "text/tab-separated-values",
        "text/markdown",
        "text/html",
    ]
    assert [
        case["expected_artifact"]["validation_profile"]
        for case in document["cases"]
    ] == [
        "ris_interchange_v1",
        "tsv_table_v1",
        "markdown_document_v1",
        "safe_self_contained_xhtml_v1",
    ]


def test_v2_execution_results_have_a_create_only_record_schema() -> None:
    document = _load(V2)
    result = document["result"]
    verification = document["verification_policy"]
    assert verification["semantic_verifier_protocol"] == (
        "repoproof-semantic-verifier-v1"
    )
    assert verification["verifier_logic_is_task_authored_not_harness_hardcoded"] is True
    assert verification["verifier_pass_requires_signed_runtime_upstream_call"] is True
    assert result["record_schema"] == "QualificationExecutionRecordV1"
    assert result["append_only_record_directory"].endswith("m6_1_multiformat_v2")
    assert "no model call" in result["evidence_scope"].lower()
    assert set(result["passed_case_evidence_required"]) == {
        "historical_verdict",
        "clean_replay",
        "fresh_audit",
        "operational_status",
        "package_health",
        "output_validation_profile",
        "semantic_verifier_id",
        "semantic_verifier_sha256",
        "semantic_verifier_evidence_sha256",
        "semantic_verifier_evidence",
        "artifact_sha256",
    }


def test_product_core_contains_no_four_case_identity_special_cases() -> None:
    """Qualification identities belong to task data, never Harness branches."""

    forbidden = {
        "mrtango/rispy",
        "hgrecco/pint",
        "networkx/networkx",
        "biopython/biopython",
        "tool-rispy-tool",
        "tool-pint-tool",
        "tool-networkx-tool",
        "tool-biopython-tool",
        "b7aae3b2069ced3fb75287711300f2edf0bcac21",
        "5e79411e1be2dc39c52a536168338773b49fd512",
        "7530809bfa1ea7ed6fdf918a4d1431488953cb1f",
        "d7e4b8b19399668b09442a5b35765d9186b5f665",
    }
    offenders: list[str] = []
    for path in sorted((REPO / "src" / "repoproof").rglob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        matched = sorted(value for value in forbidden if value in source)
        if matched:
            offenders.append(f"{path.relative_to(REPO)}: {matched}")

    assert offenders == []
