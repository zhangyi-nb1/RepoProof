"""ORACLE — host regression for adopt-chonkie-local-chunking-v2.

The consumer fixture's PRE-EXISTING capabilities must keep working;
none of these touch Chonkie.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rag_consumer import ChunkRecord, health, load_documents

FIXTURES = Path(__file__).parent / "fixtures" / "public_documents.json"


def test_loader_loads_all_documents() -> None:
    docs = load_documents(FIXTURES)
    assert [d["document_id"] for d in docs] == [
        "doc-101-ops-manual",
        "doc-102-support-faq",
        "doc-103-blank",
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
        text="hello 世界 🚀",
        char_start=0,
        char_end=10,
        units=10,
        metadata={"source": "unit"},
    )
    dumped = json.dumps(rec.to_dict(), ensure_ascii=False)
    assert json.loads(dumped)["units"] == 10
