"""Claude 网关通道:显式选择 + provider 强制结构化输出。

不变量:
  I1 通道必须被显式点名(`REPOPROOF_DRAFTER_BACKEND`),未配置就报公开码,
     绝不静默回落到另一条通道 —— 换通道会换掉计费主体与模型身份;
  I2 结构化输出=强制工具调用(tools + tool_choice + input_schema),
     返回的 `tool_use.input` 原样成为 JSON 文本,不经模型散文;
  I3 声明了 schema 却拿回散文 → `ANTHROPIC_STRUCTURED_OUTPUT_NOT_ENFORCED`,
     不接受自由文本(OpenAI 兼容 shim 正是在这里静默降级的);
  I4 只有 temperature 一个参数可在 provider 明确拒收时降级,只降一次,
     且如实记 `temperature_dropped`;其他 4xx 不重试;
  I5 传输失败投影成公开码,证据里不含 key、不含主机名;
  I6 `_once_with_system` 之上的全部起草/修复逻辑与 litellm 通道**是同一份代码**,
     两条通道不可能在"要什么、收什么"上漂移。
"""

from __future__ import annotations

import json

import pytest

from repoproof.adoption.intake import tool_drafter
from repoproof.adoption.intake.tool_drafter import (
    AnthropicGatewayDrafter,
    DraftError,
    LiteLLMDrafter,
    configured_drafter_backend,
    online_drafter,
)
from repoproof.agents import anthropic_gateway as gw

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict"],
    "properties": {"verdict": {"type": "string", "enum": ["ok", "bad"]}},
}


def _config(**kwargs) -> gw.AnthropicGatewayConfig:
    base = {
        "model_name": "anon-claude",
        "api_base": "http://gateway.invalid",
        "api_key": "anon-token",
    }
    base.update(kwargs)
    return gw.AnthropicGatewayConfig(**base)


class _Recorder:
    """Scripted transport: records every request, replays queued responses."""

    def __init__(self, *responses: tuple[int, dict | bytes]):
        self.requests: list[dict] = []
        self._responses = list(responses)

    def __call__(self, url, payload, headers, timeout_s):
        self.requests.append(
            {
                "url": url,
                "body": json.loads(payload.decode("utf-8")),
                "headers": headers,
                "timeout_s": timeout_s,
            }
        )
        status, body = self._responses[min(len(self.requests), len(self._responses)) - 1]
        return status, body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")


def _ok(tool_input: dict | None = None, text: str = "") -> dict:
    content = (
        [{"type": "tool_use", "name": "emit", "input": tool_input}]
        if tool_input is not None
        else [{"type": "text", "text": text}]
    )
    return {"content": content, "usage": {"input_tokens": 11, "output_tokens": 5}}


# ---------------------------------------------------------------- I1 explicit
def test_backend_must_be_named_and_never_falls_back(monkeypatch) -> None:
    monkeypatch.delenv("REPOPROOF_DRAFTER_BACKEND", raising=False)
    assert configured_drafter_backend() == "litellm"
    for alias in ("anthropic-gateway", "anthropic", "claude", "CLAUDE"):
        monkeypatch.setenv("REPOPROOF_DRAFTER_BACKEND", alias)
        assert configured_drafter_backend() == "anthropic-gateway"
    monkeypatch.setenv("REPOPROOF_DRAFTER_BACKEND", "gemini")
    with pytest.raises(DraftError):
        configured_drafter_backend()


