"""ORACLE — capability acceptance for adopt-chonkie-local-chunking-v1.

Read-only, hash-guarded. The agent may NEVER edit this file. Each test
pins one contract property, so a direct-adoption baseline reports the
real gap as a granular failed-test list instead of one opaque error.

No test here prescribes HOW the adapter must work — only observable
properties of ``rag_consumer.chunk_documents`` output.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from rag_consumer import CHUNK_RECORD_FIELDS, ConsumerChunkingError, chunk_documents

FIXTURES = Path(__file__).parent / "fixtures" / "input_documents.json"
UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _load_docs() -> list[dict]:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["documents"]


def _request_main() -> dict:
    """Docs 1-2 (real content). The blank doc has its own test."""
    return {"documents": [d for d in _load_docs() if d["document_id"] != "doc-003-blank"]}


def _doc_texts(request: dict) -> dict[str, str]:
    return {d["document_id"]: d["text"] for d in request["documents"]}


def test_returns_records_for_each_document() -> None:
    request = _request_main()
    response = chunk_documents(request)
    by_doc: dict[str, int] = {}
    for rec in response["records"]:
        by_doc[rec.get("document_id", "<missing>")] = by_doc.get(rec.get("document_id", "<missing>"), 0) + 1
    for doc in request["documents"]:
        assert by_doc.get(doc["document_id"], 0) >= 1, (
            f"no records attributed to {doc['document_id']}; got keys={sorted(by_doc)}"
        )


def test_record_schema_exact_fields() -> None:
    response = chunk_documents(_request_main())
    assert response["records"], "no records at all"
    for rec in response["records"]:
        assert set(rec.keys()) == set(CHUNK_RECORD_FIELDS), (
            f"record fields {sorted(rec.keys())} != contract {sorted(CHUNK_RECORD_FIELDS)}"
        )


def test_response_json_serializable() -> None:
    response = chunk_documents(_request_main())
    json.dumps(response, ensure_ascii=False)


def test_deterministic_repeat_run() -> None:
    first = chunk_documents(_request_main())
    second = chunk_documents(_request_main())
    assert first == second, "same input must produce byte-identical output"


def test_chunk_ids_stable_and_not_upstream_uuid() -> None:
    first = chunk_documents(_request_main())
    second = chunk_documents(_request_main())
    ids_first = [rec.get("chunk_id") or rec.get("id") for rec in first["records"]]
    ids_second = [rec.get("chunk_id") or rec.get("id") for rec in second["records"]]
    assert all(ids_first), "records carry no id at all"
    assert ids_first == ids_second, "chunk ids changed between identical runs"
    leaked = [i for i in ids_first if isinstance(i, str) and UUID4_RE.match(i)]
    assert not leaked, f"upstream uuid4 ids leaked into host records: {leaked[:3]}"
    assert len(ids_first) == len(set(ids_first)), "chunk ids not unique"


def test_document_order_and_ordinals() -> None:
    request = _request_main()
    response = chunk_documents(request)
    doc_order = [d["document_id"] for d in request["documents"]]
    seen_docs = []
    ordinals: dict[str, list[int]] = {}
    for rec in response["records"]:
        doc = rec["document_id"]
        if doc not in seen_docs:
            seen_docs.append(doc)
        ordinals.setdefault(doc, []).append(rec["ordinal"])
    assert seen_docs == doc_order, f"document order changed: {seen_docs} != {doc_order}"
    for doc, seq in ordinals.items():
        assert seq == list(range(len(seq))), f"{doc} ordinals not contiguous from 0: {seq[:6]}"


def test_offsets_match_source_slice() -> None:
    """The only trustworthy offset check with unicode + repeated
    sentences: the source slice at [char_start:char_end] must equal the
    chunk text. A str.find-based reconstruction cannot fake this."""
    request = _request_main()
    texts = _doc_texts(request)
    response = chunk_documents(request)
    for rec in response["records"]:
        src = texts[rec["document_id"]]
        assert src[rec["char_start"] : rec["char_end"]] == rec["text"], (
            f"offset slice mismatch in {rec['document_id']} ordinal={rec['ordinal']}"
        )


def test_metadata_and_document_id_passthrough() -> None:
    request = _request_main()
    meta = {d["document_id"]: d["metadata"] for d in request["documents"]}
    response = chunk_documents(request)
    for rec in response["records"]:
        assert rec["metadata"] == meta[rec["document_id"]], "document metadata lost or altered"


def test_input_not_mutated() -> None:
    request = _request_main()
    snapshot = copy.deepcopy(request)
    chunk_documents(request)
    assert request == snapshot, "chunk_documents mutated its input"


def test_blank_document_yields_zero_records_without_crash() -> None:
    docs = _load_docs()
    response = chunk_documents({"documents": docs})
    blank = [r for r in response["records"] if r.get("document_id") == "doc-003-blank"]
    assert blank == [], f"blank/whitespace document produced {len(blank)} records"


def test_upstream_errors_wrapped_as_host_error() -> None:
    with pytest.raises(ConsumerChunkingError):
        chunk_documents({"documents": [{"document_id": "doc-bad", "text": None, "metadata": {}}]})
