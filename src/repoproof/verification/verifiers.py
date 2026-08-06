"""Four independent verifiers. None of them reads agent self-claims.

CapabilityVerifier / HostRegressionVerifier run the contract's frozen
pytest commands inside the network-none run container and parse ONLY
structured signals (exit code + failed-test ids from pytest output).
PolicyVerifier checks oracle/upstream integrity and policy events.
ReplayVerifier compares a fresh clean-room re-run against the first
run's structured outcome.
"""

from __future__ import annotations

import re
from pathlib import Path

from repoproof.domain.models import VerificationResult
from repoproof.harness.oracle_guard import trees_equal
from repoproof.harness.trace import scan_events

_FAILED_RE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)
_ERROR_RE = re.compile(r"^ERROR\s+(\S+)", re.MULTILINE)


def parse_pytest(stdout: str) -> dict:
    failed = sorted(set(_FAILED_RE.findall(stdout)) | set(_ERROR_RE.findall(stdout)))
    m = re.search(r"(\d+) passed", stdout)
    passed_count = int(m.group(1)) if m else 0
    return {"failed_tests": failed, "passed_count": passed_count}


def capability_result(*, exit_code: int | None, stdout: str, evidence: list[str]) -> VerificationResult:
    parsed = parse_pytest(stdout)
    ok = exit_code == 0
    return VerificationResult(
        verifier="CapabilityVerifier",
        passed=ok,
        detail=(
            "capability tests passed"
            if ok
            else f"{len(parsed['failed_tests'])} capability check(s) failed: "
            + ", ".join(parsed["failed_tests"][:12])
        ),
        evidence=evidence,
        extra={"exit_code": exit_code, **parsed},
    )


def regression_result(*, exit_code: int | None, stdout: str, evidence: list[str]) -> VerificationResult:
    parsed = parse_pytest(stdout)
    ok = exit_code == 0
    return VerificationResult(
        verifier="HostRegressionVerifier",
        passed=ok,
        detail="host fixture regression intact" if ok else f"host regression broken: {parsed['failed_tests'][:8]}",
        evidence=evidence,
        extra={"exit_code": exit_code, **parsed},
    )


def policy_result(
    *,
    trace_path: Path,
    oracle_before: dict[str, str],
    oracle_after: dict[str, str],
    upstream_before: dict[str, str],
    upstream_after: dict[str, str],
    adaptation_files: list[str],
    max_patch_files: int,
    evidence: list[str],
) -> VerificationResult:
    problems: list[str] = []
    ok_o, diff_o = trees_equal(oracle_before, oracle_after)
    if not ok_o:
        problems.append(f"oracle modified: {diff_o[:5]}")
    ok_u, diff_u = trees_equal(upstream_before, upstream_after)
    if not ok_u:
        problems.append(f"upstream modified in place: {diff_u[:5]}")
    if len(adaptation_files) > max_patch_files:
        problems.append(f"adaptation files {len(adaptation_files)} > budget {max_patch_files}")
    denied = [
        e
        for e in scan_events(trace_path, "policy.decision")
        if not e["payload"].get("allowed", True)
    ]
    executed_after_denial = [
        e for e in denied if e["payload"].get("executed_anyway", False)
    ]
    if executed_after_denial:
        problems.append(f"{len(executed_after_denial)} denied action(s) executed anyway")
    return VerificationResult(
        verifier="PolicyVerifier",
        passed=not problems,
        detail="oracle/upstream intact; no denied action executed" if not problems else "; ".join(problems),
        evidence=evidence,
        extra={
            "denied_count": len(denied),
            "adaptation_files": adaptation_files,
        },
    )


def replay_result(*, first: dict, replay: dict, evidence: list[str]) -> VerificationResult:
    """Compare structured outcomes of the clean-room replay to run #1.

    Volatile fields (uuid ids, timings) are already stripped from the
    normalized probe digest upstream of this comparison.
    """
    checks = {
        "capability_failed_tests_equal": first.get("capability_failed") == replay.get("capability_failed"),
        "capability_exit_equal": first.get("capability_exit") == replay.get("capability_exit"),
        "regression_exit_equal": first.get("regression_exit") == replay.get("regression_exit"),
        "probe_normalized_sha_equal": first.get("probe_normalized_sha") == replay.get("probe_normalized_sha"),
    }
    ok = all(checks.values())
    return VerificationResult(
        verifier="ReplayVerifier",
        passed=ok,
        detail=(
            "clean-room replay reproduced run #1 outcomes"
            if ok
            else "replay diverged: " + ", ".join(k for k, v in checks.items() if not v)
        ),
        evidence=evidence,
        extra={"checks": checks, "first": first, "replay": replay},
    )