def test_unconfigured_channel_reports_missing_names_and_does_not_switch(monkeypatch) -> None:
    monkeypatch.setenv("REPOPROOF_DRAFTER_BACKEND", "anthropic-gateway")
    for name in ("REPOPROOF_ANTHROPIC_BASE", "REPOPROOF_ANTHROPIC_KEY", "REPOPROOF_ANTHROPIC_MODEL", "REPOPROOF_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(DraftError) as caught:
        online_drafter()
    assert "REPOPROOF_ANTHROPIC_BASE" in str(caught.value)
    cause = caught.value.__cause__
    assert isinstance(cause, gw.AnthropicGatewayError) and cause.code == gw.NOT_CONFIGURED
    assert "REPOPROOF_ANTHROPIC_KEY" in cause.detail


def test_configured_channel_is_the_selected_drafter(monkeypatch) -> None:
    monkeypatch.setenv("REPOPROOF_DRAFTER_BACKEND", "anthropic-gateway")
    monkeypatch.setenv("REPOPROOF_ANTHROPIC_BASE", "http://gateway.invalid")
    monkeypatch.setenv("REPOPROOF_ANTHROPIC_KEY", "anon-token")
    monkeypatch.setenv("REPOPROOF_ANTHROPIC_MODEL", "anon-claude")
    drafter = online_drafter()
    assert isinstance(drafter, AnthropicGatewayDrafter)
    assert drafter.name == "anthropic-gateway:anon-claude"
    status = tool_drafter.online_drafter_status()
    assert status["ready"] is True and status["backend"] == "anthropic-gateway"


# ------------------------------------------------------- I2/I3 enforced schema
def test_schema_travels_as_a_forced_tool_call(monkeypatch) -> None:
    transport = _Recorder((200, _ok({"verdict": "ok"})))
    reply = gw.call_messages(
        _config(), system="sys", user="hi", schema=_SCHEMA, transport=transport
    )
    body = transport.requests[0]["body"]
    assert body["tools"][0]["input_schema"] == _SCHEMA
    assert body["tool_choice"] == {"type": "tool", "name": "emit"}
    assert "response_format" not in body
    assert transport.requests[0]["url"].endswith("/v1/messages")
    assert transport.requests[0]["headers"]["anthropic-version"] == gw.ANTHROPIC_VERSION
    assert reply.structured is True
    assert json.loads(reply.text) == {"verdict": "ok"}
    assert reply.usage == {"prompt_tokens": 11, "completion_tokens": 5}


def test_prose_answer_to_a_schema_request_is_a_public_failure() -> None:
    transport = _Recorder((200, _ok(text='```json\n{"verdict": "ok"}\n```')))
    with pytest.raises(gw.AnthropicGatewayError) as caught:
        gw.call_messages(_config(), system="s", user="u", schema=_SCHEMA, transport=transport)
    assert caught.value.code == gw.STRUCTURED_OUTPUT_NOT_ENFORCED


def test_free_text_request_keeps_returning_text() -> None:
    transport = _Recorder((200, _ok(text="OK")))
    reply = gw.call_messages(_config(), system="s", user="u", transport=transport)
    assert reply.text == "OK" and reply.structured is False
    assert "tools" not in transport.requests[0]["body"]


# ------------------------------------------------------------ I4 temperature
def test_temperature_is_dropped_only_once_and_recorded() -> None:
    rejected = {"error": {"type": "invalid_request_error", "message": "`temperature` is deprecated for this model."}}
    transport = _Recorder((400, rejected), (200, _ok({"verdict": "ok"})))
    reply = gw.call_messages(
        _config(temperature_policy="0"), system="s", user="u", schema=_SCHEMA, transport=transport
    )
    assert [("temperature" in r["body"]) for r in transport.requests] == [True, False]
    assert reply.temperature_dropped is True


def test_other_bad_requests_are_not_retried() -> None:
    other = {"error": {"type": "invalid_request_error", "message": "max_tokens too large"}}
    transport = _Recorder((400, other), (200, _ok({"verdict": "ok"})))
    with pytest.raises(gw.AnthropicGatewayError) as caught:
        gw.call_messages(_config(temperature_policy="0"), system="s", user="u", transport=transport)
    assert caught.value.code == gw.BAD_REQUEST and len(transport.requests) == 1


def test_provider_default_policy_never_sends_temperature() -> None:
    transport = _Recorder((200, _ok(text="OK")))
    gw.call_messages(_config(), system="s", user="u", transport=transport)
    assert "temperature" not in transport.requests[0]["body"]


# ------------------------------------------------------------ I5 public codes
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, gw.AUTH_FAILED),
        (403, gw.AUTH_FAILED),
        (404, gw.MODEL_NOT_AVAILABLE),
        (429, gw.RATE_LIMITED),
        (503, gw.UNAVAILABLE),
    ],
)
def test_transport_failures_project_public_codes(status: int, code: str) -> None:
    transport = _Recorder((status, {"error": {"message": "upstream said no"}}))
    with pytest.raises(gw.AnthropicGatewayError) as caught:
        gw.call_messages(_config(), system="s", user="u", transport=transport)
    assert caught.value.code == code
    rendered = str(caught.value)
    assert "anon-token" not in rendered and "gateway.invalid" not in rendered


