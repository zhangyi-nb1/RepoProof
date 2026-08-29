"""M6.1 structured action result and recoverable journey contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.execution.product_action import (
    ProductActionResultV1,
    action_result_from_payload,
    read_product_action_result,
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
        },
    )

    assert result.failure_owner == "HARNESS"
    assert result.product_stop_code == "STOP_HARNESS_OR_EXTERNAL"
    assert result.reason_codes == ["BUILD_FAILED"]
    assert "Agent repair" in str(result.recommended_action)


def test_studio_fresh_audit_rebuilds_export_before_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "fresh.md"
    expected_path = tmp_path / "fresh.expected.json"
    input_path.write_text("# Fresh\n", encoding="utf-8")
    expected_path.write_text('{"headings":[]}\n', encoding="utf-8")
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


def test_job_result_is_bound_to_job_id_and_managed_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"
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
    loaded = product_journeys.read_journey(first.journey_id)
    assert loaded.tool_name == "demo-tool"
    assert loaded.task_id == "tool-demo-tool-v1"
    assert product_journeys.list_journeys()[0].journey_id == first.journey_id


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
