"""Qualification attempts are immutable Product evidence, never Lab scores."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from repoproof.persistence.qualification_records import (
    QualificationCaseResultV1,
    QualificationCaseResultV2,
    QualificationExecutionRecordV1,
    QualificationExecutionRecordV2,
    QualificationRecordError,
    qualification_framework_tree_sha256,
    write_qualification_record,
)
from repoproof.verification.semantic_artifact import (
    SemanticVerifierEvidenceV1,
    semantic_verifier_evidence_sha256,
)
from repoproof.verification.workspace_semantic import (
    SemanticVerifierEvidenceV2,
    workspace_semantic_evidence_sha256,
)


def _semantic_evidence() -> SemanticVerifierEvidenceV1:
    return SemanticVerifierEvidenceV1(
        verifier_id="independent-case-verifier-v1",
        verifier_source_sha256="e" * 64,
        input_sha256="0" * 64,
        artifact_sha256="1" * 64,
        output_contract_sha256="2" * 64,
        intent_confirmation_sha256="3" * 64,
        upstream_commit="4" * 40,
        import_module="synthetic_upstream",
        upstream_imports=1,
        upstream_calls=1,
        input_negative_control_sha256="6" * 64,
        input_negative_control_result="REJECTED",
        input_negative_control_upstream_imports=0,
        input_negative_control_upstream_calls=0,
        artifact_negative_control_sha256="5" * 64,
        artifact_negative_control_result="REJECTED",
        artifact_negative_control_upstream_imports=1,
        artifact_negative_control_upstream_calls=1,
        upstream_result_counterfactual_result="REJECTED",
        upstream_result_counterfactual_upstream_imports=1,
        upstream_result_counterfactual_upstream_calls=1,
        required_commitment_ids=("commitment-one",),
        checked_commitment_ids=("commitment-one",),
        passed=True,
        reason_codes=(),
    )


def _record(*, status: str = "PASSED") -> QualificationExecutionRecordV1:
    case_status = "PASSED" if status == "PASSED" else "FAILED"
    evidence = _semantic_evidence() if case_status == "PASSED" else None
    return QualificationExecutionRecordV1(
        execution_id="m6-1-multiformat-v2-attempt-1",
        protocol_id="m6.1-natural-requirements-multiformat-qualification-v2",
        protocol_sha256="a" * 64,
        framework_git_commit="b" * 40,
        framework_tree_sha256="c" * 64,
        backend="mini-swe",
        started_at="2026-08-30T00:00:00Z",
        completed_at="2026-08-30T01:00:00Z",
        status=status,
        invalidated_batch_and_restart_reason=(
            "generic harness defect; restart from case one"
            if status == "INVALIDATED"
            else None
        ),
        cases=(QualificationCaseResultV1(
            case_name="case-one",
            status=case_status,
            journey_id="d" * 32,
            task_id="tool-case-one-v1",
            run_id="tool-case-one-v1-run",
            historical_verdict=(
                "VERIFIED_TOOL_READY" if case_status == "PASSED" else None
            ),
            clean_replay="PASS" if case_status == "PASSED" else None,
            fresh_audit="PASS" if case_status == "PASSED" else None,
            operational_status="ACTIVE" if case_status == "PASSED" else None,
            package_health="OK" if case_status == "PASSED" else None,
            output_validation_profile=(
                "plain_text_v1" if case_status == "PASSED" else None
            ),
            semantic_verifier_id=(
                "independent-case-verifier-v1" if case_status == "PASSED" else None
            ),
            semantic_verifier_sha256="e" * 64 if case_status == "PASSED" else None,
            semantic_verifier_evidence_sha256=(
                semantic_verifier_evidence_sha256(evidence)
                if evidence is not None
                else None
            ),
            semantic_verifier_passed=True if case_status == "PASSED" else None,
            semantic_verifier_evidence=evidence,
            artifact_sha256="1" * 64 if case_status == "PASSED" else None,
        ),),
    )


def test_write_is_create_only_and_product_scoring_is_always_false(tmp_path: Path) -> None:
    record = _record()
    path = write_qualification_record(tmp_path / "qualification-runs", record)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["test_mode"] == "PRODUCT"
    assert all(
        document[field] is False
        for field in (
            "counts_toward_model_score",
            "counts_toward_stage_gate",
            "counts_toward_profile_qualification",
            "counts_toward_observation_policy_qualification",
        )
    )
    with pytest.raises(QualificationRecordError, match="append-only"):
        write_qualification_record(path.parent, record)


def test_invalidated_attempt_requires_reason_and_pass_requires_all_cases() -> None:
    with pytest.raises(ValidationError, match="restart reason"):
        QualificationExecutionRecordV1(
            **{
                **_record(status="INVALIDATED").model_dump(),
                "invalidated_batch_and_restart_reason": None,
            }
        )


def test_passed_case_cannot_omit_semantic_verifier_or_artifact_evidence() -> None:
    complete = _record().cases[0].model_dump()
    for field in (
        "semantic_verifier_id",
        "semantic_verifier_sha256",
        "semantic_verifier_evidence_sha256",
        "semantic_verifier_evidence",
        "artifact_sha256",
        "fresh_audit",
        "output_validation_profile",
    ):
        with pytest.raises(ValidationError, match="missing evidence"):
            QualificationCaseResultV1(**{**complete, field: None})

    with pytest.raises(ValidationError, match="semantic verifier PASS"):
        QualificationCaseResultV1(
            **{**complete, "semantic_verifier_passed": False}
        )
    with pytest.raises(ValidationError, match="mismatched evidence"):
        QualificationCaseResultV1(
            **{**complete, "artifact_sha256": "9" * 64}
        )
    with pytest.raises(ValidationError, match="every preregistered case"):
        QualificationExecutionRecordV1(
            **{
                **_record().model_dump(),
                "cases": [{"case_name": "case-one", "status": "FAILED"}],
            }
        )


def test_symlink_record_root_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "qualification-runs"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(QualificationRecordError, match="unsafe"):
        write_qualification_record(linked, _record())


def test_framework_tree_fingerprint_is_path_and_content_bound(
    tmp_path: Path,
) -> None:
    package = tmp_path / "repoproof"
    (package / "nested").mkdir(parents=True)
    (package / "a.py").write_text("A = 1\n", encoding="utf-8")
    (package / "nested" / "b.py").write_text("B = 2\n", encoding="utf-8")
    (package / "ignored.txt").write_text("not executable source\n", encoding="utf-8")

    first = qualification_framework_tree_sha256(package)
    assert first == qualification_framework_tree_sha256(package)
    (package / "ignored.txt").write_text("changed\n", encoding="utf-8")
    assert qualification_framework_tree_sha256(package) == first
    (package / "nested" / "b.py").write_text("B = 3\n", encoding="utf-8")
    assert qualification_framework_tree_sha256(package) != first

    linked = tmp_path / "linked-package"
    linked.symlink_to(package, target_is_directory=True)
    with pytest.raises(QualificationRecordError, match="unsafe"):
        qualification_framework_tree_sha256(linked)


def _workspace_evidence() -> SemanticVerifierEvidenceV2:
    return SemanticVerifierEvidenceV2(
        verifier_id="independent-workspace-verifier-v1",
        verifier_source_sha256="1" * 64,
        input_kind="directory",
        input_sha256="2" * 64,
        artifact_tree_sha256="3" * 64,
        artifact_manifest_sha256="4" * 64,
        workspace_contract_sha256="5" * 64,
        intent_confirmation_sha256="6" * 64,
        upstream_commit="7" * 40,
        import_module="synthetic_upstream",
        upstream_imports=1,
        upstream_calls=1,
        input_negative_control_sha256="8" * 64,
        input_negative_control_result="REJECTED",
        artifact_negative_control_tree_sha256="9" * 64,
        artifact_negative_control_result="REJECTED",
        upstream_result_counterfactual_result="REJECTED",
        upstream_result_counterfactual_upstream_imports=1,
        upstream_result_counterfactual_upstream_calls=1,
        required_commitment_ids=("workspace-output",),
        checked_commitment_ids=("workspace-output",),
        passed=True,
    )


def test_v2_records_success_and_expected_admission_rejection(tmp_path: Path) -> None:
    evidence = _workspace_evidence()
    success = QualificationCaseResultV2(
        case_name="baseline-one",
        status="PASSED",
        journey_id="a" * 32,
        task_id="tool-baseline-one-v1",
        run_id="run-one",
        historical_verdict="VERIFIED_TOOL_READY",
        clean_replay="PASS",
        fresh_audit="PASS",
        operational_status="ACTIVE",
        package_health="OK",
        artifact_tree_sha256=evidence.artifact_tree_sha256,
        artifact_manifest_sha256=evidence.artifact_manifest_sha256,
        workspace_structure_passed=True,
        semantic_verifier_id=evidence.verifier_id,
        semantic_verifier_sha256=evidence.verifier_source_sha256,
        semantic_verifier_evidence_sha256=workspace_semantic_evidence_sha256(evidence),
        semantic_verifier_evidence=evidence,
        agent_invoked=True,
        repair_attempts=1,
    )
    rejection = QualificationCaseResultV2(
        case_name="negative-control",
        status="EXPECTED_REJECTION",
        failure_stage="ADMISSION",
        failure_owner="USER_INPUT",
        reason_codes=("UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT",),
        recommended_action="Use an offline reversible task.",
        agent_invoked=False,
        repair_attempts=0,
    )
    record = QualificationExecutionRecordV2(
        execution_id="m6-2-workspace-attempt-1",
        protocol_id="m6.2-workspace-bundle-qualification-v1",
        protocol_sha256="a" * 64,
        framework_git_commit="b" * 40,
        framework_tree_sha256="c" * 64,
        started_at="2026-08-31T00:00:00Z",
        completed_at="2026-08-31T01:00:00Z",
        status="COMPLETED",
        cases=(rejection, success),
    )
    path = write_qualification_record(tmp_path, record)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_v2_failure_cannot_be_active_or_ambiguous() -> None:
    with pytest.raises(ValidationError, match="one failure verdict"):
        QualificationCaseResultV2(
            case_name="failed",
            status="FAILED",
            agent_invoked=False,
            repair_attempts=0,
        )
    with pytest.raises(ValidationError, match="cannot be ACTIVE"):
        QualificationCaseResultV2(
            case_name="failed",
            status="FAILED",
            operational_status="ACTIVE",
            failure_stage="CLEAN_REPLAY",
            failure_owner="HARNESS",
            reason_codes=("REPLAY_DRIFT",),
            recommended_action="Inspect the package.",
            agent_invoked=False,
            repair_attempts=0,
        )