def test_auth_failure_detail_is_empty_so_no_credential_echo() -> None:
    transport = _Recorder((401, {"error": {"message": "invalid api key anon-token"}}))
    with pytest.raises(gw.AnthropicGatewayError) as caught:
        gw.call_messages(_config(), system="s", user="u", transport=transport)
    assert caught.value.detail == ""


def test_drafter_projects_gateway_codes_as_draft_errors(monkeypatch) -> None:
    monkeypatch.setenv("REPOPROOF_ANTHROPIC_BASE", "http://gateway.invalid")
    monkeypatch.setenv("REPOPROOF_ANTHROPIC_KEY", "anon-token")
    monkeypatch.setenv("REPOPROOF_ANTHROPIC_MODEL", "anon-claude")
    drafter = AnthropicGatewayDrafter()
    monkeypatch.setattr(
        gw, "_urllib_transport", _Recorder((503, {"error": {"message": "Service temporarily unavailable"}}))
    )
    with pytest.raises(DraftError) as caught:
        drafter._once_with_system("s", "u", schema=_SCHEMA, schema_name="tool_draft")
    assert str(caught.value) == gw.UNAVAILABLE


def test_drafter_records_usage_and_returns_tool_input(monkeypatch) -> None:
    monkeypatch.setenv("REPOPROOF_ANTHROPIC_BASE", "http://gateway.invalid/v1")
    monkeypatch.setenv("REPOPROOF_ANTHROPIC_KEY", "anon-token")
    monkeypatch.setenv("REPOPROOF_ANTHROPIC_MODEL", "anon-claude")
    drafter = AnthropicGatewayDrafter()
    transport = _Recorder((200, _ok({"verdict": "ok"})))
    monkeypatch.setattr(gw, "_urllib_transport", transport)
    text = drafter._once_with_system("s", "u", schema=_SCHEMA, schema_name="tool_draft")
    assert json.loads(text) == {"verdict": "ok"}
    assert drafter.last_usage == {"prompt_tokens": 11, "completion_tokens": 5}
    # A bare host and an explicit /v1 base must reach the same endpoint.
    assert transport.requests[0]["url"] == "http://gateway.invalid/v1/messages"
    assert transport.requests[0]["timeout_s"] == tool_drafter._LONG_FORM_DRAFTER_TIMEOUT_SECONDS


# --------------------------------------------------------------- I6 no drift
def test_high_level_drafting_logic_is_literally_shared_with_the_other_channel() -> None:
    shared = (
        "draft",
        "draft_verifier",
        "repair_reference",
        "repair_workspace_reference",
        "repair_verifier",
        "repair_workspace_contract",
        "repair_fixture_builder",
        "propose_example_inputs",
        "propose_workspace_fixture_blueprints",
        "summarize_repo",
        "_repair_source",
        "_once",
    )
    for name in shared:
        assert getattr(AnthropicGatewayDrafter, name) is getattr(LiteLLMDrafter, name), name
    assert AnthropicGatewayDrafter._once_with_system is not LiteLLMDrafter._once_with_system
