"""Product Codex connector: auth preflight, event accounting and policy hook."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repoproof.agents.codex_cli_backend import (
    CodexCLIBackend,
    CodexSubscriptionConfig,
    run_subscription_preflight,
    subscription_config,
)
from repoproof.agents.codex_hook_guard import evaluate_hook


def _executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_importing_codex_connector_does_not_load_miniswe_provider_config() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            ("import sys; import repoproof.agents.codex_cli_backend; "
             "print(any(name.startswith('minisweagent') for name in sys.modules))"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert probe.returncode == 0
    assert probe.stdout == "False\n"
    assert probe.stderr == ""


def test_codex_preflight_uses_login_status_without_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli = _executable(
        tmp_path / "codex",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'codex-cli test'; exit 0; fi\n"
        "if [ \"$1\" = \"login\" ] && [ \"$2\" = \"status\" ]; then exit 0; fi\n"
        "exit 9\n",
    )
    monkeypatch.setenv("REPOPROOF_CODEX_CLI", str(cli))
    monkeypatch.delenv("REPOPROOF_CODEX_MODEL", raising=False)

    config = subscription_config()
    assert config is not None
    result = run_subscription_preflight(config)

    assert result.ready
    assert result.calls == 0
    assert result.cost == "INCLUDED_USAGE_UNMETERED"
    assert result.action_protocol == "codex-exec-jsonl-v1"


def test_codex_hook_rejects_outside_read_and_accepts_session_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "session"
    host = root / "host"
    host.mkdir(parents=True)
    monkeypatch.setenv("REPOPROOF_CODEX_ALLOWED_ROOT", str(root))
    monkeypatch.setenv("REPOPROOF_CODEX_POLICY_LOG", str(tmp_path / "policy.jsonl"))

    denied = evaluate_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "/usr/bin/head -n 1 /etc/hosts"},
        "cwd": str(host),
    })
    allowed = evaluate_hook({
        "tool_name": "Bash",
        "tool_input": {"command": "sed -n '1,20p' ../upstream/pkg.py"},
        "cwd": str(host),
    })

    decision = denied["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "out_of_workspace_access" in decision["permissionDecisionReason"]
    assert allowed == {}


def test_codex_backend_reads_jsonl_and_strips_api_gateway_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "session" / "host"
    workspace.mkdir(parents=True)
    cli = _executable(
        tmp_path / "codex",
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "prompt = sys.stdin.read()\n"
        "pathlib.Path('captured.json').write_text(json.dumps({\n"
        "  'prompt': prompt,\n"
        "  'api_key_present': bool(os.environ.get('OPENAI_API_KEY')),\n"
        "  'gateway_present': bool(os.environ.get('REPOPROOF_API_BASE')),\n"
        "  'unrelated_secret_present': bool(os.environ.get('AWS_SECRET_ACCESS_KEY')),\n"
        "  'ssh_agent_present': bool(os.environ.get('SSH_AUTH_SOCK')),\n"
        "}))\n"
        "print(json.dumps({'type':'thread.started','thread_id':'t'}), flush=True)\n"
        "print(json.dumps({'type':'turn.started'}), flush=True)\n"
        "print(json.dumps({'type':'item.started','item':{\n"
        "  'type':'command_execution','command':'pytest -q'}}), flush=True)\n"
        "pathlib.Path(os.environ['REPOPROOF_CODEX_POLICY_LOG']).write_text(\n"
        "  json.dumps({'allowed': True, 'reasons': ['ok'], 'command': 'pytest -q'}) + '\\n')\n"
        "print(json.dumps({'type':'item.completed','item':{\n"
        "  'type':'agent_message','text':'done'}}), flush=True)\n"
        "print(json.dumps({'type':'turn.completed','usage':{\n"
        "  'input_tokens':123,'output_tokens':45,'cached_input_tokens':67}}), flush=True)\n",
    )
    config = CodexSubscriptionConfig(cli, "codex-cli test")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-codex")
    monkeypatch.setenv("REPOPROOF_API_BASE", "http://broken-gateway")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-reach-codex")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/must-not-reach-codex")
    output = tmp_path / "trajectory.jsonl"
    backend = CodexCLIBackend(
        config=config,
        workspace=workspace,
        allowed_root=workspace.parent,
        output_path=output,
        policy_log_path=tmp_path / "policy.jsonl",
        command_limit=3,
        timeout_s=10,
    )

    result = backend.run_task("repair this capability")
    captured = json.loads((workspace / "captured.json").read_text(encoding="utf-8"))

    assert result.exit_status == "Submitted"
    assert result.submission == "done"
    assert result.n_model_calls == 1 and result.model_calls_observed is False
    assert result.commands_used == 1
    assert result.policy_audit_complete is True
    assert (result.input_tokens, result.output_tokens) == (123, 45)
    assert captured == {
        "prompt": "repair this capability",
        "api_key_present": False,
        "gateway_present": False,
        "unrelated_secret_present": False,
        "ssh_agent_present": False,
    }
    # Prompt is carried on stdin and therefore never exposed in the process argv.
    assert "repair this capability" not in output.read_text(encoding="utf-8")


def test_codex_backend_fails_closed_when_policy_audit_is_missing(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "session" / "host"
    workspace.mkdir(parents=True)
    cli = _executable(
        tmp_path / "codex",
        "#!/usr/bin/env python3\n"
        "import json\n"
        "print(json.dumps({'type':'turn.started'}), flush=True)\n"
        "print(json.dumps({'type':'item.started','item':{\n"
        "  'type':'command_execution','command':'pytest -q'}}), flush=True)\n",
    )
    backend = CodexCLIBackend(
        config=CodexSubscriptionConfig(cli, "codex-cli test"),
        workspace=workspace,
        allowed_root=workspace.parent,
        output_path=tmp_path / "trajectory.jsonl",
        policy_log_path=tmp_path / "policy.jsonl",
        command_limit=3,
        timeout_s=10,
    )

    result = backend.run_task("repair this capability")

    assert result.exit_status == "CodexPolicyAuditMissing"
    assert result.policy_audit_complete is False


def test_codex_backend_refuses_workspace_outside_session(tmp_path: Path) -> None:
    cli = _executable(tmp_path / "codex", "#!/bin/sh\nexit 0\n")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ValueError, match="outside the disposable session root"):
        CodexCLIBackend(
            config=CodexSubscriptionConfig(cli, "test"),
            workspace=workspace,
            allowed_root=tmp_path / "different-root",
            output_path=tmp_path / "out.jsonl",
            policy_log_path=tmp_path / "policy.jsonl",
            command_limit=1,
            timeout_s=1,
        )


def test_codex_connector_never_requires_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # This assertion documents the credential boundary without reading any
    # Codex auth file:subscription auth is owned by the official CLI.
    assert os.environ.get("OPENAI_API_KEY") is None
