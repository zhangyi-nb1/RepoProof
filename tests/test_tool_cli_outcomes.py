"""M6 CLI exit codes are the durable Product worker's success boundary."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from repoproof import cli
from repoproof.adoption.intake import tool_confirm, tool_drafter, tool_intake
from repoproof.runner import tool_pipeline


@pytest.mark.parametrize(
    ("result", "rehearsal_only", "expected"),
    [
        ({"verdict": "REHEARSAL_PASS_ONLY", "exported": None}, True, True),
        ({"verdict": "BLOCKED", "exported": None}, True, False),
        ({"verdict": "REHEARSAL_FAIL", "exported": None}, True, False),
        (
            {
                "verdict": "VERIFIED_TOOL_READY",
                "historical_verdict": "VERIFIED_TOOL_READY",
                "exported": "/tools/demo",
            },
            False,
            True,
        ),
        ({"verdict": "REAL_BLOCKED", "exported": None}, False, False),
        (
            {
                "historical_verdict": "VERIFIED_TOOL_READY",
                "exported": None,
            },
            False,
            False,
        ),
        ({"historical_verdict": "FAIL", "exported": "/tools/demo"}, False, False),
    ],
)
def test_tool_build_completion_boundary(
    result: dict,
    rehearsal_only: bool,
    expected: bool,
) -> None:
    assert tool_pipeline.tool_build_completed(
        result, rehearsal_only=rehearsal_only
    ) is expected


@pytest.mark.parametrize(
    ("result", "rehearsal_only", "expected_code"),
    [
        ({"verdict": "REHEARSAL_PASS_ONLY", "exported": None}, True, 0),
        ({"verdict": "REHEARSAL_FAIL", "exported": None}, True, 3),
        (
            {
                "historical_verdict": "VERIFIED_TOOL_READY",
                "verdict": "VERIFIED_TOOL_READY",
                "exported": "/tools/demo",
            },
            False,
            0,
        ),
        ({"verdict": "REAL_BLOCKED", "exported": None}, False, 3),
    ],
)
def test_tool_build_cli_exit_matches_completion_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    result: dict,
    rehearsal_only: bool,
    expected_code: int,
) -> None:
    monkeypatch.setattr(tool_pipeline, "tool_build", lambda *args, **kwargs: result)
    argv = [
        "tool",
        "build",
        "--draft-dir",
        str(tmp_path / "draft"),
        "--dest-root",
        str(tmp_path / "tools"),
    ]
    if rehearsal_only:
        argv.append("--rehearsal-only")

    assert cli.main(argv) == expected_code
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is (expected_code == 0)


def test_tool_add_drafter_failure_is_nonzero_even_when_skeleton_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = SimpleNamespace(
        admission=SimpleNamespace(
            status="SUPPORTED",
            to_dict=lambda: {"status": "SUPPORTED"},
        ),
        draft=object(),
    )
    bundle = tmp_path / "draft"
    monkeypatch.setattr(tool_intake, "run_tool_intake", lambda *args, **kwargs: report)
    monkeypatch.setattr(tool_confirm, "write_draft_bundle", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(tool_drafter, "LiteLLMDrafter", lambda: object())

    def _fail(*_args: object, **_kwargs: object) -> None:
        raise tool_drafter.DraftError("drafter unavailable")

    monkeypatch.setattr(tool_drafter, "draft_into_bundle", _fail)
    code = cli.main(
        [
            "tool",
            "add",
            "--repo",
            "https://github.com/acme/demo",
            "--capability",
            "Convert the input into deterministic text.",
            "--draft-out",
            str(bundle),
        ]
    )

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["draft_bundle"] == str(bundle)
    assert payload["draft_error"] == "drafter unavailable"
