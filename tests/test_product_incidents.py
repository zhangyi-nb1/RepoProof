from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from repoproof.execution.product_action import ProductActionResultV2
from repoproof.persistence.product_incidents import (
    HarnessChangeEvidenceV1,
    IncidentRecordError,
    ProductIncidentV1,
    product_action_failure_incident,
    public_incident_fingerprint,
    scan_core_for_case_identifiers,
    write_harness_change_evidence,
    write_product_incident,
)

_SHA = "a" * 64
_COMMIT = "b" * 40


def _incident(**overrides) -> ProductIncidentV1:
    raw = {
        "incident_id": "incident-1",
        "framework_git_commit": _COMMIT,
        "framework_tree_sha256": _SHA,
        "profile_id": "workspace_bundle_v1",
        "task_version": "tool-example-v1",
        "stage": "AGENT_ADAPTER",
        "owner": "AGENT_ADAPTER",
        "normalized_fingerprint": "c" * 16,
        "public_failed_nodes": ("public::required-entry",),
        "reason_codes": ("WORKSPACE_REQUIRED_ENTRY_MISSING",),
        "artifact_tree_diff": {"missing": ["README.md"]},
        "agent_diff_present": True,
        "repair_eligible": True,
        "disposition": "REPAIR_AGENT",
        "created_at": "2026-08-31T00:00:00Z",
    }
    raw.update(overrides)
    return ProductIncidentV1.model_validate(raw)


def test_only_agent_adapter_incident_is_repairable() -> None:
    assert _incident().repair_eligible is True
    with pytest.raises(ValidationError, match="only AGENT_ADAPTER"):
        _incident(owner="HARNESS")
    terminal = _incident(
        repair_eligible=False,
        disposition="STOP_NEEDS_HUMAN",
    )
    assert terminal.owner == "AGENT_ADAPTER"
    assert terminal.repair_eligible is False
    with pytest.raises(ValidationError, match="requires an adapter diff"):
        _incident(agent_diff_present=False)
    with pytest.raises(ValidationError, match="requires public failed nodes"):
        _incident(public_failed_nodes=())


def test_public_fingerprint_redacts_paths_values_and_hashes() -> None:
    first = public_incident_fingerprint(
        stage="ARTIFACT_STRUCTURE",
        owner="AGENT_ADAPTER",
        reason_codes=["WORKSPACE_REQUIRED_ENTRY_MISSING"],
        public_failed_nodes=["/private/a/run-123/deadbeefcafebabe/node-7"],
    )
    second = public_incident_fingerprint(
        stage="ARTIFACT_STRUCTURE",
        owner="AGENT_ADAPTER",
        reason_codes=["WORKSPACE_REQUIRED_ENTRY_MISSING"],
        public_failed_nodes=["/other/b/run-999/0123456789abcdef/node-4"],
    )
    assert first == second
    assert len(first) == 16


def test_non_safety_change_needs_two_independent_incidents() -> None:
    base = {
        "evidence_id": "change-1",
        "invariant": "A successful action must publish a validated directory.",
        "anonymous_fixture_id": "anonymous-tree-1",
        "normalized_fingerprint": "c" * 16,
        "before_control_sha256": "1" * 64,
        "after_control_sha256": "2" * 64,
        "affected_component": "execution.workspace_bundle",
        "incident_ids": ("incident-1",),
        "regression_tests": ("test_anonymous_tree",),
        "case_identifier_scan_passed": True,
        "created_at": "2026-08-31T00:10:00Z",
    }
    with pytest.raises(ValidationError, match="two independent incidents"):
        HarnessChangeEvidenceV1.model_validate(base)
    accepted = HarnessChangeEvidenceV1.model_validate({
        **base,
        "incident_ids": ("incident-1", "incident-2"),
    })
    assert len(accepted.incident_ids) == 2


