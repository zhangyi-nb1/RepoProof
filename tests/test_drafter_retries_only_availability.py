"""秒级中断不该报废一趟旅程(incident-provider-interruption-recorded-as-fail-*)。

现象:同一天两次网关瞬时中断(事后复验 TCP 0.02 s、真调用 2.5 s),各自打断了一趟已经跑了
十几分钟的旅程。终态现在被正确记成"通道不可用"而不是草稿失败,但代价是一次眨眼就报废一趟。
这两条记录的既定处置本来就是 RETRY_INFRASTRUCTURE——只是起草通道上从没实现过。

不变量:
  I1 通道**可用性**类失败在起草侧有界重试(超时、连接错、限流、不可用);
  I2 **配置**类失败一次都不重试(未配置、认证失败、坏请求)——等一等不会变好;
  I3 重试有界:仍失败就如实抛出原始公开码,不改写、不换通道、不换模型。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake import tool_drafter
from repoproof.agents import anthropic_gateway
from repoproof.agents.anthropic_gateway import AnthropicGatewayError

AVAILABILITY = [
    anthropic_gateway.UNAVAILABLE,
    anthropic_gateway.TIMEOUT,
    anthropic_gateway.CONNECTIVITY,
    anthropic_gateway.RATE_LIMITED,
]
CONFIGURATION = [
    anthropic_gateway.NOT_CONFIGURED,
    anthropic_gateway.AUTH_FAILED,
    anthropic_gateway.BAD_REQUEST,
]


def _drafter(monkeypatch, replies):
    """``replies`` is a list of gateway codes; ``None`` means a successful reply."""

    calls: list[int] = []

    class _Reply:
        text = '{"semantic_verifier": "x"}'
        usage: dict = {}
        temperature_dropped = False

    def fake_call_messages(config, **_kwargs):
        calls.append(len(calls))
        code = replies[min(len(calls) - 1, len(replies) - 1)]
        if code is None:
            return _Reply()
        raise AnthropicGatewayError(code)

    monkeypatch.setattr(anthropic_gateway, "call_messages", fake_call_messages)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    drafter = object.__new__(tool_drafter.AnthropicGatewayDrafter)
    drafter._config = object()
    drafter.last_usage = {}
    drafter.temperature_dropped = False
    return drafter, calls


@pytest.mark.parametrize("code", AVAILABILITY)
def test_availability_failures_are_retried_then_reported(monkeypatch, code: str) -> None:
    drafter, calls = _drafter(monkeypatch, [code])
    with pytest.raises(tool_drafter.DraftError) as excinfo:
        drafter._once_with_system("s", "u", schema={"type": "object"}, schema_name="tool_draft")
    assert len(calls) > 1, "可用性类失败要重试"
    assert len(calls) <= 3, "重试必须有界"
    assert code in str(excinfo.value), "仍失败要如实抛出原始公开码"


@pytest.mark.parametrize("code", CONFIGURATION)
def test_configuration_failures_are_not_retried(monkeypatch, code: str) -> None:
    drafter, calls = _drafter(monkeypatch, [code])
    with pytest.raises(tool_drafter.DraftError):
        drafter._once_with_system("s", "u", schema={"type": "object"}, schema_name="tool_draft")
    assert len(calls) == 1, "配置类失败等一等不会变好"


def test_a_blip_that_clears_lets_the_call_through(monkeypatch) -> None:
    drafter, calls = _drafter(monkeypatch, [anthropic_gateway.UNAVAILABLE, None])
    text = drafter._once_with_system(
        "s", "u", schema={"type": "object"}, schema_name="tool_draft"
    )
    assert text == '{"semantic_verifier": "x"}'
    assert len(calls) == 2
