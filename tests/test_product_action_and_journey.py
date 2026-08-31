"""M6.1 structured action result and recoverable journey contracts."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from repoproof import cli
from repoproof.execution.product_action import (
    ProductActionResultV1,
    ProductActionResultV2,
    action_result_from_payload,
    read_product_action_result,
    workspace_action_result_from_payload,
    write_product_action_result,
)
from repoproof.ui.services import product_jobs, product_journeys, product_mode


def test_build_action_result_keeps_process_and_pipeline_semantics_separate(
    tmp_path: Path,
) -> None:
    result = action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-build",
        ok=False,
        payload={
            "ok": False,
            "task_id": "tool-demo-v1",
            "verdict": "BLOCKED",
            "stages": {
                "route": {"route": "AGENT_ADAPT", "agent_invoked": True},
                "real": {
                    "run_id": "run-1",
                    "product_stop_code": "STOP_HARNESS_OR_EXTERNAL",
                    "failure_assessment": {
                        "failure_owner": "HARNESS",
                        "reason_codes": ["UPSTREAM_WHEEL_MISSING"],
                        "recommended_action": "RETRY_INFRASTRUCTURE",
                    },
                },
            },
        },
    )
    assert result.pipeline_verdict == "BLOCKED"
    assert result.product_stop_code == "STOP_HARNESS_OR_EXTERNAL"
    assert result.failure_owner == "HARNESS"
    assert result.reason_codes == ["UPSTREAM_WHEEL_MISSING"]

    path = write_product_action_result(tmp_path / "result.json", result)
    assert read_product_action_result(path) == result


def test_provider_preflight_failure_preserves_owner_and_zero_agent_calls() -> None:
    result = action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-build-real",
        ok=False,
        payload={
            "ok": False,
            "task_id": "tool-demo-v1",
            "verdict": "REAL_BLOCKED",
            "stages": {
                "route": {"route": "AGENT_ADAPT", "agent_invoked": True},
                "real": {
                    "blocked": True,
                    "preflight": {"status": "PROVIDER_UNAVAILABLE"},
                    "agent_model_call_count": 0,
                },
            },
        },
    )

    assert result.failure_owner == "EXTERNAL"
    assert result.reason_codes == ["PROVIDER_UNAVAILABLE"]
    assert result.product_stop_code == "STOP_HARNESS_OR_EXTERNAL"
    assert result.recommended_action == "模型服务恢复后重试；本次未进入 Agent repair。"
    assert result.agent_invoked is False


def test_provider_configuration_failure_is_harness_owned() -> None:
    result = action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-build-real",
        ok=False,
        payload={
            "verdict": "REAL_BLOCKED",
            "stages": {
                "real": {
                    "blocked": True,
                    "preflight": {"status": "AUTH_FAILED"},
                    "agent_model_call_count": 0,
                }
            },
        },
    )

    assert result.failure_owner == "HARNESS"
    assert result.reason_codes == ["AUTH_FAILED"]
    assert result.agent_invoked is False


def test_answer_key_preflight_reason_is_not_collapsed_to_generic_failure() -> None:
    result = action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-build-real",
        ok=False,
        payload={
            "verdict": "REAL_BLOCKED",
            "stages": {
                "real": {
                    "blocked": True,
                    "agent_model_call_count": 0,
                    "preflight": {
                        "ready": False,
                        "reason": "ANSWER_KEY_REACHABLE",
                    },
                    "remediation": "Remove reachable engineering answers before retrying.",
                }
            },
        },
    )

    assert result.failure_owner == "HARNESS"
    assert result.reason_codes == ["ANSWER_KEY_REACHABLE"]
    assert result.product_stop_code == "STOP_HARNESS_OR_EXTERNAL"
    assert result.recommended_action == (
        "Remove reachable engineering answers before retrying."
    )
    assert result.agent_invoked is False


def test_exported_build_result_derives_tool_name_for_fresh_core_projection() -> None:
    result = action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-build-real",
        ok=True,
        payload={
            "ok": True,
            "task_id": "tool-markdown-it-py-tool-v2",
            "exported": "/managed/tools/markdown-it-py-tool",
            "verdict": "VERIFIED_TOOL_READY",
        },
    )

    assert result.tool_name == "markdown-it-py-tool"
    assert result.recorded_operational_status is None


@pytest.mark.parametrize(
    ("reason_code", "owner", "failure_class", "retry_policy", "action_code"),
    [
        (
            "DRAFTER_TIMEOUT",
            "EXTERNAL",
            "PROVIDER_TRANSPORT",
            "RETRY_AFTER_PROVIDER_RECOVERY",
            "RETRY_DRAFT_AFTER_PROVIDER_RECOVERY",
        ),
        (
            "DRAFTER_CONNECTIVITY_ERROR",
            "EXTERNAL",
            "PROVIDER_TRANSPORT",
            "RETRY_AFTER_PROVIDER_RECOVERY",
            "RETRY_DRAFT_AFTER_PROVIDER_RECOVERY",
        ),
        (
            "DRAFTER_STRUCTURED_OUTPUT_UNSUPPORTED",
            "EXTERNAL",
            "PROVIDER_CAPABILITY",
            "RETRY_AFTER_CONFIGURATION_REPAIR",
            "CONFIGURE_STRUCTURED_DRAFTER",
        ),
        (
            "DRAFTER_TIMEOUT_CONFIG_INVALID",
            "HARNESS",
            "HARNESS_CONFIGURATION",
            "RETRY_AFTER_CONFIGURATION_REPAIR",
            "REPAIR_DRAFTER_CONFIGURATION",
        ),
    ],
)
def test_tool_add_preserves_typed_drafter_failure(
    reason_code: str,
    owner: str,
    failure_class: str,
    retry_policy: str,
    action_code: str,
) -> None:
    result = action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-add",
        ok=False,
        payload={"ok": False, "draft_error": reason_code},
    )

    assert result.reason_codes == [reason_code]
    assert result.failure_owner == owner
    assert result.failure_stage == "DRAFTING"
    assert result.failure_class == failure_class
    assert result.retry_policy == retry_policy
    assert result.requires_new_task_version is False
    assert result.recommended_action_code == action_code
    assert result.product_stop_code == "STOP_HARNESS_OR_EXTERNAL"


def test_tool_add_preserves_specific_intent_admission_reason() -> None:
    result = action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-add",
        ok=False,
        payload={
            "ok": False,
            "admission": {
                "status": "UNSUPPORTED",
                "reason_codes": [
                    "UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT"
                ],
                "next_step": "Use an offline workflow without credentials.",
            },
        },
    )

    assert result.reason_codes == [
        "UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT"
    ]
    assert result.failure_owner == "USER_INPUT"
    assert result.failure_stage == "INTAKE"
    assert result.agent_invoked is False
    assert result.recommended_action == "Use an offline workflow without credentials."


def test_audit_build_failure_is_harness_owned_not_agent_repair() -> None:
    result = action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-audit",
        ok=False,
        payload={
            "ok": False,
            "decision": "REVOKED",
            "reason_code": "BUILD_FAILED",
            "failure_owner": "HARNESS",
            "failure_stage": "BUILD",
            "failure_class": "HARNESS_ENVIRONMENT",
            "retry_policy": "RETRY_AFTER_ENVIRONMENT_REPAIR",
            "requires_new_task_version": False,
            "recommended_action_code": "REPAIR_BUILD_ENVIRONMENT",
            "recommended_action": "Repair the build environment and retry.",
            "product_stop_code": "STOP_HARNESS_OR_EXTERNAL",
        },
    )

    assert result.failure_owner == "HARNESS"
    assert result.failure_stage == "BUILD"
    assert result.failure_class == "HARNESS_ENVIRONMENT"
    assert result.retry_policy == "RETRY_AFTER_ENVIRONMENT_REPAIR"
    assert result.requires_new_task_version is False
    assert result.recommended_action_code == "REPAIR_BUILD_ENVIRONMENT"
    assert result.product_stop_code == "STOP_HARNESS_OR_EXTERNAL"
    assert result.reason_codes == ["BUILD_FAILED"]
    assert result.recommended_action == "Repair the build environment and retry."


def test_legacy_audit_reason_code_is_not_reverse_mapped_to_remediation() -> None:
    result = action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-audit",
        ok=False,
        payload={
            "ok": False,
            "decision": "REVOKED",
            "reason_code": "SEMANTIC_VERIFIER_MISMATCH",
        },
    )

    assert result.reason_codes == ["SEMANTIC_VERIFIER_MISMATCH"]
    assert result.failure_class is None
    assert result.retry_policy is None
    assert result.requires_new_task_version is None
    assert result.recommended_action_code is None
    assert "typed failure metadata" in str(result.recommended_action)
    assert "修复适配器" not in str(result.recommended_action)


def test_studio_fresh_audit_rebuilds_export_before_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "fresh.md"
    expected_path = tmp_path / "fresh.expected.json"
    input_path.write_text("# Fresh\n", encoding="utf-8")
    expected_path.write_text('{"headings":[]}\n', encoding="utf-8")
    tool_dir = tmp_path / "tools" / "markdown-it-py-tool"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.json").write_text(
        json.dumps({"contract_schema_version": 3}), encoding="utf-8"
    )
    captured: dict = {}

    def _capture(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(product_jobs, "_start_product_job", _capture)
    result = product_jobs.start_tool_audit(
        "markdown-it-py-tool",
        input_path,
        expected_path,
        tmp_path / "tools",
        expected_task_id="tool-markdown-it-py-tool-v1",
        journey_id="journey-1",
    )

    assert result["ok"] is True
    assert "--build" in captured["argv"]
    expected_task_index = captured["argv"].index("--expected-task-id")
    assert captured["argv"][expected_task_index + 1] == "tool-markdown-it-py-tool-v1"
    assert captured["argv"].index("--build") > captured["argv"].index("--dest-root")
    assert captured["kwargs"]["kind"] == "tool-audit"
    assert captured["kwargs"]["metadata"]["task_id"] == "tool-markdown-it-py-tool-v1"


def test_action_result_rejects_unknown_schema(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    payload = ProductActionResultV1(
        job_id="a" * 32, action="tool-add", ok=True
    ).model_dump(mode="json")
    payload["schema_version"] = 2
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="ProductActionResultV1"):
        read_product_action_result(path)


def test_workspace_action_result_v2_round_trip(tmp_path: Path) -> None:
    result = workspace_action_result_from_payload(
        job_id="a" * 32,
        journey_id="b" * 32,
        action="tool-build-real",
        ok=True,
        payload={
            "ok": True,
            "task_id": "tool-workspace-demo-v1",
            "verdict": "VERIFIED_TOOL_READY",
        },
        artifact_root=tmp_path / "workspace",
        artifact_tree_sha256="1" * 64,
        artifact_manifest_sha256="2" * 64,
        workspace_structure_passed=True,
    )

    assert isinstance(result, ProductActionResultV2)
    assert result.delivery_profile_id == "workspace_bundle_v1"
    assert result.artifact_kind == "directory"
    assert result.artifacts["workspace_bundle"] == str(
        (tmp_path / "workspace").resolve()
    )
    path = write_product_action_result(tmp_path / "workspace-result.json", result)
    assert read_product_action_result(path) == result


def test_workspace_build_may_precede_user_artifact_evidence() -> None:
    result = ProductActionResultV2(
        job_id="a" * 32,
        action="tool-build-real",
        ok=True,
        delivery_profile_id="workspace_bundle_v1",
        artifact_kind="directory",
    )
    assert result.artifact_tree_sha256 is None


def test_workspace_evidence_cannot_be_partial() -> None:
    with pytest.raises(ValueError, match="requires both tree and manifest"):
        ProductActionResultV2(
            job_id="a" * 32,
            action="tool-audit",
            ok=True,
            delivery_profile_id="workspace_bundle_v1",
            artifact_kind="directory",
            artifact_tree_sha256="1" * 64,
        )


def test_workspace_cli_failure_writes_result_and_append_only_incident(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    (project / "src" / "repoproof").mkdir(parents=True)
    (project / "src" / "repoproof" / "module.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    contracts = project / "contracts"
    contracts.mkdir()
    (contracts / "tool-anonymous-v1.yaml").write_text(
        "tool:\n  delivery_profile_id: workspace_bundle_v1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(
        ["git", "-C", str(project), "config", "user.email", "test@local"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project), "config", "user.name", "RepoProof Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-q", "-m", "fixture"],
        check=True,
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", project)
    result_path = tmp_path / "result.json"
    args = argparse.Namespace(
        result_json=result_path,
        job_id="job-workspace-failure",
        journey_id="journey-one",
    )

    exit_code = cli._emit_tool_action(
        args,
        action="tool-build",
        payload={
            "ok": False,
            "task_id": "tool-anonymous-v1",
            "verdict": "BLOCKED",
            "failure_owner": "HARNESS",
            "reason_codes": ["UPSTREAM_IMPORT_FAILED"],
            "product_stop_code": "STOP_HARNESS_OR_EXTERNAL",
            "recommended_action": "Repair the environment.",
        },
        exit_code=3,
    )

    assert exit_code == 3
    assert read_product_action_result(result_path).ok is False
    incident_paths = list((project / "runs" / "product-incidents").glob("*.json"))
    assert len(incident_paths) == 1
    incident = json.loads(incident_paths[0].read_text(encoding="utf-8"))
    assert incident["stage"] == "PREFLIGHT_UPSTREAM"
    assert incident["owner"] == "HARNESS"
    assert incident["reason_codes"] == [
        "STOP_HARNESS_OR_EXTERNAL",
        "UPSTREAM_IMPORT_FAILED",
    ]
    assert "Repair the environment." not in json.dumps(incident)


def test_failed_workspace_action_may_have_no_artifact() -> None:
    result = ProductActionResultV2(
        job_id="a" * 32,
        action="tool-build-real",
        ok=False,
        delivery_profile_id="workspace_bundle_v1",
        artifact_kind="directory",
        product_stop_code="STOP_HARNESS_OR_EXTERNAL",
    )
    assert result.artifact_root is None


def test_job_result_is_bound_to_job_id_and_managed_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = (tmp_path / "state").resolve()
    result_dir = state / "job-results"
    result_dir.mkdir(parents=True)
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    path = result_dir / "result.json"
    write_product_action_result(
        path,
        ProductActionResultV1(job_id="a" * 32, action="tool-add", ok=True),
    )
    job = {"job_id": "b" * 32, "result_json": str(path)}
    got = product_jobs.product_job_action_result(job)
    assert got["ok"] is False
    assert got["error_code"] == "ACTION_RESULT_JOB_MISMATCH"


def test_journey_round_trip_and_restart_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
    monkeypatch.setattr(product_journeys, "ui_state_root", lambda: state)
    first = product_journeys.create_journey(
        source_repo_url="https://github.com/acme/demo",
        draft_dir=state / "drafts" / "demo",
        dest_root=tmp_path / "tools",
    )
    updated = product_journeys.update_journey(
        first.journey_id,
        tool_name="demo-tool",
        task_id="tool-demo-tool-v1",
        last_job_id="c" * 32,
    )
    assert updated.created_at == first.created_at
    assert first.agent_backend == "mini-swe"
    loaded = product_journeys.read_journey(first.journey_id)
    assert loaded.tool_name == "demo-tool"
    assert loaded.task_id == "tool-demo-tool-v1"
    assert product_journeys.list_journeys()[0].journey_id == first.journey_id


def test_unfrozen_legacy_draft_is_read_only_incompatible_not_current_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = (tmp_path / "state").resolve()
    tools = tmp_path / "tools"
    tools.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    draft_dir = state / "drafts" / "legacy"
    draft_dir.mkdir(parents=True)
    (draft_dir / "examples").mkdir()
    (draft_dir / "draft.yaml").write_text(
        "tool:\n  name: legacy-tool\n",
        encoding="utf-8",
    )
    (draft_dir / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft_dir / "reference_impl.py").write_text("import legacy\n", encoding="utf-8")
    monkeypatch.setattr(product_journeys, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_jobs, "product_job_state", lambda: {})
    monkeypatch.setattr(product_mode, "project_root", lambda: project)
    monkeypatch.setattr(
        product_mode,
        "list_tools",
        lambda *_args, **_kwargs: {"tools": [], "projection_errors": []},
    )
    journey = product_journeys.create_journey(
        source_repo_url="https://github.com/acme/legacy",
        draft_dir=draft_dir,
        dest_root=tools,
    )

    snapshot = product_journeys.journey_snapshot(journey)

    assert snapshot["phase"] == "DRAFT_INCOMPATIBLE"
    readiness = snapshot["draft_review"]["draft_readiness"]
    assert readiness["compatible"] is False
    assert readiness["current"] is False
    assert "TOOL_SPEC_VERSION_NOT_CURRENT" in readiness["reason_codes"]
    assert "INTENT_CONTRACT_MISSING" in readiness["reason_codes"]


def test_journey_symlink_root_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "outside"
    target.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (state / "journeys").symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(product_journeys, "ui_state_root", lambda: state)
    with pytest.raises(OSError, match="不安全"):
        product_journeys.create_journey(
            source_repo_url="https://github.com/acme/demo",
            draft_dir=state / "drafts" / "demo",
            dest_root=tmp_path / "tools",
        )


def test_terminal_job_without_result_makes_journey_semantically_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    tools = tmp_path / "tools"
    tools.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(product_journeys, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_mode, "project_root", lambda: project)
    monkeypatch.setattr(
        product_jobs,
        "product_job_state",
        lambda: {"job_id": "d" * 32, "status": "FAILED"},
    )
    journey = product_journeys.create_journey(
        source_repo_url="https://github.com/acme/demo",
        draft_dir=state / "drafts" / "demo",
        dest_root=tools,
    )
    journey = product_journeys.update_journey(
        journey.journey_id, last_job_id="d" * 32
    )

    snapshot = product_journeys.journey_snapshot(journey)
    assert snapshot["phase"] == "SEMANTIC_UNKNOWN"
    assert snapshot["semantic_error"] == "ACTION_RESULT_MISSING"