def test_false_success_change_may_use_first_incident_with_anonymous_control() -> None:
    evidence = HarnessChangeEvidenceV1(
        evidence_id="change-safe-1",
        invariant="REVOKED must never be presented as ACTIVE.",
        anonymous_fixture_id="anonymous-ledger-1",
        normalized_fingerprint="d" * 16,
        before_control_sha256="1" * 64,
        after_control_sha256="2" * 64,
        affected_component="runner.tool_registry",
        incident_ids=("incident-safe-1",),
        safety_or_false_success_exception=True,
        regression_tests=("test_revoked_is_not_active",),
        case_identifier_scan_passed=True,
        created_at="2026-08-31T00:10:00Z",
    )
    assert evidence.safety_or_false_success_exception is True


def test_incident_and_change_evidence_are_append_only(tmp_path: Path) -> None:
    incident = _incident()
    incident_root = tmp_path / "incidents"
    path = write_product_incident(incident_root, incident)
    assert json.loads(path.read_text(encoding="utf-8"))["incident_id"] == "incident-1"
    with pytest.raises(IncidentRecordError, match="already exists"):
        write_product_incident(tmp_path / "incidents", incident)

    evidence = HarnessChangeEvidenceV1(
        evidence_id="change-safe-1",
        invariant="No false success.",
        anonymous_fixture_id="anonymous-1",
        normalized_fingerprint=incident.normalized_fingerprint,
        before_control_sha256="1" * 64,
        after_control_sha256="2" * 64,
        affected_component="generic.component",
        incident_ids=("incident-1",),
        safety_or_false_success_exception=True,
        regression_tests=("test_control",),
        case_identifier_scan_passed=True,
        created_at="2026-08-31T00:10:00Z",
    )
    assert write_harness_change_evidence(
        tmp_path / "changes",
        evidence,
        incident_root=incident_root,
    ).is_file()


def test_change_writer_requires_real_matching_independent_incidents(
    tmp_path: Path,
) -> None:
    incident_root = tmp_path / "incidents"
    first = _incident(incident_id="incident-1", task_version="tool-one-v1")
    second = _incident(incident_id="incident-2", task_version="tool-two-v1")
    write_product_incident(incident_root, first)
    write_product_incident(incident_root, second)
    evidence = HarnessChangeEvidenceV1(
        evidence_id="change-two-task-control",
        invariant="A generic invariant failed in two independent tasks.",
        anonymous_fixture_id="anonymous-two-task-control",
        normalized_fingerprint=first.normalized_fingerprint,
        before_control_sha256="1" * 64,
        after_control_sha256="2" * 64,
        affected_component="generic.component",
        incident_ids=(first.incident_id, second.incident_id),
        regression_tests=("test_anonymous_control",),
        case_identifier_scan_passed=True,
        created_at="2026-08-31T00:10:00Z",
    )

    assert write_harness_change_evidence(
        tmp_path / "changes",
        evidence,
        incident_root=incident_root,
    ).is_file()

    same_task_root = tmp_path / "same-task-incidents"
    write_product_incident(same_task_root, first)
    write_product_incident(
        same_task_root,
        second.model_copy(update={"task_version": first.task_version}),
    )
    with pytest.raises(IncidentRecordError, match="independent task versions"):
        write_harness_change_evidence(
            tmp_path / "rejected-changes",
            evidence,
            incident_root=same_task_root,
        )

    mismatched_root = tmp_path / "mismatched-incidents"
    write_product_incident(mismatched_root, first)
    write_product_incident(
        mismatched_root,
        second.model_copy(update={"normalized_fingerprint": "d" * 16}),
    )
    with pytest.raises(IncidentRecordError, match="fingerprint"):
        write_harness_change_evidence(
            tmp_path / "rejected-fingerprint",
            evidence,
            incident_root=mismatched_root,
        )


