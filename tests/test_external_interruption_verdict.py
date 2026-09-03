"""供应商中途挂掉 ≠ 被测方失败(incident-provider-interruption-recorded-as-fail-*)。

不变量:
  I1 只有明确的供应商/传输故障退出才产生 EXTERNAL 中断标记;正常提交、
     步数用尽、token 预算耗尽都不产生 —— 那三种是被测方真实的终局;
  I2 该标记走既有 `missing_external` 通道,闸门按原决策表判 **BLOCKED**
     而不是 FAIL:测量被打断 = 可恢复的非结论(与崩溃报告同一口径);
  I3 标记里没有供应商响应体、URL、账号信息;
  I4 布线:轮循环把它接进 `missing_external` —— 轮级归因早就判了 EXTERNAL,
     不接上去,终态就只看 capability,一次抖动被写成该模型的 FAIL 进台账。
"""

from __future__ import annotations

import inspect

import pytest

from repoproof.adoption.repair.repair_loop import (
    classify_agent_exit_status,
    external_interruption_marker,
)
from repoproof.domain.models import Verdict, VerificationResult
from repoproof.verification import completion_gate


def _vr(name: str, passed: bool) -> VerificationResult:
    return VerificationResult(verifier=name, passed=passed, detail="")


@pytest.mark.parametrize(
    "exit_status",
    [
        "Uncaught:ServiceUnavailableError",
        "Uncaught:RateLimitError",
        "Uncaught:APITimeoutError",
        "Uncaught:APIConnectionError",
        "Uncaught:InternalServerError",
    ],
)
def test_provider_exits_produce_an_external_interruption_marker(exit_status: str) -> None:
    marker = external_interruption_marker(exit_status)
    assert marker is not None
    assert classify_agent_exit_status(exit_status)[0] == "EXTERNAL"


@pytest.mark.parametrize(
    "exit_status", ["Submitted", "LimitsExceeded", "TokenBudgetExhausted", "", "Uncaught:BadRequestError"]
)
def test_agent_side_exits_never_produce_the_marker(exit_status: str) -> None:
    assert external_interruption_marker(exit_status) is None


def test_marker_carries_no_provider_body_url_or_account() -> None:
    marker = external_interruption_marker("Uncaught:ServiceUnavailableError")
    assert marker is not None
    lowered = marker.lower()
    for leak in ("http", "://", "account", "api key", "token", "192.168"):
        assert leak not in lowered


def test_interrupted_run_is_blocked_not_failed() -> None:
    marker = external_interruption_marker("Uncaught:ServiceUnavailableError")
    gate = completion_gate.decide(
        capability=_vr("CapabilityVerifier", False),
        regression=_vr("HostRegressionVerifier", True),
        policy=_vr("PolicyVerifier", True),
        replay=None,
        adaptation=None,
        missing_external=[marker],
        budget_exhausted=None,
    )
    assert gate.verdict is Verdict.BLOCKED
    assert any(marker == reason or marker in reason for reason in gate.reasons)

    same_without_marker = completion_gate.decide(
        capability=_vr("CapabilityVerifier", False),
        regression=_vr("HostRegressionVerifier", True),
        policy=_vr("PolicyVerifier", True),
        replay=None,
        adaptation=None,
        missing_external=[],
        budget_exhausted=None,
    )
    assert same_without_marker.verdict is Verdict.FAIL


def test_round_loop_feeds_the_marker_into_missing_external() -> None:
    from repoproof.runner import host_guided

    source = inspect.getsource(host_guided)
    assert "external_interruption_marker" in source, "轮级 EXTERNAL 归因没有接进终态"
    call = source[source.index("exit_responsibility = classify_agent_exit_status") :][:1200]
    assert "external_interruption_marker" in call and "missing_external.append" in call
