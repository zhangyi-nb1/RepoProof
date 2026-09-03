"""autopilot 站结果必须投影真实失败站(incident-autopilot-rehearsal-cause-opaque-*)。

不变量:某站的 CLI payload 若在 `stages` 里带着一个 ok=False 的子站,
autopilot 记录的 reason code / detail / owner 必须来自那个子站,而不是笼统的
"REHEARSAL_FAILED";并且每站的原始 payload 必须落盘,失败可从磁盘诊断。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from repoproof.ui.services import autopilot

_spec = importlib.util.spec_from_file_location("_autopilot_fixtures", Path(__file__).with_name("test_autopilot.py"))
_fixtures = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fixtures)
_HAPPY, _Scripted, _env = _fixtures._HAPPY, _fixtures._Scripted, _fixtures._env

_BLOCKED_BUILD = {
    "ok": False,
    "verdict": "BLOCKED",
    "task_id": "tool-anon-tool-v1",
    "stages": {
        "confirm": {"task_id": "tool-anon-tool-v1", "public": 2, "held": 1},
        "preflight": {
            "schema_version": 1,
            "ok": False,
            "failure_owner": "CONTRACT",
            "reason_codes": ["REFERENCE_GOLDEN_MISMATCH"],
            "recommended_action": "ASK_USER",
            "product_stop_code": "STOP_NEEDS_HUMAN",
            "checks": [
                {"name": "frozen_wheelhouse", "ok": True, "reason_code": None, "detail": ""},
                {
                    "name": "reference_golden_mismatch",
                    "ok": False,
                    "reason_code": "REFERENCE_GOLDEN_MISMATCH",
                    "detail": "冻结 reference 目录树与期望不一致：report.pptx=ZIP_METADATA_ONLY",
                },
            ],
        },
    },
    "exported": None,
}


def test_rehearsal_failure_projects_the_failed_substage(tmp_path: Path, monkeypatch) -> None:
    state, dest = _env(tmp_path, monkeypatch)
    runner = _Scripted(tmp_path, monkeypatch, payloads={**_HAPPY, "build": _BLOCKED_BUILD})

    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=dest,
        runner=runner,
        record_dir=tmp_path / "record",
    )

    assert result["ok"] is False and result["status"] == "REHEARSAL_FAILED"
    stage = next(item for item in result["report"]["stages"] if item["stage"] == "rehearsal")
    assert stage["reason_codes"] == ["REFERENCE_GOLDEN_MISMATCH"]
    assert "ZIP_METADATA_ONLY" in stage["detail"]
    assert stage["facts"]["failure_owner"] == "CONTRACT"
    assert stage["facts"]["failed_stage"] == "preflight"
    assert list(result["report"]["stop_reason_codes"]) == ["REFERENCE_GOLDEN_MISMATCH"]


def test_every_stage_payload_is_persisted_for_disk_diagnosis(tmp_path: Path, monkeypatch) -> None:
    state, dest = _env(tmp_path, monkeypatch)
    runner = _Scripted(tmp_path, monkeypatch, payloads={**_HAPPY, "build": _BLOCKED_BUILD})

    autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=dest,
        runner=runner,
        record_dir=tmp_path / "record",
    )

    stage_dir = tmp_path / "record" / "stages"
    assert (stage_dir / "draft.json").is_file()
    rehearsal = json.loads((stage_dir / "rehearsal.json").read_text(encoding="utf-8"))
    assert rehearsal["verdict"] == "BLOCKED"
    assert rehearsal["stages"]["preflight"]["checks"][1]["reason_code"] == "REFERENCE_GOLDEN_MISMATCH"
