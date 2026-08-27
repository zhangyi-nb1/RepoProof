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


def test_tool_build_cli_defaults_product_agent_to_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def _build(*_args: object, **kwargs: object) -> dict:
        seen.update(kwargs)
        return {"verdict": "REHEARSAL_PASS_ONLY", "exported": None}

    monkeypatch.setattr(tool_pipeline, "tool_build", _build)
    code = cli.main([
        "tool", "build",
        "--draft-dir", str(tmp_path / "draft"),
        "--dest-root", str(tmp_path / "tools"),
        "--rehearsal-only",
    ])

    assert code == 0
    assert seen["agent_backend"] == "codex-cli"


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


def test_tool_plan_with_repo_passes_cache_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`tool plan --repo` 必须真能调通分析器。

    2026-08-27 实录:该调用点漏传必填关键字 `cache_root`,于是这条路径
    **每次必崩**(TypeError 在调用点抛出,连克隆都没开始),而 `--dir`
    那条正常 —— 所以整条 CLI 旅程的测试全绿。mypy 首次覆盖 cli 时揪出。
    本钉只认「按真实签名可调用」:用真函数对象的签名做绑定检查,不
    monkeypatch 掉签名本身,否则钉子就跟着假签名一起瞎。
    """
    import inspect

    from repoproof.adoption.analysis import repository_analyzer

    seen: dict = {}
    real_sig = inspect.signature(repository_analyzer.analyze_repository)

    def _spy(*args: object, **kwargs: object):
        real_sig.bind(*args, **kwargs)          # 真签名绑定:漏参在这里就炸
        seen.update(kwargs)
        return SimpleNamespace(sources=[str(tmp_path)], to_dict=lambda: {})

    monkeypatch.setattr(repository_analyzer, "analyze_repository", _spy)
    monkeypatch.setattr(
        "repoproof.adoption.admission.support_policy.evaluate_tool_policy",
        lambda _report: SimpleNamespace(),
    )
    plan_obj = SimpleNamespace(
        model_dump=lambda: {"support_status": "SUPPORTED"},
        support_status="SUPPORTED",
        implementation_route="DIRECT_WRAP",
        reason_codes=[],
        detected_surfaces=[],
        plan_sha256="x" * 64,
    )
    monkeypatch.setattr(
        "repoproof.adoption.planning.capability_plan.build_capability_plan",
        lambda *_a, **_k: plan_obj,
    )

    out = tmp_path / "plan.yaml"
    code = cli.main([
        "tool", "plan",
        "--repo", "https://github.com/acme/demo",
        "--capability", "把文本转成 slug",
        "--out", str(out),
    ])

    assert code == 0
    assert "cache_root" in seen, "调用点漏传 cache_root —— 这条路径运行时必崩"
    assert out.is_file()
