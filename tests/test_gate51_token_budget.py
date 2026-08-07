"""Gate 5.1 — token budget enforcement (no model, no docker)."""

from __future__ import annotations

import pytest
from minisweagent.agents.default import DefaultAgent
from minisweagent.exceptions import LimitsExceeded

from repoproof.agents.token_budget import ENFORCEMENT, TokenBudgetedModel
from repoproof.domain.models import AdaptationManifest, Verdict, VerificationResult
from repoproof.verification.completion_gate import decide
from repoproof.verification.verifiers import policy_result


class FakeInner:
    """Fake model whose responses 'report' usage into the shared totals
    (standing in for the litellm success hook)."""

    def __init__(self, totals, per_call=(1000, 100)):
        self.totals = totals
        self.per_call = per_call
        self.calls = 0
        self.seen_kwargs: list[dict] = []

    def query(self, messages, **kwargs):
        self.calls += 1
        self.seen_kwargs.append(dict(kwargs))
        self.totals["seen"] = True
        self.totals["in"] += self.per_call[0]
        self.totals["out"] += self.per_call[1]
        return {"role": "assistant", "content": "ok", "extra": {"actions": [], "cost": 0.0}}

    def format_message(self, **kw):
        extra = kw.pop("extra", {})
        return {**kw, "extra": extra}

    def format_observation_messages(self, message, outputs, template_vars):
        return []

    def get_template_vars(self, **kw):
        return {}

    def serialize(self):
        return {"model": {"name": "fake-inner"}}


def _budgeted(totals, max_in=5000, max_out=1000, per_call=(1000, 100)):
    events = []
    inner = FakeInner(totals, per_call)
    model = TokenBudgetedModel(
        inner=inner, totals=totals, max_input_tokens=max_in, max_output_tokens=max_out,
        on_exhausted=events.append,
    )
    return model, inner, events


def test_under_limit_continues_and_passes_remaining_max_tokens() -> None:
    totals = {"in": 0, "out": 0, "seen": False}
    model, inner, _ = _budgeted(totals)
    model.query([])  # first call: unlimited knowledge yet -> full output budget
    assert inner.seen_kwargs[0]["max_tokens"] == 1000
    model.query([])  # after 100 out used -> remaining 900
    assert inner.seen_kwargs[1]["max_tokens"] == 900
    assert inner.calls == 2


def test_over_input_limit_blocks_next_call() -> None:
    totals = {"in": 0, "out": 0, "seen": False}
    model, inner, events = _budgeted(totals, max_in=2500)
    model.query([])
    model.query([])
    model.query([])  # in=3000 accumulated AFTER this call
    with pytest.raises(LimitsExceeded) as ei:
        model.query([])  # pre-call check must fire; inner never called
    assert inner.calls == 3
    assert events and events[0]["kind"] == "max_input_tokens_total"
    assert ei.value.messages[0]["extra"]["exit_status"] == "TokenBudgetExhausted"
    assert "provider_reported_post_call" in ENFORCEMENT["input"]


def test_over_output_limit_blocks_next_call() -> None:
    totals = {"in": 0, "out": 0, "seen": False}
    model, inner, events = _budgeted(totals, max_out=250)
    model.query([])
    model.query([])
    model.query([])  # out=300 >= 250 after third
    with pytest.raises(LimitsExceeded):
        model.query([])
    assert inner.calls == 3 and events[0]["kind"] == "max_output_tokens_total"


def test_default_agent_terminates_cleanly_on_budget() -> None:
    """The official InterruptAgentFlow path: exhaustion becomes an exit
    message, DefaultAgent.run returns TokenBudgetExhausted — never an
    uncaught crash, never BLOCKED."""
    totals = {"in": 0, "out": 0, "seen": False}
    model, _inner, _ = _budgeted(totals, max_in=1500)

    class NullEnv:
        def execute(self, action, cwd=""):
            return {"output": "", "returncode": 0, "exception_info": ""}

        def get_template_vars(self, **kw):
            return {}

        def serialize(self):
            return {}

    agent = DefaultAgent(model, NullEnv(), system_template="s", instance_template="{{task}}", step_limit=10)
    extra = agent.run("t")
    assert extra["exit_status"] == "TokenBudgetExhausted"
    # mswea increments n_calls BEFORE model.query; the blocked attempt
    # bumps the agent counter but the REAL network call never happens:
    assert model.inner.calls == 2
    assert agent.n_calls == 3


def _vr(name, passed=True):
    return VerificationResult(verifier=name, passed=passed, detail="t")


def test_policy_fails_on_token_budget_violation(tmp_path) -> None:
    pol = policy_result(
        token_budget={"input_used": 290819, "output_used": 11122, "input_limit": 250000, "output_limit": 30000},
        trace_path=tmp_path / "missing.jsonl" if False else _empty_trace(tmp_path),
        oracle_before={}, oracle_after={}, upstream_before={}, upstream_after={},
        adaptation_manifest=AdaptationManifest(frozen=True),
        adaptation_recheck_ok=True, adaptation_recheck_detail="ok",
        budgets=__import__("repoproof.domain.models", fromlist=["Budgets"]).Budgets(),
        evidence=[],
    )
    assert not pol.passed and "token budget violated" in pol.detail
    gate = decide(
        capability=_vr("CapabilityVerifier", False), regression=_vr("HostRegressionVerifier"),
        policy=pol, replay=None, adaptation=None,
        budget_exhausted="max_input_tokens_total (290819 >= 250000)",
    )
    assert gate.verdict is Verdict.FAIL
    assert gate.reasons[0].startswith("BUDGET_EXHAUSTED")


def test_budget_exhausted_never_reported_as_blocked() -> None:
    fail = decide(
        capability=_vr("CapabilityVerifier", False), regression=_vr("HostRegressionVerifier"),
        policy=_vr("PolicyVerifier"), replay=None, adaptation=None,
        budget_exhausted="max_output_tokens_total (30001 >= 30000)",
    )
    blocked = decide(
        capability=_vr("CapabilityVerifier", False), regression=_vr("HostRegressionVerifier"),
        policy=_vr("PolicyVerifier"), replay=None, adaptation=None,
        missing_external=["provider backend down"],
    )
    assert fail.verdict is Verdict.FAIL and blocked.verdict is Verdict.BLOCKED


def test_unknown_usage_never_written_as_zero() -> None:
    totals = {"in": 0, "out": 0, "seen": False}  # provider reported nothing
    model, inner, _ = _budgeted(totals)

    class Silent(FakeInner):
        def query(self, messages, **kwargs):
            self.calls += 1
            self.seen_kwargs.append(dict(kwargs))
            return {"role": "assistant", "content": "ok", "extra": {"actions": []}}

    model.inner = Silent(totals)
    model.query([])
    model.query([])  # still no usage seen -> no false enforcement, no fake zeros
    assert totals["seen"] is False
    assert model.inner.seen_kwargs[1]["max_tokens"] == 1000  # request-cap still applies


def _empty_trace(tmp_path):
    from repoproof.harness.trace import TraceWriter

    p = tmp_path / "trace.jsonl"
    TraceWriter(p).append("run.start", actor="runner")
    return p
