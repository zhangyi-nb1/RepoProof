"""Gate 6 — third task (frontmatter ingest): preregistered SOLVABLE task.

Same evidence machinery, third capability domain (front-matter
parsing). Solvable-by-design ≠ rigged: the oracle is still
reference-calibrated against the pinned upstream, the negative control
still fails, and nothing in the agent-visible surface leaks the
reference adapter."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repoproof.domain.models import TaskContract
from repoproof.execution.docker_backend import DockerExecutionBackend
from repoproof.harness.coverage_ledger import build_requirements, contract_public_text

REPO = Path(__file__).resolve().parent.parent
UPSTREAM = REPO / "upstream-cache" / "upstream-dc7c0af5466b"
WHEELHOUSE = REPO / "upstream-cache" / "wheelhouse-dc7c0af5466b"
ORACLE = REPO / "oracle" / "adopt-frontmatter-local-ingest-v1"
CONSUMER = REPO / "fixtures" / "consumer_rag_ingest"
CONTRACT = REPO / "contracts" / "adopt-frontmatter-local-ingest-v1.yaml"
USER = f"{os.getuid()}:{os.getgid()}"

docker_ok, _ = DockerExecutionBackend.available()
needs_docker = pytest.mark.skipif(
    not (docker_ok and UPSTREAM.exists() and WHEELHOUSE.exists()),
    reason="docker daemon or pinned caches unavailable",
)


def _run_control(adapter_dir: Path) -> dict:
    from repoproof.runner.calibration import run_oracle_with_adapter

    return run_oracle_with_adapter(
        project_root=REPO, upstream=UPSTREAM, wheelhouse=WHEELHOUSE,
        oracle_dir=ORACLE, adapter_dir=adapter_dir, consumer_dir=CONSUMER, user=USER,
    )


@needs_docker
def test_positive_control_reference_adapter_passes() -> None:
    result = _run_control(REPO / "tests" / "calibration_fm")
    assert result["exit_code"] == 0, result.get("stdout_tail")
    assert result["totals"]["failures"] == 0 and result["totals"]["errors"] == 0
    assert result["totals"]["tests"] == 11


@needs_docker
def test_negative_control_regex_stripper_fails() -> None:
    result = _run_control(REPO / "fixtures" / "negative_control_fm_regex")
    assert result["exit_code"] != 0
    failed = {n["node_id"] for n in result.get("nodes", []) if n["outcome"] != "passed"}
    assert any("test_records_match_pinned_reference" in n for n in failed)


def test_contract_loads_frozen_with_relaxed_token_budgets() -> None:
    contract, _ = TaskContract.load_frozen(CONTRACT, require_sidecar=True)
    assert contract.source_repo.distribution == "python-frontmatter"
    assert contract.acceptance.probe_script == "direct_frontmatter_probe.py"
    # Preregistered relaxation for the solvable task — recorded here so
    # nobody can quietly claim identical budgets across benchmark rows.
    assert contract.budgets.max_input_tokens_total == 400000
    assert contract.budgets.max_output_tokens_total == 40000
    assert contract.budgets.max_agent_steps == 20


def test_ledger_requirements_come_from_contract_field() -> None:
    contract, _ = TaskContract.load_frozen(CONTRACT, require_sidecar=True)
    reqs = build_requirements(contract)
    assert [r["id"] for r in reqs] == [
        "parse-from-upstream", "json-safe-projection", "has-frontmatter-flag",
        "malformed-fence-upstream", "document-order", "wrapped-errors",
        "determinism", "offline-cpu-only",
    ]
    public = contract_public_text(contract)
    for r in reqs:
        assert r["source_quote"] in public
        assert r["status"] == "UNASSESSED"


def test_reference_adapter_not_leaked_to_agent_surface() -> None:
    """The trusted adapter lives only under tests/calibration_fm and
    must not exist inside any tree an agent can read (consumer fixture,
    oracle, probes)."""
    leak_roots = [CONSUMER, ORACLE, REPO / "src" / "repoproof" / "probes"]
    for root in leak_roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "ORACLE CALIBRATION ONLY" not in text, path
            if path.name == "adapter.py":
                pytest.fail(f"adapter.py leaked into agent-visible tree: {path}")


def test_reference_records_are_reference_calibrated() -> None:
    import json

    ref = json.loads((ORACLE / "fixtures" / "reference_records.json").read_text(encoding="utf-8"))
    assert "dc7c0af5" in ref["upstream"]
    fixtures = ref["fixtures"]
    assert set(fixtures) == {"public_documents.json", "held_out_documents.json"}
    # Calibrated upstream truths the oracle depends on:
    d005 = fixtures["public_documents.json"]["d-005-malformed-unclosed"]
    assert d005["has_frontmatter"] is False and d005["metadata"] == {}
    d003 = fixtures["public_documents.json"]["d-003-dates-nested"]
    assert d003["metadata"]["published"] == "2026-01-15"  # P1: date -> ISO string
