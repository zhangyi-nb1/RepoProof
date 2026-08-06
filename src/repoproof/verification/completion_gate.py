"""Independent completion gate.

The ONLY producer of a final verdict. Consumes structured
VerificationResults exclusively — an agent (or scripted fixture)
``claim_complete`` event is trace data, never an input here. That
property is pinned by tests/test_completion_gate.py.
"""

from __future__ import annotations

from repoproof.domain.models import GateResult, Verdict, VerificationResult


def decide(
    *,
    capability: VerificationResult,
    regression: VerificationResult,
    policy: VerificationResult,
    replay: VerificationResult | None,
    adaptation_present: bool,
    blocked_conditions: list[str] | None = None,
) -> GateResult:
    reasons: list[str] = []
    blocked = blocked_conditions or []
    if blocked:
        return GateResult(
            verdict=Verdict.BLOCKED,
            reasons=[f"blocked: {b}" for b in blocked],
            capability_passed=capability.passed,
            regression_passed=regression.passed,
            policy_passed=policy.passed,
            replay_passed=replay.passed if replay else None,
            adaptation_present=adaptation_present,
        )

    all_static = capability.passed and regression.passed and policy.passed

    if all_static and replay is None:
        # Never a final PASS without a clean-room replay.
        return GateResult(
            verdict=Verdict.READY_FOR_REPLAY,
            reasons=["capability+regression+policy passed; clean-room replay pending"],
            capability_passed=True,
            regression_passed=True,
            policy_passed=True,
            replay_passed=None,
            adaptation_present=adaptation_present,
        )

    if all_static and replay is not None and replay.passed:
        verdict = Verdict.PASS_ADAPTED if adaptation_present else Verdict.PASS_DIRECT
        return GateResult(
            verdict=verdict,
            reasons=["capability, host regression, policy and clean-room replay all passed"],
            capability_passed=True,
            regression_passed=True,
            policy_passed=True,
            replay_passed=True,
            adaptation_present=adaptation_present,
        )

    for r in (capability, regression, policy):
        if not r.passed:
            reasons.append(f"{r.verifier}: {r.detail}")
    if replay is not None and not replay.passed:
        reasons.append(f"ReplayVerifier: {replay.detail}")

    return GateResult(
        verdict=Verdict.FAIL,
        reasons=reasons or ["unspecified verification failure"],
        capability_passed=capability.passed,
        regression_passed=regression.passed,
        policy_passed=policy.passed,
        replay_passed=replay.passed if replay else None,
        adaptation_present=adaptation_present,
    )
