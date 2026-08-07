"""ProviderAdmissionGate — mock-transport battery (no network, no LLM)."""

from __future__ import annotations

import json

from repoproof.agents.provider_gate import ProviderConfig, run_preflight

CFG = ProviderConfig(
    provider="openai-compatible",
    model_name="gpt-5.5",
    api_base="http://proxy.example/v1",
    api_key="sk-test-never-hashed",
)


def _native_ok(payload, timeout_s):
    assert payload["model"] == "gpt-5.5"
    return 200, {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"function": {"name": "bash", "arguments": json.dumps({"command": "echo PREFLIGHT_OK"})}}
                    ]
                }
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 7},
    }


def test_native_tool_action_ready() -> None:
    r = run_preflight(CFG, transport=_native_ok)
    assert r.ready and r.action_protocol == "native"
    assert r.calls == 1 and r.input_tokens == 20 and r.output_tokens == 7
    assert r.cost == "UNKNOWN"  # real calls, dollar price unknown — never 0


def test_textbased_action_ready_when_native_unparseable() -> None:
    def transport(payload, timeout_s):
        if "tools" in payload:
            return 200, {"choices": [{"message": {"content": "I would run echo PREFLIGHT_OK"}}], "usage": {}}
        return 200, {
            "choices": [{"message": {"content": "```bash\necho PREFLIGHT_OK\n```"}}],
            "usage": {"prompt_tokens": 15, "completion_tokens": 9},
        }

    r = run_preflight(CFG, transport=transport)
    assert r.ready and r.action_protocol == "textbased"
    assert r.calls == 2


def _err(code, body=None):
    def transport(payload, timeout_s):
        return code, body or {"error": {"message": "boom"}}

    return transport


def test_auth_failed_401() -> None:
    r = run_preflight(CFG, transport=_err(401))
    assert r.status == "AUTH_FAILED" and not r.ready


def test_model_not_available_404_and_body_variant() -> None:
    assert run_preflight(CFG, transport=_err(404)).status == "MODEL_NOT_AVAILABLE"
    body = {"error": {"message": "The model `gpt-5.5` does not exist", "code": "model_not_found"}}
    assert run_preflight(CFG, transport=_err(400, body)).status == "MODEL_NOT_AVAILABLE"


def test_rate_limited_429() -> None:
    assert run_preflight(CFG, transport=_err(429)).status == "RATE_LIMITED"


def test_provider_unavailable_503() -> None:
    r = run_preflight(CFG, transport=_err(503, {"error": {"message": "Service temporarily unavailable"}}))
    assert r.status == "PROVIDER_UNAVAILABLE" and not r.ready


def test_provider_timeout() -> None:
    def transport(payload, timeout_s):
        raise TimeoutError("read timed out")

    assert run_preflight(CFG, transport=transport).status == "PROVIDER_TIMEOUT"


def test_unparseable_actions_both_protocols() -> None:
    def transport(payload, timeout_s):
        return 200, {"choices": [{"message": {"content": "no code blocks here"}}], "usage": {}}

    r = run_preflight(CFG, transport=transport)
    assert r.status == "ACTION_PROTOCOL_UNSUPPORTED" and r.calls == 2


def test_temperature_fallback_recorded() -> None:
    def transport(payload, timeout_s):
        if "temperature" in payload:
            return 400, {"error": {"message": "temperature is not supported for this model"}}
        return _native_ok({k: v for k, v in payload.items() if k != "temperature"} | {"model": "gpt-5.5"}, timeout_s)

    r = run_preflight(CFG, transport=transport)
    assert r.ready and r.temperature == "provider_default"
    assert any("temperature" in e for e in r.evidence)


def test_config_hash_stable_and_key_excluded() -> None:
    same = ProviderConfig(
        provider="a-totally-different-display-label",
        model_name="gpt-5.5",
        api_base="http://proxy.example/v1/",
        api_key="sk-DIFFERENT-KEY",
    )
    # key, trailing slash AND display label are all irrelevant (canonical)
    assert CFG.config_sha256 == same.config_sha256
    norm = CFG.normalized()
    assert "http" not in str(norm), "raw api base must not appear in canonical form"
    assert set(norm) == {"provider_type", "api_base_fingerprint", "model_name",
                         "action_protocol", "temperature_policy"}
    other = ProviderConfig(
        provider="openai-compatible",
        model_name="gpt-5.4-mini",
        api_base="http://proxy.example/v1",
        api_key="k",
    )
    assert CFG.config_sha256 != other.config_sha256
    assert "sk-" not in json.dumps(run_preflight(CFG, transport=_err(503)).summary())
    assert "<redacted-host>" in CFG.api_base_summary


def test_blocked_preflight_never_constructs_backend() -> None:
    """Admission wiring: on a failed preflight the orchestrator must not
    build MiniSWEBackend, so DefaultAgent.run count and
    agent_model_call_count stay 0."""
    from repoproof.runner.agent_run import admit_or_block

    factory_calls = {"n": 0}

    def backend_factory():
        factory_calls["n"] += 1

    outcome = admit_or_block(CFG, transport=_err(503), backend_factory=backend_factory)
    assert outcome["blocked"] is True
    assert outcome["preflight"]["status"] == "PROVIDER_UNAVAILABLE"
    assert outcome["agent_model_call_count"] == 0
    assert factory_calls["n"] == 0


def test_ready_preflight_binds_same_config_hash_into_run() -> None:
    from repoproof.runner.agent_run import admit_or_block

    outcome = admit_or_block(CFG, transport=_native_ok, backend_factory=lambda: "backend")
    assert outcome["blocked"] is False
    assert outcome["preflight"]["provider_config_sha256"] == CFG.config_sha256
    assert outcome["run_binding"]["provider_config_sha256"] == CFG.config_sha256
    assert outcome["run_binding"]["action_protocol"] == "native"
