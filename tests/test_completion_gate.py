"""The gate's core promises:
  1. verdicts derive ONLY from structured verification results;
  2. a ``claim_complete`` event (agent or scripted) changes nothing;
  3. no clean-room replay -> never a final PASS.
"""

from pathlib import Path

from repoproof.domain.models import Verdict, VerificationResult
from repoproof.harness.trace import TraceWriter, scan_events
from repoproof.verification.completion_gate import decide


def _vr(name: str, passed: bool) -> VerificationResult:
    return VerificationResult(verifier=name, passed=passed, detail="t")


def test_all_pass_direct_vs_adapted() -> None:
    g = decide(
        capability=_vr("CapabilityVerifier", True),
        regression=_vr("HostRegressionVerifier", True),
        policy=_vr("PolicyVerifier", True),
        replay=_vr("ReplayVerifier", True),
        adaptation_present=False,
    )
    assert g.verdict is Verdict.PASS_DIRECT
    g2 = decide(
        capability=_vr("CapabilityVerifier", True),
        regression=_vr("HostRegressionVerifier", True),
        policy=_vr("PolicyVerifier", True),
        replay=_vr("ReplayVerifier", True),
        adaptation_present=True,
    )
    assert g2.verdict is Verdict.PASS_ADAPTED


def test_no_replay_caps_at_ready_for_replay() -> None:
    g = decide(
        capability=_vr("CapabilityVerifier", True),
        regression=_vr("HostRegressionVerifier", True),
        policy=_vr("PolicyVerifier", True),
        replay=None,
        adaptation_present=True,
    )
    assert g.verdict is Verdict.READY_FOR_REPLAY  # never a final PASS


def test_capability_failure_is_fail_and_blocked_wins() -> None:
    g = decide(
        capability=_vr("CapabilityVerifier", False),
        regression=_vr("HostRegressionVerifier", True),
        policy=_vr("PolicyVerifier", True),
        replay=_vr("ReplayVerifier", True),
        adaptation_present=False,
    )
    assert g.verdict is Verdict.FAIL
    b = decide(
        capability=_vr("CapabilityVerifier", False),
        regression=_vr("HostRegressionVerifier", False),
        policy=_vr("PolicyVerifier", True),
        replay=None,
        adaptation_present=False,
        blocked_conditions=["arm64 install path failed"],
    )
    assert b.verdict is Verdict.BLOCKED


def test_claim_complete_event_is_ignored(tmp_path: Path) -> None:
    """A trace full of enthusiastic self-claims does not move the gate:
    decide() cannot even see the trace — and the claim scan proves the
    events exist yet the verdict still derives from verifications."""
    trace = tmp_path / "trace.jsonl"
    tw = TraceWriter(trace)
    for _ in range(3):
        tw.append("agent.claim_complete", actor="scripted-fixture", payload={"claim": "all done, PASS!"})
    claims = scan_events(trace, "agent.claim_complete")
    assert len(claims) == 3
    g = decide(
        capability=_vr("CapabilityVerifier", False),
        regression=_vr("HostRegressionVerifier", True),
        policy=_vr("PolicyVerifier", True),
        replay=_vr("ReplayVerifier", True),
        adaptation_present=False,
    )
    assert g.verdict is Verdict.FAIL  # three claims, zero effect
