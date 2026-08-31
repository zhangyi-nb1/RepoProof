"""Frozen M6.2 qualification scope and no-case-specific-Core guard."""

from __future__ import annotations

from pathlib import Path

import yaml

from repoproof.persistence.product_incidents import scan_core_for_case_identifiers

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = REPO_ROOT / "docs" / "m6_2_workspace_bundle_qualification.yaml"
CORE = REPO_ROOT / "src" / "repoproof"


def _protocol() -> dict:
    document = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_protocol_stops_before_unfrozen_wheels_or_real_model_execution() -> None:
    document = _protocol()
    cases = document["cases"]

    assert document["status"] == "BLOCKED_BEFORE_EXECUTION"
    assert document["wheelhouse_freeze"]["status"] == "PENDING_MATERIALIZATION"
    assert document["wheelhouse_freeze"]["execution_must_stop_while_pending"] is True
    assert document["execution_policy"]["real_model_execution_authorized"] is False
    assert document["execution_policy"]["pushing_or_publishing_authorized"] is False
    assert document["execution_policy"]["fixed_agent_backend"] == "mini-swe"
    assert [case["order"] for case in cases] == list(range(9))
    assert [case["kind"] for case in cases] == [
        "expected_rejection",
        "baseline",
        "baseline",
        "complex",
        "complex",
        "complex",
        "complex",
        "complex",
        "complex",
    ]
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert len({case["resolved_commit"] for case in cases}) == len(cases)


def test_preregistered_case_identities_do_not_enter_new_generic_core() -> None:
    """Freeze old Lab references while rejecting any new M6.2 case coupling.

    Two upstream names already occur in the historical host-adaptation/Lab code
    before M6.2.  Listing those exact files makes the inherited debt visible and
    prevents the workspace implementation from adding another occurrence.
    """

    document = _protocol()
    cases = document["cases"]
    distribution_names = [
        case.get("distribution")
        or case["repository"].rstrip("/").rsplit("/", 1)[-1]
        for case in cases
    ]
    expected_historical_hits = {
        "browser-use": [
            "execution/upstream_sidecar.py",
            "harness/host_guard.py",
            "runner/host_guided.py",
            "ui/services/live_run.py",
        ],
        "pdfplumber": [
            "execution/import_hook.py",
            "harness/host_guard.py",
        ],
    }

    for identifier in distribution_names:
        assert scan_core_for_case_identifiers(CORE, [identifier]) == (
            expected_historical_hits.get(identifier, [])
        )

    forbidden_exact_identities = [
        case["case_id"] for case in cases
    ] + [case["resolved_commit"] for case in cases]
    assert scan_core_for_case_identifiers(CORE, forbidden_exact_identities) == []

    new_workspace_modules = (
        CORE / "execution" / "workspace_bundle.py",
        CORE / "verification" / "workspace_semantic.py",
        CORE / "adoption" / "assembly" / "workspace_tool_assembler.py",
        CORE / "adoption" / "intake" / "workspace_fixtures.py",
    )
    all_case_names = tuple(distribution_names) + tuple(forbidden_exact_identities)
    for path in new_workspace_modules:
        source = path.read_text(encoding="utf-8").casefold()
        assert all(identifier.casefold() not in source for identifier in all_case_names)
