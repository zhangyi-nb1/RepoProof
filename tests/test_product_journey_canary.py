"""Zero-model canaries for the recoverable Product Journey state machine."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from repoproof.execution.product_action import (
    ProductActionResultV1,
    write_product_action_result,
)
from repoproof.runner import tool_registry
from repoproof.runner.tool_release import append_release_decision
from repoproof.ui.services import product_jobs, product_journeys, product_mode


def _configure_roots(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    state = tmp_path / "state"
    project = tmp_path / "project"
    tools = tmp_path / "tools"
    (project / "contracts").mkdir(parents=True)
    tools.mkdir()
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_journeys, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_mode, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_mode, "project_root", lambda: project)
    monkeypatch.setattr(product_mode, "tool_root", lambda: tools)
    return state, project, tools


def _write_draft(draft: Path) -> None:
    (draft / "examples" / "inputs").mkdir(parents=True)
    (draft / "examples" / "expected").mkdir()
    (draft / "draft.yaml").write_text(
        yaml.safe_dump({
            "tool": {
                "name": "alpha-tool",
                "summary": "Alpha",
                "interface": {
                    "input": {"format": "TXT"},
                    "output": {
                        "format": "TEXT",
                        "contract": {
                            "media_type": "text/plain",
                            "root_type": "text",
                            "required": {},
                        },
                    },
                },
            },
            "capability": {"statement": "Alpha", "output_schema": "AlphaText"},
        }),
        encoding="utf-8",
    )
    (draft / "reference_impl.py").write_text("# reference\n", encoding="utf-8")
    examples = []
    for index in range(3):
        input_name = f"case-{index}.txt"
        output_name = f"case-{index}.expected.txt"
        (draft / "examples" / "inputs" / input_name).write_text("a", encoding="utf-8")
        (draft / "examples" / "expected" / output_name).write_text("A", encoding="utf-8")
        examples.append({
            "input_file": f"inputs/{input_name}",
            "expected_file": f"expected/{output_name}",
        })
    (draft / "examples.yaml").write_text(
        yaml.safe_dump({"examples": examples}), encoding="utf-8"
    )


def _write_result(state: Path, result: ProductActionResultV1) -> None:
    write_product_action_result(
        state / "job-results" / f"{result.job_id}.json", result
    )


def _export_ready_tool(tools: Path) -> tuple[str, str]:
    task_id = "tool-alpha-tool-v1"
    run_id = f"{task_id}-20260829-000000"
    package = tools / "alpha-tool"
    (package / "evidence").mkdir(parents=True)
    contract_hash = "b" * 64
    manifest = {
        "name": "alpha-tool",
        "summary": "Alpha",
        "source": {
            "url": "https://github.com/acme/alpha",
            "distribution": "alpha",
            "resolved_commit": "a" * 40,
        },
        "verification": {
            "verdict": "VERIFIED_TOOL_READY",
            "run_id": run_id,
            "contract_sha256": contract_hash,
        },
    }
    (package / "tool.json").write_text(json.dumps(manifest), encoding="utf-8")
    (package / "evidence" / "provenance.json").write_text(
        json.dumps({
            "tool": "alpha-tool",
            "task_id": task_id,
            "run_id": run_id,
            "tool_contract_sha256": contract_hash,
        }),
        encoding="utf-8",
    )
    tool_registry.register_tool(
        tools, package, run_id=run_id, exported_at="2026-08-29T00:00:00Z"
    )
    return task_id, run_id


def test_zero_model_full_journey_reaches_active(tmp_path: Path, monkeypatch) -> None:
    state, project, tools = _configure_roots(tmp_path, monkeypatch)
    draft = state / "drafts" / "alpha"
    journey = product_journeys.create_journey(
        source_repo_url="https://github.com/acme/alpha",
        draft_dir=draft,
        dest_root=tools,
    )
    _write_draft(draft)
    assert product_journeys.journey_snapshot(journey)["phase"] == "DRAFT"

    task_id = "tool-alpha-tool-v1"
    (project / "contracts" / f"{task_id}.yaml").write_text(
        f"task_id: {task_id}\n", encoding="utf-8"
    )
    rehearsal_job = "1" * 32
    _write_result(state, ProductActionResultV1(
        job_id=rehearsal_job,
        journey_id=journey.journey_id,
        action="tool-build",
        ok=True,
        tool_name="alpha-tool",
        task_id=task_id,
        pipeline_verdict="REHEARSAL_PASS_ONLY",
        agent_invoked=False,
    ))
    journey = product_journeys.update_journey(
        journey.journey_id, task_id=task_id, tool_name="alpha-tool",
        last_job_id=rehearsal_job,
    )
    archived = project / "tool_tasks" / "_drafts" / task_id
    archived.parent.mkdir(parents=True)
    draft.rename(archived)
    assert product_journeys.journey_snapshot(journey)["phase"] == "REHEARSED"

    task_id, run_id = _export_ready_tool(tools)
    build_job = "2" * 32
    _write_result(state, ProductActionResultV1(
        job_id=build_job,
        journey_id=journey.journey_id,
        action="tool-build-real",
        ok=True,
        tool_name="alpha-tool",
        task_id=task_id,
        run_id=run_id,
        pipeline_verdict="VERIFIED_TOOL_READY",
        historical_verdict="VERIFIED_TOOL_READY",
        exported_path=str(tools / "alpha-tool"),
        agent_invoked=True,
    ))
    journey = product_journeys.update_journey(journey.journey_id, last_job_id=build_job)
    exported = product_journeys.journey_snapshot(journey)
    assert exported["phase"] == "EXPORTED"
    assert exported["operational_status"] == "REVIEW_REQUIRED"

    append_release_decision(
        tools,
        tool="alpha-tool",
        task_id=task_id,
        run_id=run_id,
        decision="ACTIVE",
        reason_code="FRESH_INPUT_PASS",
        reason="Fresh audit passed.",
        evidence_sha256="c" * 64,
        actor="operator",
    )
    assert product_journeys.journey_snapshot(journey)["phase"] == "ACTIVE"


def test_new_same_name_draft_does_not_inherit_old_task_release_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _state, _project, tools = _configure_roots(tmp_path, monkeypatch)
    old_task_id, old_run_id = _export_ready_tool(tools)
    append_release_decision(
        tools,
        tool="alpha-tool",
        task_id=old_task_id,
        run_id=old_run_id,
        decision="REVOKED",
        reason_code="FRESH_INPUT_MISMATCH",
        reason="Old version failed a fresh audit.",
        evidence_sha256="e" * 64,
        actor="operator",
    )
    draft = _state / "drafts" / "alpha-v2"
    _write_draft(draft)
    journey = product_journeys.create_journey(
        source_repo_url="https://github.com/acme/alpha",
        draft_dir=draft,
        dest_root=tools,
        tool_name="alpha-tool",
    )

    snapshot = product_journeys.journey_snapshot(journey)

    assert snapshot["task_id"] is None
    assert snapshot["phase"] == "DRAFT"
    assert snapshot["operational_status"] == "UNVERIFIED"
    assert snapshot["tool"] is None


def test_failure_canaries_are_fail_closed(tmp_path: Path, monkeypatch) -> None:
    state, _project, tools = _configure_roots(tmp_path, monkeypatch)
    journey = product_journeys.create_journey(
        source_repo_url="https://github.com/acme/alpha",
        draft_dir=state / "drafts" / "alpha",
        dest_root=tools,
    )
    blocked_job = "3" * 32
    _write_result(state, ProductActionResultV1(
        job_id=blocked_job,
        journey_id=journey.journey_id,
        action="tool-build",
        ok=False,
        pipeline_verdict="BLOCKED",
        product_stop_code="STOP_HARNESS_OR_EXTERNAL",
        failure_owner="HARNESS",
        reason_codes=["UPSTREAM_WHEEL_MISSING"],
        agent_invoked=False,
    ))
    journey = product_journeys.update_journey(journey.journey_id, last_job_id=blocked_job)
    snapshot = product_journeys.journey_snapshot(journey)
    assert snapshot["phase"] == "FAILED"
    assert snapshot["operational_status"] == "UNVERIFIED"

    task_id, run_id = _export_ready_tool(tools)
    append_release_decision(
        tools,
        tool="alpha-tool",
        task_id=task_id,
        run_id=run_id,
        decision="REVOKED",
        reason_code="FRESH_INPUT_MISMATCH",
        reason="Fresh audit output differed.",
        evidence_sha256="d" * 64,
        actor="operator",
    )
    journey = product_journeys.update_journey(
        journey.journey_id, tool_name="alpha-tool", task_id=task_id
    )
    revoked = product_journeys.journey_snapshot(journey)
    assert revoked["phase"] == "EXPORTED"
    assert revoked["operational_status"] == "REVOKED"


def test_legacy_tool_is_synthesized_read_only_without_backfill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _state, _project, tools = _configure_roots(tmp_path, monkeypatch)
    _export_ready_tool(tools)

    cards = product_journeys.synthesized_read_only_cards()
    assert cards[0]["read_only"] is True
    assert cards[0]["phase"] == "EXPORTED"
    assert product_journeys.list_journeys() == []
