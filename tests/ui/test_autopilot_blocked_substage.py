"""autopilot 必须把"被阻塞"的子站也投影成公开原因(phase 2 首跑 REAL_BLOCKED 无细节)。

不变量:`stages.<name>.blocked is True` 与 `ok is False` 同等对待;其 preflight
状态(如 PROVIDER_UNAVAILABLE)与证据行成为该站的 reason code / detail,owner=EXTERNAL。
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

_BLOCKED_REAL = {
    "ok": False,
    "task_id": "tool-anon-tool-v1",
    "verdict": "REAL_BLOCKED",
    "exported": None,
    "stages": {
        "resumed_from_frozen": {"task_id": "tool-anon-tool-v1"},
        "install_preflight": {"ok": True, "mode": "first_install"},
        "preflight": {"ok": True, "reason_codes": [], "checks": []},
        "real": {
            "blocked": True,
            "preflight": {
                "status": "PROVIDER_UNAVAILABLE",
                "model_name": "anon-model",
                "evidence": ["http 503 -> PROVIDER_UNAVAILABLE"],
            },
            "agent_model_call_count": 0,
        },
    },
}


def test_blocked_real_stage_projects_provider_status(tmp_path: Path, monkeypatch) -> None:
    state, dest = _env(tmp_path, monkeypatch)
    runner = _Scripted(tmp_path, monkeypatch, payloads={**_HAPPY, "build-real": _BLOCKED_REAL})

    result = autopilot.run_journey_autopilot(
        repo="https://github.com/anon/anon",
        capability="do the thing",
        project_root=tmp_path,
        dest_root=dest,
        runner=runner,
        record_dir=tmp_path / "record",
    )

    assert result["ok"] is False and result["status"] == "REAL_BUILD_FAILED"
    stage = next(item for item in result["report"]["stages"] if item["stage"] == "real_build")
    assert stage["reason_codes"] == ["PROVIDER_UNAVAILABLE"]
    assert "http 503" in stage["detail"]
    assert stage["facts"]["failed_stage"] == "real"
    assert stage["facts"]["failure_owner"] == "EXTERNAL"
    assert list(result["report"]["stop_reason_codes"]) == ["PROVIDER_UNAVAILABLE"]
