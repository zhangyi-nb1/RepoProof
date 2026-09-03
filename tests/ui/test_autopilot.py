"""Journey autopilot(仓库地址 + 一句话 → ACTIVE)的机制钉。

不变量:
  I1 autopilot 不新增判定:每一站都是既有生产路径的调用,站结果原样记录;
  I2 首个失败站即停,带该站的公开 reason code;不重试、不跳站;
  I3 被替代的两道人闸(样例确认、意图确认)必须留下 confirmed_by=autopilot 的
     来源标记,报告与草稿目录里都有;
  I4 `--until` 可在任一站后暂停(用于"全部彩排 → 冻结协议 → 再真发");
     `--resume-task-id` 从真发续跑,不重冻;
  I5 预期拒绝(N0 型)在 admission UNSUPPORTED 时判为成功且零后续站;
  I6 终态只从 registry+ledger 重算,不信任何站的 payload。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from repoproof.ui.services import autopilot, product_jobs


def _env(tmp_path: Path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    dest = tmp_path / "tools"
    dest.mkdir()
    return state, dest


def _write_draft(draft_dir: Path, *, profile: str = "workspace_bundle_v1") -> None:
    (draft_dir / "examples").mkdir(parents=True, exist_ok=True)
    (draft_dir / "draft.yaml").write_text(
        yaml.safe_dump(
            {"tool": {"name": "anon-tool"}, "_delivery_profile": {"schema_version": 1, "profile_id": profile}}
        ),
        encoding="utf-8",
    )
    (draft_dir / "workspace_fixture_candidates.json").write_text(
        json.dumps({"records": [{"candidate_token": "t1"}, {"candidate_token": "t2"}, {"candidate_token": "t3"}]}),
        encoding="utf-8",
    )


class _Scripted:
    """Scripted CLI runner + service doubles; records every call in order."""

    def __init__(self, tmp_path: Path, monkeypatch, *, payloads: dict[str, dict], active: bool = True):
        self.calls: list[list[str]] = []
        self.payloads = payloads
        self.service_calls: list[str] = []
        monkeypatch.setattr(
            product_jobs,
            "confirm_workspace_fixture_candidate",
            lambda d, *, candidate_token: self.service_calls.append(f"confirm:{candidate_token}") or {"ok": True},
        )
        monkeypatch.setattr(
            product_jobs, "confirm_draft_intent", lambda d: self.service_calls.append("intent") or {"ok": True}
        )
        monkeypatch.setattr(
            product_jobs,
            "freeze_draft_wheelhouse",
            lambda d: self.service_calls.append("freeze") or {"ok": True, "wheels": 7, "root": "a" * 64},
        )
        monkeypatch.setattr(
            product_jobs,
            "propose_audit_candidates",
            lambda name, **kw: (
                self.service_calls.append("propose")
                or {"ok": True, "candidates": [{"candidate_token": "f1", "blueprint_id": "fresh-one"}]}
            ),
        )
        monkeypatch.setattr(
            product_jobs,
            "materialize_workspace_audit_candidate",
            lambda name, **kw: (
                self.service_calls.append("materialize")
                or {"ok": True, "input": str(tmp_path / "in"), "expected": str(tmp_path / "exp")}
            ),
        )
        monkeypatch.setattr(
            "repoproof.ui.services.product_mode.list_tools",
            lambda root: {
                "tools": [
                    {
                        "name": "anon-tool",
                        "operational_status": "ACTIVE" if active else "REVIEW_REQUIRED",
                        "health": "OK",
                        "historical_verdict": "VERIFIED_TOOL_READY",
                    }
                ]
            },
        )

    def __call__(self, argv):
        argv = list(argv)
        self.calls.append(argv)
        verb = argv[1]
        if verb == "add":
            draft_dir = Path(argv[argv.index("--draft-out") + 1])
            payload = self.payloads["add"]
            if payload.get("ok"):
                _write_draft(draft_dir, profile=payload.get("_profile", "workspace_bundle_v1"))
            return payload
        return self.payloads[verb]


_HAPPY = {
    "add": {
        "ok": True,
        "admission": {"status": "RISK_REVIEW"},
        "draft_selfcheck": {"ok": True, "status": "PASSED", "rounds": 2},
    },
    "build": {
        "ok": True,
        "verdict": "REHEARSAL_PASS_ONLY",
        "task_id": "tool-anon-tool-v1",
        "stages": {"rehearsal": {"verdict": "PASS_ADAPTED"}},
    },
    "build-real": {
        "ok": True,
        "verdict": "VERIFIED_TOOL_READY",
        "exported": "/tools/anon-tool",
        "stages": {"real": {"verdict": "PASS_ADAPTED", "run_id": "tool-anon-tool-v1-20260902-000000"}},
    },
    # Real audit CLI shape: a singular reason_code and a decision record; the
    # payload never carried a reason_codes list (a fixture that invented one
    # kept a dead check green — incident-autopilot-misreads-fresh-audit-pass-*).
    "audit": {
        "ok": True,
        "reason_code": "FRESH_INPUT_PASS",
        "decision": {"decision": "ACTIVE", "reason_code": "FRESH_INPUT_PASS"},
        "operational_status": "ACTIVE",
        "artifact_tree_sha256": "b" * 64,
        "semantic_verifier_passed": True,
    },
}


def test_happy_path_drives_every_stage_in_order_and_records_provenance(tmp_path: Path, monkeypatch) -> None:
    state, dest = _env(tmp_path, monkeypatch)
    runner = _Scripted(tmp_path, monkeypatch, payloads=_HAPPY)

    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=dest,
        runner=runner,
        record_dir=tmp_path / "record",
    )

    assert result["ok"] is True and result["status"] == "ACTIVE"
    report = result["report"]
    assert [s["stage"] for s in report["stages"]] == list(autopilot.STAGES)
    assert all(s["ok"] for s in report["stages"])
    assert [c[1] for c in runner.calls] == ["add", "build", "build-real", "audit"]
    assert runner.service_calls == [
        "confirm:t1",
        "confirm:t2",
        "confirm:t3",
        "intent",
        "freeze",
        "propose",
        "materialize",
    ]
    assert report["provenance"]["examples_confirmed_by"] == "autopilot"
    assert report["task_id"] == "tool-anon-tool-v1" and report["tool_name"] == "anon-tool"
    draft_dir = Path(report["draft_dir"])
    marker = json.loads((draft_dir / "autopilot.json").read_text(encoding="utf-8"))
    assert marker["examples_confirmed_by"] == "autopilot" and marker["examples_confirmed"] == 3
    assert (tmp_path / "record" / "autopilot-report.json").is_file()
    assert Path(result["report_path"]).is_file()
    # 彩排与真发都必须带批次与后端;审核必须带 --build 与冻结 task 绑定
    build = next(c for c in runner.calls if c[1] == "build")
    assert "--rehearsal-only" in build and "--batch" in build
    audit = next(c for c in runner.calls if c[1] == "audit")
    assert "--build" in audit and "tool-anon-tool-v1" in audit


def test_expected_admission_rejection_is_success_with_zero_later_stages(tmp_path: Path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    payloads = dict(_HAPPY)
    payloads["add"] = {
        "ok": False,
        "admission": {
            "status": "UNSUPPORTED",
            "reason_codes": ["UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT"],
            "blockers": ["needs secrets"],
        },
    }
    runner = _Scripted(tmp_path, monkeypatch, payloads=payloads)

    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="watch my balance live",
        project_root=tmp_path,
        dest_root=tmp_path / "tools",
        runner=runner,
        expect_admission_rejection=True,
    )

    assert result["ok"] is True and result["status"] == "EXPECTED_REJECTION"
    assert [c[1] for c in runner.calls] == ["add"] and runner.service_calls == []
    assert result["report"]["stop_reason_codes"] == ["UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT"]

    unexpected = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="watch my balance live",
        project_root=tmp_path,
        dest_root=tmp_path / "tools",
        runner=_Scripted(tmp_path, monkeypatch, payloads=payloads),
    )
    assert unexpected["ok"] is False and unexpected["status"] == "ADMISSION_REJECTED"


def test_first_failing_stage_stops_with_its_public_codes(tmp_path: Path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    payloads = dict(_HAPPY)
    payloads["build"] = {
        "ok": False,
        "verdict": "REHEARSAL_FAIL",
        "task_id": "tool-anon-tool-v1",
        "stages": {
            "rehearsal": {
                "verdict": "FAIL",
                "reason_codes": ["REHEARSAL_POSITIVE_CONTROL_FAILED"],
                "failure_owner": "HARNESS",
            }
        },
    }
    runner = _Scripted(tmp_path, monkeypatch, payloads=payloads)

    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=tmp_path / "tools",
        runner=runner,
    )

    assert result["ok"] is False and result["status"] == "REHEARSAL_FAILED"
    assert result["report"]["stop_stage"] == "rehearsal"
    assert result["report"]["stop_reason_codes"] == ["REHEARSAL_POSITIVE_CONTROL_FAILED"]
    assert [c[1] for c in runner.calls] == ["add", "build"]
    assert result["report"]["stages"][-1]["facts"]["failure_owner"] == "HARNESS"


def test_self_check_failure_stops_before_any_gate(tmp_path: Path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    payloads = dict(_HAPPY)
    payloads["add"] = {
        "ok": True,
        "admission": {"status": "RISK_REVIEW"},
        "draft_selfcheck": {
            "ok": False,
            "status": "FAILED",
            "rounds": 4,
            "final_reason_codes": ["WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"],
        },
    }
    runner = _Scripted(tmp_path, monkeypatch, payloads=payloads)

    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=tmp_path / "tools",
        runner=runner,
    )

    assert result["status"] == "DRAFT_SELF_CHECK_FAILED" and runner.service_calls == []
    assert result["report"]["stop_reason_codes"] == ["WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"]


def test_until_pauses_after_rehearsal_and_resume_continues_from_real_build(tmp_path: Path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    runner = _Scripted(tmp_path, monkeypatch, payloads=_HAPPY)
    paused = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=tmp_path / "tools",
        runner=runner,
        until="rehearsal",
    )
    assert paused["ok"] is True and paused["status"] == "PAUSED_AT_REHEARSAL"
    assert [c[1] for c in runner.calls] == ["add", "build"]

    resumed_runner = _Scripted(tmp_path, monkeypatch, payloads=_HAPPY)
    resumed = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=tmp_path / "tools",
        runner=resumed_runner,
        resume_task_id="tool-anon-tool-v1",
        resume_tool_name="anon-tool",
    )
    assert resumed["ok"] is True and resumed["status"] == "ACTIVE"
    assert [c[1] for c in resumed_runner.calls] == ["build-real", "audit"]
    assert [s["stage"] for s in resumed["report"]["stages"]] == ["real_build", "fresh_audit", "final"]


def test_final_state_comes_from_registry_not_from_stage_payloads(tmp_path: Path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    runner = _Scripted(tmp_path, monkeypatch, payloads=_HAPPY, active=False)

    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=tmp_path / "tools",
        runner=runner,
    )

    assert result["ok"] is False and result["status"] == "REGISTRY_NOT_ACTIVE"
    assert result["report"]["stages"][-1]["facts"]["operational_status"] == "REVIEW_REQUIRED"


def test_non_workspace_draft_is_refused_before_machine_gates(tmp_path: Path, monkeypatch) -> None:
    _env(tmp_path, monkeypatch)
    payloads = dict(_HAPPY)
    payloads["add"] = {**_HAPPY["add"], "_profile": "cli_v2"}
    runner = _Scripted(tmp_path, monkeypatch, payloads=payloads)

    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=tmp_path / "tools",
        runner=runner,
    )

    assert result["status"] == "AUTOPILOT_PROFILE_UNSUPPORTED" and runner.service_calls == []
