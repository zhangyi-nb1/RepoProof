"""Gate 2.5 decision table — pinned.

Core promises:
  1. verdicts derive ONLY from structured verification results;
  2. claim_complete events (agent or scripted) change nothing;
  3. no clean-room replay -> never a final PASS;
  4. only a clean_adoption replay grounds a PASS — reproducing a
     failing baseline does not;
  5. budget exhaustion with unmet hard goals is FAIL (BUDGET_EXHAUSTED),
     never BLOCKED; BLOCKED is reserved for missing external inputs;
  6. adaptation_present derives from the frozen AdaptationManifest;
  7. PARTIAL is never auto-emitted in Gate 2.x.
"""

from pathlib import Path

from repoproof.domain.models import AdaptationManifest, Verdict, VerificationResult
from repoproof.harness.trace import TraceWriter, scan_events
from repoproof.verification.completion_gate import decide
from repoproof.verification.verifiers import REPLAY_MODE_BASELINE, REPLAY_MODE_CLEAN


def _vr(name: str, passed: bool) -> VerificationResult:
    return VerificationResult(verifier=name, passed=passed, detail="t")


def _replay(passed: bool, mode: str) -> VerificationResult:
    return VerificationResult(verifier="ReplayVerifier", passed=passed, detail="t", extra={"mode": mode})


def _adaptation(files: int) -> AdaptationManifest:
    return AdaptationManifest(total_files=files, total_lines=files * 10, tree_root_sha256="x", frozen=True)


def _decide(c=True, r=True, p=True, replay=None, adaptation=None, missing=None, budget=None):
    return decide(
        capability=_vr("CapabilityVerifier", c),
        regression=_vr("HostRegressionVerifier", r),
        policy=_vr("PolicyVerifier", p),
        replay=replay,
        adaptation=adaptation,
        missing_external=missing,
        budget_exhausted=budget,
    )


def test_pass_direct_vs_adapted_requires_clean_adoption_replay() -> None:
    assert _decide(replay=_replay(True, REPLAY_MODE_CLEAN)).verdict is Verdict.PASS_DIRECT
    assert (
        _decide(replay=_replay(True, REPLAY_MODE_CLEAN), adaptation=_adaptation(2)).verdict
        is Verdict.PASS_ADAPTED
    )


def test_baseline_reproduction_replay_never_grounds_pass() -> None:
    g = _decide(replay=_replay(True, REPLAY_MODE_BASELINE), adaptation=_adaptation(2))
    assert g.verdict is Verdict.READY_FOR_REPLAY
    assert "clean_adoption" in g.reasons[0]


def test_no_replay_caps_at_ready_for_replay() -> None:
    assert _decide(replay=None, adaptation=_adaptation(1)).verdict is Verdict.READY_FOR_REPLAY


def test_replay_divergence_is_fail() -> None:
    assert _decide(replay=_replay(False, REPLAY_MODE_CLEAN)).verdict is Verdict.FAIL


def test_capability_failure_is_fail() -> None:
    assert _decide(c=False, replay=_replay(True, REPLAY_MODE_CLEAN)).verdict is Verdict.FAIL


def test_budget_exhausted_with_unmet_goals_is_fail_not_blocked() -> None:
    g = _decide(c=False, budget="max_agent_steps (21 > 20)")
    assert g.verdict is Verdict.FAIL
    assert g.reasons[0].startswith("BUDGET_EXHAUSTED")


def test_blocked_reserved_for_missing_external() -> None:
    g = _decide(c=False, missing=["docker unavailable", "api key not provided"])
    assert g.verdict is Verdict.BLOCKED
    assert all(reason.startswith("blocked (external)") for reason in g.reasons)


def test_adaptation_present_derived_from_manifest() -> None:
    empty = AdaptationManifest(total_files=0, tree_root_sha256="e", frozen=True)
    g = _decide(replay=_replay(True, REPLAY_MODE_CLEAN), adaptation=empty)
    assert g.verdict is Verdict.PASS_DIRECT  # zero frozen files == no adaptation
    unfrozen = AdaptationManifest(total_files=3, tree_root_sha256="e", frozen=False)
    g2 = _decide(replay=_replay(True, REPLAY_MODE_CLEAN), adaptation=unfrozen)
    assert g2.verdict is Verdict.PASS_DIRECT  # unfrozen zone can't claim adaptation


def test_partial_never_auto_emitted() -> None:
    outcomes = set()
    for c in (True, False):
        for r in (True, False):
            for p in (True, False):
                replays = (None, _replay(True, REPLAY_MODE_CLEAN),
                           _replay(True, REPLAY_MODE_BASELINE), _replay(False, REPLAY_MODE_CLEAN))
                for replay in replays:
                    for budget in (None, "steps"):
                        outcomes.add(_decide(c=c, r=r, p=p, replay=replay, budget=budget).verdict)
    assert Verdict.PARTIAL not in outcomes


def test_claim_complete_event_is_ignored(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    tw = TraceWriter(trace)
    for _ in range(3):
        tw.append("agent.claim_complete", actor="scripted-fixture", payload={"claim": "all done, PASS!"})
    assert len(scan_events(trace, "agent.claim_complete")) == 3
    assert _decide(c=False, replay=_replay(True, REPLAY_MODE_CLEAN)).verdict is Verdict.FAIL
