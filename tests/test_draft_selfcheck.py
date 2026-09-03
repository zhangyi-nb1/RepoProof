"""起草自检报告与 readiness 绑定(incident-draft-controls-unverified-*)。

不变量:
  I1 机器起草的 workspace 草稿在冻结前必须有一份**当前**的自检报告
     (绑定语义指纹 + builder/blueprints/reference/verifier 四件字节);任一
     控制件改动即失效(STALE),报告失败即 FAILED,缺失即 MISSING;
  I2 自检状态只阻塞 ready(冻结),不阻塞 ready_to_confirm(人仍可审阅确认);
  I3 人工手写的草稿(无 draft_meta.json)与非 workspace 草稿不适用;
  I4 修复目标按公开失败码确定性路由:builder / reference / verifier,
     reference↔verifier 分歧首轮修 verifier、次轮修 reference,系统性故障不修。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from repoproof.adoption.intake.draft_readiness import evaluate_draft_readiness
from repoproof.adoption.intake.draft_selfcheck import (
    DraftControlBindingV1,
    DraftSelfCheckReportV1,
    DraftSelfCheckRoundV1,
    draft_control_binding,
    read_draft_self_check,
    repair_target_for,
    self_check_status,
    write_draft_self_check,
)


def _draft_dir(tmp_path: Path, *, machine_drafted: bool = True, workspace: bool = True) -> tuple[Path, dict]:
    draft_dir = tmp_path / "draft"
    draft_dir.mkdir(parents=True)
    draft = {
        "task_id": "tool-anon-v1",
        "tool": {
            "name": "anon",
            "schema_version": 4 if workspace else 3,
            "delivery_profile_id": "workspace_bundle_v1" if workspace else None,
        },
        "_delivery_profile": {
            "schema_version": 1,
            "profile_id": "workspace_bundle_v1" if workspace else "cli_v2",
        },
        "_intent_contract": {
            "schema_version": 1,
            "user_goal": "anonymous goal",
            "commitments": [],
            "confirmation": None,
        },
    }
    (draft_dir / "draft.yaml").write_text(yaml.safe_dump(draft, allow_unicode=True), encoding="utf-8")
    (draft_dir / "fixture_builder.py").write_text("def build(blueprint, output_path):\n    pass\n", encoding="utf-8")
    (draft_dir / "fixture_blueprints.json").write_text('{"blueprints": []}\n', encoding="utf-8")
    (draft_dir / "reference_impl.py").write_text("def build_workspace(i, o):\n    pass\n", encoding="utf-8")
    (draft_dir / "semantic_verifier.py").write_text("def verify(i, a):\n    return {'ok': True}\n", encoding="utf-8")
    if machine_drafted:
        (draft_dir / "draft_meta.json").write_text('{"drafter": "anonymous-drafter"}\n', encoding="utf-8")
    return draft_dir, draft


def _report(binding: DraftControlBindingV1, *, ok: bool) -> DraftSelfCheckReportV1:
    return DraftSelfCheckReportV1(
        ok=ok,
        drafter="anonymous-drafter",
        rounds=(DraftSelfCheckRoundV1(round=1, check_ok=ok, reason_codes=() if ok else ("X",), candidate_count=3),),
        bound=binding,
        final_reason_codes=() if ok else ("X",),
        recommended_action="",
        created_at="2026-09-02T00:00:00Z",
    )


def test_binding_tracks_every_control_file_and_semantics(tmp_path: Path) -> None:
    draft_dir, draft = _draft_dir(tmp_path)
    before = draft_control_binding(draft, draft_dir)
    assert all(len(value) == 64 for value in before.model_dump().values())
    (draft_dir / "semantic_verifier.py").write_text("def verify(i, a):\n    return {'ok': False}\n", encoding="utf-8")
    after = draft_control_binding(draft, draft_dir)
    assert after.semantic_verifier_sha256 != before.semantic_verifier_sha256
    assert after.reference_sha256 == before.reference_sha256


def test_status_transitions_missing_passed_stale_failed(tmp_path: Path) -> None:
    draft_dir, draft = _draft_dir(tmp_path)
    assert self_check_status(draft, draft_dir) == "MISSING"
    write_draft_self_check(draft_dir, _report(draft_control_binding(draft, draft_dir), ok=True))
    assert read_draft_self_check(draft_dir) is not None
    assert self_check_status(draft, draft_dir) == "PASSED"
    (draft_dir / "fixture_builder.py").write_text(
        "def build(blueprint, output_path):\n    return 1\n", encoding="utf-8"
    )
    assert self_check_status(draft, draft_dir) == "STALE"
    write_draft_self_check(draft_dir, _report(draft_control_binding(draft, draft_dir), ok=False))
    assert self_check_status(draft, draft_dir) == "FAILED"


def test_status_not_applicable_for_hand_authored_or_cli_drafts(tmp_path: Path) -> None:
    hand_dir, hand = _draft_dir(tmp_path / "hand", machine_drafted=False)
    assert self_check_status(hand, hand_dir) == "NOT_APPLICABLE"
    cli_dir, cli = _draft_dir(tmp_path / "cli", workspace=False)
    assert self_check_status(cli, cli_dir) == "NOT_APPLICABLE"


def test_readiness_reports_self_check_without_blocking_confirmation(tmp_path: Path) -> None:
    draft_dir, draft = _draft_dir(tmp_path)
    readiness = evaluate_draft_readiness(draft, draft_dir)
    assert "DRAFT_SELF_CHECK_MISSING" in readiness.reason_codes
    assert readiness.public_summary.draft_self_check == "MISSING"
    assert readiness.ready is False
    # 自检缺失是「冻结前」问题:它不能成为阻塞人审阅/确认的原因之一。
    from repoproof.adoption.intake import draft_readiness as module

    evaluation = module._evaluate(draft, draft_dir, project_root=None)
    issue = next(item for item in evaluation.issues if item.code == "DRAFT_SELF_CHECK_MISSING")
    assert issue.confirmation_only is True
    write_draft_self_check(draft_dir, _report(draft_control_binding(draft, draft_dir), ok=True))
    passed = evaluate_draft_readiness(draft, draft_dir)
    assert not any(code.startswith("DRAFT_SELF_CHECK_") for code in passed.reason_codes)
    assert passed.public_summary.draft_self_check == "PASSED"


def test_repair_target_routing_is_deterministic() -> None:
    assert repair_target_for("FIXTURE_BUILDER_FAILED", round_index=1) == "builder"
    assert repair_target_for("FIXTURE_INPUT_DUPLICATE", round_index=1) == "builder"
    assert repair_target_for("WORKSPACE_REFERENCE_FIXTURE_REJECTED", round_index=1) == "builder"
    assert repair_target_for("WORKSPACE_REFERENCE_EXECUTION_FAILED", round_index=1) == "reference"
    assert repair_target_for("WORKSPACE_REFERENCE_CONTRACT_FAILED", round_index=2) == "reference"
    assert repair_target_for("WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT", round_index=1) == "verifier"
    assert repair_target_for("WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT", round_index=2) == "verifier"
    assert repair_target_for("WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT", round_index=3) == "reference"
    assert repair_target_for("WORKSPACE_SEMANTIC_SCREEN_EXECUTION_FAILED", round_index=1) == "verifier"
    assert repair_target_for("VERIFIER_DISCRIMINATION_GAP", round_index=2) == "verifier"
    assert repair_target_for("PINNED_UPSTREAM_UNAVAILABLE", round_index=1) is None
    assert repair_target_for("DEPENDENCY_LOCK_MISSING", round_index=1) is None
    assert repair_target_for("FIXTURE_BUILDER_ISOLATION_UNAVAILABLE", round_index=1) is None


def test_report_is_written_atomically_and_round_trips(tmp_path: Path) -> None:
    draft_dir, draft = _draft_dir(tmp_path)
    report = _report(draft_control_binding(draft, draft_dir), ok=False)
    path = write_draft_self_check(draft_dir, report)
    assert path.name == "draft_selfcheck.json"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["ok"] is False and loaded["rounds"][0]["reason_codes"] == ["X"]
    assert read_draft_self_check(draft_dir) == report
