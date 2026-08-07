"""PUBLIC contract tests — agent-visible and agent-runnable.

Compiled from the HARD requirements' public text and the public truth
table. These are NOT the acceptance oracle (which stays held out);
they exist so the deliverable can be validated against the PUBLIC
semantics before submitting. Run inside the task container:

  PYTHONPATH=/consumer/src REPOPROOF_ADAPTATION_DIR=/adaptation \
    /venv/env/bin/python -m pytest -q /consumer/public_tests
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rag_ingest import INGEST_RECORD_FIELDS, IngestError, ingest_documents

TRUTH = json.loads(
    (Path(__file__).parent.parent / "public_examples" / "truth_table.json").read_text(encoding="utf-8")
)


def _ingest_one(text: str) -> dict:
    return ingest_documents({"documents": [{"doc_id": "p-1", "text": text}]})["records"][0]


@pytest.mark.parametrize("row", TRUTH["truth_table"], ids=lambda r: r["case"][:40])
def test_flag_truth_table(row: dict) -> None:
    rec = _ingest_one(row["text"])
    assert rec["frontmatter_present"] == row["frontmatter_present"]
    assert rec["metadata_nonempty"] == row["metadata_nonempty"]


def test_record_schema_exact_fields() -> None:
    rec = _ingest_one("---\ntitle: Hi\n---\nBody.")
    assert set(rec.keys()) == set(INGEST_RECORD_FIELDS)


def test_order_and_one_record_per_document() -> None:
    request = {
        "documents": [
            {"doc_id": "p-a", "text": "---\nx: 1\n---\nA."},
            {"doc_id": "p-b", "text": "Plain."},
            {"doc_id": "p-c", "text": "---\n---\nC."},
        ]
    }
    records = ingest_documents(request)["records"]
    assert [r["doc_id"] for r in records] == ["p-a", "p-b", "p-c"]


def test_dates_normalised_and_types_kept() -> None:
    rec = _ingest_one("---\nwhen: 2026-01-15\ncount: 3\nscore: 4.5\nok: true\ntags:\n  - a\n  - b\n---\nB.")
    assert rec["metadata"]["when"] == "2026-01-15"  # ISO string, not a date object
    assert rec["metadata"]["count"] == 3 and rec["metadata"]["score"] == 4.5
    assert rec["metadata"]["ok"] is True and rec["metadata"]["tags"] == ["a", "b"]
    json.dumps(rec, ensure_ascii=False)


def test_upstream_parse_error_wrapped_with_code() -> None:
    bad = TRUTH["upstream_parse_error"]["text"]
    with pytest.raises(IngestError) as exc:
        _ingest_one(bad)
    assert exc.value.code == "UPSTREAM_PARSE_ERROR"


def test_host_guard_public_behaviour() -> None:
    for doc in ({"doc_id": "g-1", "text": None}, {"doc_id": "g-2"}, {"doc_id": "", "text": "x"}):
        with pytest.raises(IngestError) as exc:
            ingest_documents({"documents": [doc]})
        assert exc.value.code == "INVALID_DOCUMENT_INPUT"


def test_deterministic_and_input_untouched() -> None:
    request = {"documents": [{"doc_id": "p-s", "text": "---\na: 1\n---\nS."}]}
    snapshot = copy.deepcopy(request)
    assert ingest_documents(request) == ingest_documents(copy.deepcopy(snapshot))
    assert request == snapshot
