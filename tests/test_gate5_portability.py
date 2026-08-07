"""Gate 5 — second-repo portability: rank_bm25 oracle controls.

Proves the v3 evidence machinery transfers: reference calibration,
positive/negative controls and the freeze pipeline all run against a
DIFFERENT capability domain (BM25 ranking) with contract-driven
distribution/probe/ledger sources and zero verifier/gate changes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repoproof.domain.models import TaskContract
from repoproof.execution.docker_backend import DockerExecutionBackend
from repoproof.harness.coverage_ledger import build_requirements, contract_public_text

REPO = Path(__file__).resolve().parent.parent
UPSTREAM = REPO / "upstream-cache" / "upstream-47aa3ddf8dc1"
WHEELHOUSE = REPO / "upstream-cache" / "wheelhouse-47aa3ddf8dc1"
ORACLE = REPO / "oracle" / "adopt-rank-bm25-local-search-v1"
CONSUMER = REPO / "fixtures" / "consumer_rag_search"
CONTRACT = REPO / "contracts" / "adopt-rank-bm25-local-search-v1.yaml"
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
    result = _run_control(REPO / "tests" / "calibration_bm25")
    assert result["exit_code"] == 0, result.get("stdout_tail")
    assert result["totals"]["failures"] == 0 and result["totals"]["errors"] == 0
    assert result["totals"]["tests"] == 12


@needs_docker
def test_negative_control_wordcount_ranker_fails() -> None:
    result = _run_control(REPO / "fixtures" / "negative_control_bm25_wordcount")
    assert result["exit_code"] != 0
    failed = {n["node_id"] for n in result.get("nodes", []) if n["outcome"] != "passed"}
    assert any("test_rankings_match_pinned_reference" in n for n in failed)


def test_ledger_requirements_come_from_contract_field() -> None:
    contract, _ = TaskContract.load_frozen(CONTRACT, require_sidecar=True)
    reqs = build_requirements(contract)
    assert len(reqs) == 9
    public = " ".join(contract_public_text(contract).split())
    for r in reqs:
        assert r["source_quote"] in public
    blob = str(reqs).lower()
    for tok in ("test_", "oracle", "held", "reference_rankings", "verdict", "passed"):
        assert tok not in blob


def test_bm25_reference_adapter_not_leaked() -> None:
    marker = "POSITIVE CONTROL"
    for root in (REPO / "fixtures" / "consumer_rag_search", REPO / "src"):
        for p in root.rglob("*.py"):
            assert marker not in p.read_text(encoding="utf-8", errors="replace"), p
