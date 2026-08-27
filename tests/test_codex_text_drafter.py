"""Codex subscription drafting: no tools, structured output and routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.adoption.intake import tool_drafter
from repoproof.adoption.intake.tool_drafter import CodexDrafter, DraftError
from repoproof.agents.codex_cli_backend import CodexSubscriptionConfig
from repoproof.agents.codex_text_client import CodexTextError, run_codex_structured


def _fake_codex(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if args == ['--version']:\n"
        "  print('codex-cli structured-test'); raise SystemExit(0)\n"
        "if args == ['login', 'status']:\n"
        "  raise SystemExit(0)\n"
        "if os.environ.get('REPOPROOF_TEST_EXIT'):\n"
        "  print(os.environ.get('REPOPROOF_TEST_STDERR', ''), file=sys.stderr)\n"
        "  if os.environ.get('REPOPROOF_TEST_STDOUT_ERROR'):\n"
        "    print(json.dumps({'type': 'error', 'message': os.environ['REPOPROOF_TEST_STDOUT_ERROR']}))\n"
        "  raise SystemExit(int(os.environ['REPOPROOF_TEST_EXIT']))\n"
        "prompt = sys.stdin.read()\n"
        "out = pathlib.Path(args[args.index('--output-last-message') + 1])\n"
        "schema = pathlib.Path(args[args.index('--output-schema') + 1])\n"
        "capture = pathlib.Path(os.environ['REPOPROOF_TEST_CAPTURE'])\n"
        "capture.write_text(json.dumps({\n"
        "  'argv': args, 'prompt': prompt,\n"
        "  'schema': json.loads(schema.read_text()),\n"
        "  'no_tools': os.environ.get('REPOPROOF_CODEX_NO_TOOLS'),\n"
        "  'secret_present': bool(os.environ.get('AWS_SECRET_ACCESS_KEY')),\n"
        "}))\n"
        "out.write_text(os.environ['REPOPROOF_TEST_RESPONSE'])\n"
        "if os.environ.get('REPOPROOF_TEST_TOOL_ATTEMPT') == '1':\n"
        "  pathlib.Path(os.environ['REPOPROOF_CODEX_POLICY_LOG']).write_text(\n"
        "    json.dumps({'allowed': False, 'reasons': ['no tools']}) + '\\n')\n"
        "print(json.dumps({'type': 'turn.completed', 'usage': {\n"
        "  'input_tokens': 21, 'output_tokens': 8, 'cached_input_tokens': 5}}))\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _simple_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary"],
        "properties": {"summary": {"type": "string", "minLength": 1}},
    }


def test_structured_codex_uses_stdin_schema_read_only_and_no_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _fake_codex(tmp_path / "codex")
    capture = tmp_path / "capture.json"
    monkeypatch.setenv("REPOPROOF_TEST_CAPTURE", str(capture))
    monkeypatch.setenv("REPOPROOF_TEST_RESPONSE", '{"summary":"可信摘要"}')
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-reach-child")

    result = run_codex_structured(
        config=CodexSubscriptionConfig(cli, "codex-cli test"),
        instructions="Summarize only supplied evidence.",
        context={"prose": "untrusted repository text"},
        schema=_simple_schema(),
        purpose="test-summary",
        timeout_s=10,
    )
    seen = json.loads(capture.read_text(encoding="utf-8"))

    assert result.document == {"summary": "可信摘要"}
    assert result.usage["input_tokens"] == 21
    assert seen["no_tools"] == "1"
    assert seen["secret_present"] is False
    assert seen["schema"] == _simple_schema()
    assert seen["argv"][seen["argv"].index("--sandbox") + 1] == "read-only"
    assert "--skip-git-repo-check" in seen["argv"]
    assert seen["argv"][seen["argv"].index("--disable") + 1] == "apps"
    assert seen["argv"].count("--disable") == 2
    assert "untrusted repository text" in seen["prompt"]
    assert "untrusted repository text" not in " ".join(seen["argv"])


def test_structured_codex_rejects_invalid_schema_and_any_tool_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _fake_codex(tmp_path / "codex")
    monkeypatch.setenv("REPOPROOF_TEST_CAPTURE", str(tmp_path / "capture.json"))
    monkeypatch.setenv("REPOPROOF_TEST_RESPONSE", '{"wrong":"shape"}')
    config = CodexSubscriptionConfig(cli, "codex-cli test")

    with pytest.raises(CodexTextError, match="SCHEMA_INVALID"):
        run_codex_structured(
            config=config,
            instructions="Summarize.",
            context={},
            schema=_simple_schema(),
            purpose="bad-schema",
            timeout_s=10,
        )

    monkeypatch.setenv("REPOPROOF_TEST_RESPONSE", '{"summary":"ok"}')
    monkeypatch.setenv("REPOPROOF_TEST_TOOL_ATTEMPT", "1")
    with pytest.raises(CodexTextError, match="TOOL_ATTEMPT"):
        run_codex_structured(
            config=config,
            instructions="Summarize.",
            context={},
            schema=_simple_schema(),
            purpose="tool-attempt",
            timeout_s=10,
        )


def test_structured_codex_classifies_connectivity_without_echoing_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _fake_codex(tmp_path / "codex")
    monkeypatch.setenv("REPOPROOF_TEST_EXIT", "1")
    monkeypatch.setenv("REPOPROOF_TEST_STDERR", "warning only")
    monkeypatch.setenv(
        "REPOPROOF_TEST_STDOUT_ERROR",
        "responses_websocket: InvalidContentType /private/path",
    )

    with pytest.raises(CodexTextError, match="CODEX_CONNECTIVITY_ERROR") as raised:
        run_codex_structured(
            config=CodexSubscriptionConfig(cli, "codex-cli test"),
            instructions="Summarize.",
            context={},
            schema=_simple_schema(),
            purpose="network-test",
            timeout_s=10,
        )

    assert "/private/path" not in str(raised.value)
    assert "/private/path" in raised.value.diagnostic


def test_codex_drafter_supports_summary_draft_and_candidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _fake_codex(tmp_path / "codex")
    monkeypatch.setenv("REPOPROOF_CODEX_CLI", str(cli))
    monkeypatch.setenv("REPOPROOF_TEST_CAPTURE", str(tmp_path / "capture.json"))
    monkeypatch.delenv("REPOPROOF_CODEX_MODEL", raising=False)
    drafter = CodexDrafter()

    monkeypatch.setenv("REPOPROOF_TEST_RESPONSE", '{"summary":"仓库摘要"}')
    assert drafter.summarize_repo({"headline": "demo"}) == {"summary": "仓库摘要"}

    draft = {
        "summary": "转换文本",
        "input_format": "TXT",
        "output_format": "TXT",
        "output_schema": "ConvertedText",
        "output_contract": {
            "media_type": "text/plain",
            "root_type": "text",
            "required_fields": [],
        },
        "statement": "离线确定性转换；坏输入抛 UserInputError。",
        "reference_impl": "from pathlib import Path\ndef extract(p: Path) -> str:\n    return p.read_text()\n",
        "example_suggestions": [{"description": "典型输入", "assertion_kind": "exact_file"}],
    }
    monkeypatch.setenv("REPOPROOF_TEST_RESPONSE", json.dumps(draft, ensure_ascii=False))
    drafted = drafter.draft({"capability_goal": "转换"})
    assert drafted["output_schema"] == "ConvertedText"
    assert drafted["output_contract"]["required"] == {}
    assert "required_fields" not in drafted["output_contract"]

    candidates = {
        "inputs": [
            {"input_name": f"case-{i}.txt", "input_text": f"abc-{i}", "why": "候选输入"}
            for i in range(4)
        ],
    }
    monkeypatch.setenv("REPOPROOF_TEST_RESPONSE", json.dumps(candidates, ensure_ascii=False))
    assert drafter.propose_example_inputs({"capability_goal": "转换"}) == candidates
    seen = json.loads((tmp_path / "capture.json").read_text(encoding="utf-8"))
    assert seen["schema"]["properties"]["inputs"]["minItems"] == 4
    assert seen["schema"]["properties"]["inputs"]["maxItems"] == 4
    assert drafter.last_usage["cost"] == "INCLUDED_USAGE_UNMETERED"


def test_online_drafter_defaults_to_codex_without_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    monkeypatch.delenv("REPOPROOF_DRAFTER_BACKEND", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(tool_drafter, "CodexDrafter", lambda: sentinel)

    assert tool_drafter.online_drafter() is sentinel


def test_online_drafter_rejects_unknown_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOPROOF_DRAFTER_BACKEND", "mystery")
    with pytest.raises(DraftError, match="未知起草 backend"):
        tool_drafter.online_drafter()
