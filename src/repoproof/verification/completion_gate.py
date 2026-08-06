"""Independent completion gate — decision table (Gate 2.5 frozen).

Inputs are structured only: four VerificationResults, the FROZEN
AdaptationManifest (adaptation_present is DERIVED, never a caller
bool), missing-external conditions, and a budget-exhaustion marker.
``claim_complete`` events are trace data the gate cannot even see.

Decision table (C=capability, R=regression, P=policy):

| missing_external | budget_exhausted | C∧R∧P | replay                    | verdict |
|---|---|---|---|---|
| yes | -   | -     | -                          | BLOCKED (missing external facts/keys/resources/authorization) |
| no  | -   | true  | none                       | READY_FOR_REPLAY (never a final PASS) |
| no  | -   | true  | passed, clean_adoption     | PASS_ADAPTED if adaptation.present else PASS_DIRECT |
| no  | -   | true  | passed, baseline_repro     | READY_FOR_REPLAY (reproduction cannot ground a PASS) |
| no  | -   | true  | failed                     | FAIL (replay divergence) |
| no  | yes | false | -                          | FAIL + BUDGET_EXHAUSTED (unmet hard goals at budget end) |
| no  | no  | false | -                          | FAIL (verifier reasons) |

PARTIAL is reserved for contracts that declare soft goals; no automatic
path emits it in Gate 2.x (pinned by tests).
"""

from __future__ import annotations

from repoproof.domain.models import (
    AdaptationManifest,
    GateResult,
    Verdict,
    VerificationResult,
)
from repoproof.verification.verifiers import REPLAY_MODE_CLEAN


def decide(
    *,
    capability: VerificationResult,
    regression: VerificationResult,
    policy: VerificationResult,
    replay: VerificationResult | None,
    adaptation: AdaptationManifest | None,
    missing_external: list[str] | None = None,
    budget_exhausted: str | None = None,
) -> GateResult:
    adaptation_present = bool(adaptation and adaptation.present)
    missing = missing_external or []

    def result(verdict: Verdict, reasons: list[str]) -> GateResult:
        return GateResult(
            verdict=verdict,
            reasons=reasons,
            capability_passed=capability.passed,
            regression_passed=regression.passed,
            policy_passed=policy.passed,
            replay_passed=replay.passed if replay else None,
            adaptation_present=adaptation_present,
        )

    if missing:
        return result(Verdict.BLOCKED, [f"blocked (external): {m}" for m in missing])

    all_static = capability.passed and regression.passed and policy.passed

    if all_static:
        if replay is None:
            return result(
                Verdict.READY_FOR_REPLAY,
                ["capability+regression+policy passed; clean-room replay pending"],
            )
        if replay.passed and replay.extra.get("mode") == REPLAY_MODE_CLEAN:
            verdict = Verdict.PASS_ADAPTED if adaptation_present else Verdict.PASS_DIRECT
            return result(verdict, ["capability, host regression, policy and clean_adoption replay all passed"])
        if replay.passed:
            return result(
                Verdict.READY_FOR_REPLAY,
                [
                    f"replay mode={replay.extra.get('mode')} reproduces outcomes but only a "
                    "clean_adoption replay can ground a final PASS"
                ],
            )
        return result(Verdict.FAIL, [f"ReplayVerifier: {replay.detail}"])

    reasons = [f"{r.verifier}: {r.detail}" for r in (capability, regression, policy) if not r.passed]
    if replay is not None and not replay.passed:
        reasons.append(f"ReplayVerifier: {replay.detail}")
    if budget_exhausted:
        reasons.insert(0, f"BUDGET_EXHAUSTED: {budget_exhausted}")
    return result(Verdict.FAIL, reasons or ["unspecified verification failure"])
