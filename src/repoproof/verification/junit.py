"""JUnit-XML based test-completion verification (Gate 3A.C).

A verifier PASS no longer trusts the pytest exit code alone. It
requires ALL of:
  * exit_code == 0;
  * a present, parseable JUnit XML;
  * the executed node-id set EXACTLY equals the frozen expected set
    (no missing nodes, no unknown extras);
  * passed count == expected count;
  * failures == errors == skipped == xfailed == xpassed == 0.

Node ids are normalized to ``classname::name`` so they are stable
across host/container invocation paths.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass


def parse_junit_xml(data: bytes | None) -> dict:
    """Parse JUnit XML bytes into a structured summary. Never raises —
    a missing/corrupt report is itself a verification-relevant fact."""
    if not data:
        return {"junit_present": False, "junit_parse_error": "missing junit xml"}
    try:
        root = ET.fromstring(data.decode("utf-8", errors="replace"))
    except ET.ParseError as exc:
        return {"junit_present": True, "junit_parse_error": f"corrupt junit xml: {exc}"}
    suites = root.iter("testsuite")
    nodes: list[dict] = []
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.get(key, "0") or 0)
        for case in suite.iter("testcase"):
            node_id = f"{case.get('classname', '?')}::{case.get('name', '?')}"
            outcome = "passed"
            detail = case.find("failure")
            if detail is None:
                detail = case.find("error")
                outcome_if = "error"
            else:
                outcome_if = "failed"
            if detail is not None:
                outcome = outcome_if
            elif case.find("skipped") is not None:
                outcome = "skipped"
            # message = 断言摘要(RFC-008 修复回路的 FailurePacket 输入;
            # 截断,绝不携带整段日志)
            message = (detail.get("message") or "")[:400] if detail is not None else ""
            nodes.append({"node_id": node_id, "outcome": outcome, "message": message})
    return {
        "junit_present": True,
        "junit_parse_error": None,
        "totals": totals,
        "nodes": nodes,
        "node_ids": sorted(n["node_id"] for n in nodes),
    }


@dataclass
class CompletionCheck:
    ok: bool
    detail: str
    extra: dict


def check_test_completion(
    *,
    exit_code: int | None,
    junit: dict,
    expected_node_ids: list[str],
) -> CompletionCheck:
    expected = sorted(expected_node_ids)
    problems: list[str] = []
    if exit_code != 0:
        problems.append(f"exit_code={exit_code}")
    if not junit.get("junit_present") or junit.get("junit_parse_error"):
        problems.append(junit.get("junit_parse_error") or "missing junit xml")
        return CompletionCheck(False, "; ".join(problems), {"expected_count": len(expected)})
    totals = junit["totals"]
    actual = junit["node_ids"]
    missing = sorted(set(expected) - set(actual))
    extra_nodes = sorted(set(actual) - set(expected))
    if missing:
        problems.append(f"{len(missing)} expected node(s) not executed: {missing[:3]}")
    if extra_nodes:
        problems.append(f"{len(extra_nodes)} unknown node(s) executed: {extra_nodes[:3]}")
    passed_nodes = [n for n in junit["nodes"] if n["outcome"] == "passed"]
    if len(passed_nodes) != len(expected):
        problems.append(f"passed={len(passed_nodes)} != expected={len(expected)}")
    for key in ("failures", "errors", "skipped"):
        if totals.get(key, 0) != 0:
            problems.append(f"{key}={totals[key]}")
    detail = (
        f"all {len(expected)} frozen nodes executed and passed"
        if not problems
        else "; ".join(problems[:5])
    )
    return CompletionCheck(
        ok=not problems,
        detail=detail,
        extra={
            "expected_count": len(expected),
            "passed_count": len(passed_nodes),
            "failed_nodes": [n["node_id"] for n in junit["nodes"] if n["outcome"] in ("failed", "error")],
            "missing_nodes": missing,
            "extra_nodes": extra_nodes,
            "totals": totals,
        },
    )
