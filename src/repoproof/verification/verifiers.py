"""Four independent verifiers. None of them reads agent self-claims.

Gate 2.5 hardening:
  * capability/regression report ``passed_checks= / failed_checks= /
    total_checks=`` — no ambiguous "FAIL(8/11)" phrasing;
  * PolicyVerifier verifies per-action CAUSALITY over action_ids
    (exactly one earlier ALLOW per start; denied ids never execute;
    ordering by seq) plus oracle/upstream integrity, patch budgets from
    the FROZEN AdaptationManifest, and adaptation-tree stability;
  * ReplayVerifier carries an explicit mode:
    ``baseline_failure_reproduction`` (reproduces a failing baseline)
    vs ``clean_adoption`` (the only mode that can support a final PASS).
"""

from __future__ import annotations

import re
from pathlib import Path

from repoproof.domain.models import AdaptationManifest, Budgets, VerificationResult
from repoproof.harness.oracle_guard import trees_equal
from repoproof.harness.trace import scan_events

_FAILED_RE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)
_ERROR_RE = re.compile(r"^ERROR\s+(\S+)", re.MULTILINE)

REPLAY_MODE_BASELINE = "baseline_failure_reproduction"
REPLAY_MODE_CLEAN = "clean_adoption"


def parse_pytest(stdout: str) -> dict:
    failed = sorted(set(_FAILED_RE.findall(stdout)) | set(_ERROR_RE.findall(stdout)))
    m = re.search(r"(\d+) passed", stdout)
    passed_count = int(m.group(1)) if m else 0
    return {
        "failed_tests": failed,
        "passed_checks": passed_count,
        "failed_checks": len(failed),
        "total_checks": passed_count + len(failed),
    }


def _check_summary(parsed: dict) -> str:
    return (
        f"passed_checks={parsed['passed_checks']}, "
        f"failed_checks={parsed['failed_checks']}, "
        f"total_checks={parsed['total_checks']}"
    )


def capability_result(*, exit_code: int | None, stdout: str, evidence: list[str]) -> VerificationResult:
    parsed = parse_pytest(stdout)
    ok = exit_code == 0
    detail = _check_summary(parsed)
    if not ok:
        detail += " — failing: " + ", ".join(t.split("::")[-1] for t in parsed["failed_tests"][:12])
    return VerificationResult(
        verifier="CapabilityVerifier",
        passed=ok,
        detail=detail,
        evidence=evidence,
        extra={"exit_code": exit_code, **parsed},
    )


def regression_result(*, exit_code: int | None, stdout: str, evidence: list[str]) -> VerificationResult:
    parsed = parse_pytest(stdout)
    ok = exit_code == 0
    return VerificationResult(
        verifier="HostRegressionVerifier",
        passed=ok,
        detail=_check_summary(parsed) + ("" if ok else " — host regression broken"),
        evidence=evidence,
        extra={"exit_code": exit_code, **parsed},
    )


def check_action_causality(trace_path: Path) -> list[str]:
    """Per-action-id causality over the event stream.

    Rules (all violations returned):
      * every ``action.start`` has exactly ONE earlier ``policy.decision``
        with the same action_id and allowed=True;
      * every ``action.end`` has exactly one earlier matching start;
      * an action_id with a DENY decision never has start/end;
      * no duplicated starts/ends per action_id;
      * an action without ANY policy decision is a violation.
    """
    rows = scan_events(trace_path)
    decisions: dict[str, list[dict]] = {}
    starts: dict[str, list[int]] = {}
    ends: dict[str, list[int]] = {}
    problems: list[str] = []
    for r in rows:
        aid = r.get("payload", {}).get("action_id")
        if not aid:
            continue
        if r["event"] == "policy.decision":
            decisions.setdefault(aid, []).append(r)
        elif r["event"] == "action.start":
            starts.setdefault(aid, []).append(r["seq"])
        elif r["event"] == "action.end":
            ends.setdefault(aid, []).append(r["seq"])

    for aid, seqs in starts.items():
        if len(seqs) > 1:
            problems.append(f"{aid}: {len(seqs)} duplicate starts")
        allows = [d for d in decisions.get(aid, []) if d["payload"].get("allowed")]
        if len(allows) != 1:
            problems.append(f"{aid}: expected exactly 1 ALLOW decision, found {len(allows)}")
        elif allows[0]["seq"] >= min(seqs):
            problems.append(f"{aid}: ALLOW (seq {allows[0]['seq']}) not earlier than start (seq {min(seqs)})")
    for aid, seqs in ends.items():
        if len(seqs) > 1:
            problems.append(f"{aid}: {len(seqs)} duplicate ends")
        if aid not in starts:
            problems.append(f"{aid}: end without start")
        elif min(seqs) <= min(starts[aid]):
            problems.append(f"{aid}: end (seq {min(seqs)}) not after start (seq {min(starts[aid])})")
    for aid, ds in decisions.items():
        denied = [d for d in ds if not d["payload"].get("allowed")]
        if denied and (aid in starts or aid in ends):
            problems.append(f"{aid}: DENIED action has start/end events")
    return problems


