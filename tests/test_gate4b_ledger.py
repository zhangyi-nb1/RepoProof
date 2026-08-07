"""Gate 4B — Coverage Ledger + redaction scanner + canonical hash."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.domain.models import TaskContract
from repoproof.harness.coverage_ledger import (
    ALLOWED_STATUSES,
    build_requirements,
    contract_public_text,
    initial_ledger_json,
    observation_line,
    summarize,
)
from repoproof.verification.redaction import scan_evidence, scan_file

REPO = Path(__file__).resolve().parent.parent
CONTRACT = REPO / "contracts" / "adopt-chonkie-local-chunking-v3.yaml"
contract, _ = TaskContract.load_frozen(CONTRACT, require_sidecar=True)
REQS = build_requirements(contract)


def test_every_quote_is_verbatim_public_contract_text() -> None:
    public = " ".join(contract_public_text(contract).split())
    assert len(REQS) == 12
    for r in REQS:
        assert r["source_quote"] in public, r["id"]
        assert r["id"] and r["source_field"].startswith("capability.")


def test_manifest_contains_no_hidden_knowledge() -> None:
    """Static purity: no oracle test names, held-out refs, baseline
    failure info, reference adapter, gate or verdict knowledge."""
    blob = (initial_ledger_json(contract) + json.dumps(REQS)).lower()
    forbidden = (
        "test_", "held_out", "heldout", "held-out", "reference_partitions",
        "reference adapter", "31/33", "failed_checks", "completion gate",
        "completion_gate", "verdict", "passed", "verified", "oracle",
    )
    for token in forbidden:
        assert token not in blob, f"manifest leaked {token!r}"


def test_status_whitelist_rejects_self_verification() -> None:
    ledger = {
        "requirements": [
            {"id": "stable-ids", "status": "IMPLEMENTED"},
            {"id": "wrapped-errors", "status": "PASSED"},      # forbidden self-verify
            {"id": "metadata-passthrough", "status": "VERIFIED"},  # forbidden
            {"id": "r1-blank-zero", "status": "SELF_TESTED"},
            {"id": "r2-preserve-oversize", "status": "BLOCKED"},
        ]
    }
    s = summarize(json.dumps(ledger), REQS)
    assert s["statuses"]["stable-ids"] == "IMPLEMENTED"
    assert s["statuses"]["wrapped-errors"] == "UNASSESSED"       # demoted
    assert s["statuses"]["metadata-passthrough"] == "UNASSESSED"  # demoted
    assert s["statuses"]["r1-blank-zero"] == "SELF_TESTED"
    assert s["statuses"]["r2-preserve-oversize"] == "BLOCKED"
    assert s["addressed"] == 2  # only IMPLEMENTED + SELF_TESTED count
    assert "wrapped-errors" in s["unresolved_ids"] and "r2-preserve-oversize" in s["unresolved_ids"]
    assert set(ALLOWED_STATUSES) == {"UNASSESSED", "IMPLEMENTED", "SELF_TESTED", "BLOCKED"}


def test_summarize_handles_garbage_and_missing() -> None:
    s = summarize("not json{{", REQS)
    assert s["addressed"] == 0 and s["parse_note"]
    s2 = summarize(None, REQS)
    assert s2["addressed"] == 0 and s2["total"] == 12


def test_observation_line_math_and_low_budget_quotes() -> None:
    ledger = {"requirements": [{"id": r["id"], "status": "IMPLEMENTED"} for r in REQS[:10]]}
    s = summarize(json.dumps(ledger), REQS)
    line = observation_line(s, low_budget=False, requirements=REQS)
    assert "addressed 10/12" in line
    assert all(rid in line for rid in s["unresolved_ids"])
    assert "verbatim" not in line  # quotes withheld while budget is healthy

    low = observation_line(s, low_budget=True, requirements=REQS)
    for rid in s["unresolved_ids"]:
        quote = next(r["source_quote"] for r in REQS if r["id"] == rid)
        assert quote in low  # public verbatim text attached under low budget


def test_ledger_not_in_completion_gate_or_verifiers() -> None:
    for rel in ("verification/completion_gate.py", "verification/verifiers.py", "harness/policy.py"):
        text = (REPO / "src" / "repoproof" / rel).read_text(encoding="utf-8")
        assert "ledger" not in text.lower(), rel


# ---------------- redaction scanner ----------------


def test_redaction_scanner_blocks_each_class(tmp_path: Path) -> None:
    cases = {
        "mac.txt": "path /Users/someone/x",
        "linux.txt": "path /home/someone/x",
        "win.txt": r"path C:\Users\someone",
        "key.txt": "sk-" + "a" * 24,
        "pem.txt": "-----BEGIN RSA PRIVATE KEY-----",
        "lan.txt": "at 192.168.1.7 and 10.0.0.5",
    }
    for name, content in cases.items():
        (tmp_path / name).write_text(content)
    result = scan_evidence(tmp_path)
    assert not result["ok"]
    kinds = {f["kind"] for f in result["findings"]}
    assert {"host_path_macos", "host_path_linux", "host_path_windows",
            "api_key_openai_style", "private_key_header", "lan_ip"} <= kinds


def test_redaction_scanner_passes_clean_dir(tmp_path: Path) -> None:
    (tmp_path / "ok.json").write_text('{"path": "<repo>/runs/x", "verdict": "FAIL"}')
    assert scan_evidence(tmp_path)["ok"]


def test_committed_evidence_is_clean_now() -> None:
    for d in ("gate3c-real-run", "gate4a-intervention"):
        result = scan_evidence(REPO / "docs" / "evidence" / d)
        assert result["ok"], result["findings"][:3]


@pytest.mark.parametrize("bad", ["/Users/alice/secret", "10.20.30.40"])
def test_scan_file_single(bad: str, tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text(bad)
    assert scan_file(f)
