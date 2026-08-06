"""ORACLE — host regression for adopt-chonkie-local-chunking-v1.

The consumer fixture's PRE-EXISTING capabilities must keep working
after any adoption. These tests do not touch Chonkie at all.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rag_consumer import ChunkRecord, health, load_documents

FIXTURES = Path(__file__).parent / "fixtures" / "input_documents.json"


def test_loader_loads_all_documents() -> None:
    docs = load_documents(FIXTURES)
    assert [d["document_id"] for d in docs] == [
        "doc-001-meeting-notes",
        "doc-002-product-faq",
        "doc-003-blank",
    ]
    assert all("metadata" in d for d in docs)


def test_loader_does_not_modify_fixture_file() -> None:
    before = hashlib.sha256(FIXTURES.read_bytes()).hexdigest()
    load_documents(FIXTURES)
    after = hashlib.sha256(FIXTURES.read_bytes()).hexdigest()
    assert before == after


def test_health_endpoint_logic() -> None:
    assert health() == "ok"


def test_chunk_record_roundtrip() -> None:
    rec = ChunkRecord(
        chunk_id="doc-x:0:abcd",
        document_id="doc-x",
        ordinal=0,
        text="hello 世界",
        char_start=0,
        char_end=8,
        units=3,
        metadata={"source": "unit"},
    )
    dumped = json.dumps(rec.to_dict(), ensure_ascii=False)
    assert json.loads(dumped)["text"] == "hello 世界"