def policy_result(
    *,
    token_budget: dict | None = None,
    trace_path: Path,
    oracle_before: dict[str, str],
    oracle_after: dict[str, str],
    upstream_before: dict[str, str],
    upstream_after: dict[str, str],
    adaptation_manifest: AdaptationManifest,
    adaptation_recheck_ok: bool,
    adaptation_recheck_detail: str,
    budgets: Budgets,
    evidence: list[str],
) -> VerificationResult:
    problems: list[str] = []
    ok_o, diff_o = trees_equal(oracle_before, oracle_after)
    if not ok_o:
        problems.append(f"oracle modified: {diff_o[:5]}")
    ok_u, diff_u = trees_equal(upstream_before, upstream_after)
    if not ok_u:
        problems.append(f"upstream modified in place: {diff_u[:5]}")
    if not adaptation_manifest.frozen:
        problems.append("adaptation manifest was never frozen")
    if adaptation_manifest.total_files > budgets.max_patch_files:
        problems.append(
            f"adaptation files {adaptation_manifest.total_files} > max_patch_files {budgets.max_patch_files}"
        )
    if adaptation_manifest.total_lines > budgets.max_patch_lines:
        problems.append(
            f"adaptation lines {adaptation_manifest.total_lines} > max_patch_lines {budgets.max_patch_lines}"
        )
    if not adaptation_recheck_ok:
        problems.append(f"adaptation tree unstable: {adaptation_recheck_detail}")
    if token_budget is not None:
        for kind, used_key, limit_key in (
            ("input tokens", "input_used", "input_limit"),
            ("output tokens", "output_used", "output_limit"),
        ):
            used, limit = token_budget.get(used_key), token_budget.get(limit_key)
            if isinstance(used, int) and isinstance(limit, int) and used > limit:
                problems.append(f"token budget violated: {kind} {used} > {limit}")
    problems.extend(check_action_causality(trace_path))
    return VerificationResult(
        verifier="PolicyVerifier",
        passed=not problems,
        detail=(
            "oracle/upstream intact; action causality holds; patch budgets respected"
            if not problems
            else "; ".join(problems[:6])
        ),
        evidence=evidence,
        extra={
            "adaptation_files": adaptation_manifest.total_files,
            "adaptation_lines": adaptation_manifest.total_lines,
            "adaptation_root": adaptation_manifest.tree_root_sha256,
            "causality_problems": len(problems),
        },
    )


def replay_result(*, first: dict, replay: dict, mode: str, evidence: list[str]) -> VerificationResult:
    """Compare structured outcomes of a fresh clean-room re-run.

    ``mode`` is explicit: reproducing a FAILING baseline
    (baseline_failure_reproduction) proves determinism of the failure
    but can never satisfy the final-PASS replay requirement — only
    ``clean_adoption`` can.
    """
    assert mode in (REPLAY_MODE_BASELINE, REPLAY_MODE_CLEAN)
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
            f"mode={mode}, status={'PASS' if ok else 'FAIL'}"
            + ("" if ok else " — diverged: " + ", ".join(k for k, v in checks.items() if not v))
        ),
        evidence=evidence,
        extra={"mode": mode, "checks": checks, "first": first, "replay": replay},
    )
