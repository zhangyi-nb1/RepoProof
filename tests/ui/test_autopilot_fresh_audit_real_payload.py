"""autopilot 必须按审核 CLI **真实**的 payload 形状判定新输入抽查(incident-autopilot-misreads-fresh-audit-pass-*)。

现象:两个任务版本上,`tool audit --build` 的 payload 是 ok=true、`reason_code`(单数)=
FRESH_INPUT_PASS、decision ACTIVE,工具已在盘上 ACTIVE;autopilot 却只在一个从不存在的
`reason_codes` 列表里找 FRESH_INPUT_PASS,于是把成功写成 `FRESH_AUDIT_FAILED` 收工。既有测试
用了同样虚构的形状,所以从来没红过——第二把尺子。

不变量:
  I1 真实形状(单数 reason_code=FRESH_INPUT_PASS / FRESH_INPUT_SEMANTIC_PASS,决策 ACTIVE)判为通过,
     终态 ACTIVE;
  I2 真实的失败形状(ok=false 或 reason_code=SEMANTIC_VERIFIER_MISMATCH,决策 REVOKED)判为失败,
     且 reason code 投影为审核给出的 reason_code,不是笼统的 FRESH_AUDIT_FAILED。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from repoproof.ui.services import autopilot

_spec = importlib.util.spec_from_file_location("_autopilot_fixtures", Path(__file__).with_name("test_autopilot.py"))
_fixtures = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fixtures)
_HAPPY, _Scripted, _env = _fixtures._HAPPY, _fixtures._Scripted, _fixtures._env


def _real_pass(reason_code: str = "FRESH_INPUT_PASS") -> dict:
    return {
        "ok": True,
        "tool": "anon-tool",
        "task_id": "tool-anon-tool-v1",
        "historical_verdict": "VERIFIED_TOOL_READY",
        "operational_status": "ACTIVE",
        "reason_code": reason_code,
        "decision": {"decision": "ACTIVE", "reason_code": reason_code},
        "semantic_verifier_passed": True,
        "workspace_structure_passed": True,
        "artifact_tree_sha256": "b" * 64,
        "exit_code": 0,
    }


def _real_fail() -> dict:
    return {
        "ok": True,
        "tool": "anon-tool",
        "task_id": "tool-anon-tool-v1",
        "operational_status": "REVOKED",
        "reason_code": "SEMANTIC_VERIFIER_MISMATCH",
        "decision": {"decision": "REVOKED", "reason_code": "SEMANTIC_VERIFIER_MISMATCH"},
        "semantic_verifier_passed": False,
        "exit_code": 0,
    }


def _drive(tmp_path: Path, monkeypatch, audit: dict) -> dict:
    _state, dest = _env(tmp_path, monkeypatch)
    runner = _Scripted(tmp_path, monkeypatch, payloads={**_HAPPY, "audit": audit})
    return autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=dest,
        runner=runner,
        record_dir=tmp_path / "record",
    )


def test_real_pass_payload_is_recognised(tmp_path: Path, monkeypatch) -> None:
    result = _drive(tmp_path, monkeypatch, _real_pass())
    assert result["ok"] is True and result["status"] == "ACTIVE", result
    stage = next(s for s in result["report"]["stages"] if s["stage"] == "fresh_audit")
    assert stage["ok"] is True and not stage["reason_codes"]


def test_semantic_only_pass_is_still_a_pass(tmp_path: Path, monkeypatch) -> None:
    result = _drive(tmp_path, monkeypatch, _real_pass("FRESH_INPUT_SEMANTIC_PASS"))
    assert result["ok"] is True and result["status"] == "ACTIVE", result


def test_real_revocation_projects_the_audit_reason(tmp_path: Path, monkeypatch) -> None:
    result = _drive(tmp_path, monkeypatch, _real_fail())
    assert result["ok"] is False and result["status"] == "FRESH_AUDIT_FAILED"
    stage = next(s for s in result["report"]["stages"] if s["stage"] == "fresh_audit")
    assert "SEMANTIC_VERIFIER_MISMATCH" in stage["reason_codes"]