def test_change_writer_accepts_two_independent_pre_task_contexts(
    tmp_path: Path,
) -> None:
    incident_root = tmp_path / "incidents"
    first = _incident(
        incident_id="incident-pre-task-1",
        task_version=None,
        stage="INTENT_ADMISSION",
        owner="HARNESS",
        pre_task_context_sha256="1" * 64,
        public_failed_nodes=("repository_analysis::optional-credential-reference",),
        reason_codes=("OPTIONAL_CREDENTIAL_REFERENCE_OVERCLASSIFIED",),
        agent_diff_present=False,
        repair_eligible=False,
        disposition="RECORD_PENDING_SECOND_INCIDENT",
    )
    second = first.model_copy(
        update={
            "incident_id": "incident-pre-task-2",
            "pre_task_context_sha256": "2" * 64,
        }
    )
    write_product_incident(incident_root, first)
    write_product_incident(incident_root, second)
    evidence = HarnessChangeEvidenceV1(
        evidence_id="change-two-pre-task-contexts",
        invariant="Two independent pre-task contexts must support generic evidence.",
        anonymous_fixture_id="anonymous-pre-task-contexts",
        normalized_fingerprint=first.normalized_fingerprint,
        before_control_sha256="3" * 64,
        after_control_sha256="4" * 64,
        affected_component="generic.admission",
        incident_ids=(first.incident_id, second.incident_id),
        regression_tests=(
            "test_change_writer_accepts_two_independent_pre_task_contexts",
        ),
        case_identifier_scan_passed=True,
        created_at="2026-08-31T00:10:00Z",
    )

    assert write_harness_change_evidence(
        tmp_path / "changes",
        evidence,
        incident_root=incident_root,
    ).is_file()


def test_case_identifier_scan_is_limited_to_core_python(tmp_path: Path) -> None:
    source = tmp_path / "src" / "repoproof"
    source.mkdir(parents=True)
    (source / "generic.py").write_text("PROFILE = 'workspace_bundle_v1'\n", encoding="utf-8")
    nested = source / "nested"
    nested.mkdir()
    (nested / "bad.py").write_text("CASE = 'special-repository'\n", encoding="utf-8")
    (source / "notes.md").write_text("special-repository", encoding="utf-8")

    assert scan_core_for_case_identifiers(source, ["special-repository"]) == [
        "nested/bad.py"
    ]


@pytest.mark.parametrize(
    ("action", "owner", "reason", "expected_stage", "expected_disposition"),
    [
        ("tool-add", "USER_INPUT", "ADMISSION_UNSUPPORTED", "INTENT_ADMISSION", "UNSUPPORTED"),
        ("tool-build", "HARNESS", "UPSTREAM_IMPORT_FAILED", "PREFLIGHT_UPSTREAM", "RETRY_INFRASTRUCTURE"),
        ("tool-build", "AGENT_ADAPTER", "WORKSPACE_REQUIRED_ENTRY_MISSING", "ARTIFACT_STRUCTURE", "STOP_NEEDS_HUMAN"),
        ("tool-build", "PACKAGE", "CLEAN_REPLAY_DRIFT", "CLEAN_REPLAY", "RETRY_INFRASTRUCTURE"),
        ("tool-audit", "VERIFICATION", "SEMANTIC_MISMATCH", "SEMANTIC_VERIFIER", "STOP_NEEDS_HUMAN"),
    ],
)
def test_failed_workspace_action_has_one_public_incident_stage(
    action: str,
    owner: str,
    reason: str,
    expected_stage: str,
    expected_disposition: str,
) -> None:
    result = ProductActionResultV2(
        job_id=f"job-{action}",
        journey_id="journey-one",
        action=action,
        ok=False,
        task_id="tool-anonymous-v1",
        product_stop_code="STOP_NEEDS_HUMAN",
        failure_owner=owner,
        reason_codes=[reason],
        recommended_action="Follow the typed next action.",
        delivery_profile_id="workspace_bundle_v1",
        artifact_kind="directory",
    )

    incident = product_action_failure_incident(
        result,
        framework_git_commit=_COMMIT,
        framework_tree_sha256=_SHA,
    )

    assert incident.stage == expected_stage
    assert incident.disposition == expected_disposition
    assert incident.repair_eligible is False
    assert incident.agent_diff_present is False
    assert reason in incident.reason_codes
    assert "Follow the typed next action." not in json.dumps(incident.model_dump())
