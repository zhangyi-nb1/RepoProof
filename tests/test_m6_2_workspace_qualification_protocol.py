"""Frozen M6.2 qualification scope and no-case-specific-Core guard."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

from repoproof.persistence.product_incidents import scan_core_for_case_identifiers

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = REPO_ROOT / "docs" / "m6_2_workspace_bundle_qualification.yaml"
PROTOCOL_V2 = (
    REPO_ROOT / "docs" / "m6_2_workspace_bundle_qualification_v2.yaml"
)
CORE = REPO_ROOT / "src" / "repoproof"


def _protocol() -> dict:
    document = yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _protocol_v2() -> dict:
    document = yaml.safe_load(PROTOCOL_V2.read_text(encoding="utf-8"))
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


def test_v2_protocol_freezes_exact_wheel_bytes_before_formal_execution() -> None:
    first = _protocol()
    frozen = _protocol_v2()
    payload = PROTOCOL_V2.read_bytes()
    expected_sidecar = (
        PROTOCOL_V2.with_suffix(PROTOCOL_V2.suffix + ".sha256")
        .read_text(encoding="utf-8")
        .split()[0]
    )

    assert hashlib.sha256(payload).hexdigest() == expected_sidecar
    assert frozen["status"] == "FROZEN_READY"
    assert frozen["supersedes_protocol_id"] == first["protocol_id"]
    assert frozen["execution_policy"]["real_model_execution_authorized"] is True
    assert frozen["execution_policy"]["fixed_drafter_backend"] == (
        "litellm_api_gateway"
    )
    assert frozen["execution_policy"]["fixed_agent_backend"] == "mini-swe"
    assert frozen["wheelhouse_freeze"]["status"] == "FROZEN"
    assert frozen["wheelhouse_freeze"][
        "execution_must_consume_preregistered_bytes"
    ] is True
    assert [case["case_id"] for case in frozen["cases"]] == [
        case["case_id"] for case in first["cases"]
    ]
    assert [case["resolved_commit"] for case in frozen["cases"]] == [
        case["resolved_commit"] for case in first["cases"]
    ]

    wheel_cases = frozen["wheelhouse_freeze"]["cases"]
    assert [case["case_id"] for case in wheel_cases] == [
        case["case_id"] for case in frozen["cases"][1:]
    ]
    for case in wheel_cases:
        wheels = case["wheels"]
        names = [wheel["filename"] for wheel in wheels]
        assert wheels and len(names) == len(set(names)) == case["wheel_count"]
        assert sum(wheel["size"] for wheel in wheels) == case["total_bytes"]
        assert all(
            Path(wheel["filename"]).name == wheel["filename"]
            and wheel["filename"].endswith(".whl")
            and wheel["size"] > 0
            and re.fullmatch(r"[0-9a-f]{64}", wheel["sha256"])
            for wheel in wheels
        )
        wheel_hashes = {
            wheel["filename"]: wheel["sha256"] for wheel in wheels
        }
        root = hashlib.sha256(
            json.dumps(wheel_hashes, sort_keys=True).encode()
        ).hexdigest()
        assert root == case["root"]


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
