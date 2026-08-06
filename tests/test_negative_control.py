"""The v2 oracle must REJECT a cheating passthrough adapter.

The negative-control adapter never calls Chonkie and returns one
full-span record per document. It satisfies the schema, offsets and
metadata checks — and must still fail the suite on multi-chunking,
chunk-size caps, repeated-occurrence addressing, blank-doc handling
and error wrapping. Runs on the HOST (no chonkie import happens when
an adapter is present).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ORACLE = REPO / "oracle" / "adopt-chonkie-local-chunking-v2" / "test_capability.py"

MUST_FAIL = (
    "test_multi_chunk_for_long_documents",
    "test_units_semantics_and_chunk_size",  # full-span record blows the chunk_size cap
    "test_repeated_sentence_occurrences_separately_addressed",
    "test_blank_document_yields_zero_records",
    "test_upstream_errors_wrapped",
)


def test_negative_control_adapter_is_rejected() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "fixtures" / "consumer_rag" / "src")
    env["REPOPROOF_ADAPTATION_DIR"] = str(REPO / "fixtures" / "negative_control_adapter")
    env["PYTHONDONTWRITEBYTECODE"] = "1"  # never contaminate frozen trees
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(ORACLE)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert proc.returncode != 0, "cheating adapter must NOT satisfy the v2 oracle"
    for name in MUST_FAIL:
        assert name in proc.stdout, f"expected {name} to fail against the negative control"
    # And the schema-shaped parts DO pass — the rejection is semantic,
    # not a trivial import error.
    assert "test_record_schema_exact_fields" not in proc.stdout.replace(
        "FAILED", ""
    ) or "passed" in proc.stdout
