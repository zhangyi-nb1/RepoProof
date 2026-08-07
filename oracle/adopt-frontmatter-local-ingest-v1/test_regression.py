"""ORACLE — host regression; none of these touch python-frontmatter."""

from __future__ import annotations

import hashlib
from pathlib import Path

from rag_ingest import health, load_documents

FIXTURES = Path(__file__).parent / "fixtures" / "public_documents.json"


def test_loader_loads_documents() -> None:
    docs = load_documents(FIXTURES)
    assert len(docs) == 6 and docs[0]["doc_id"] == "d-001-standard"


def test_loader_does_not_modify_fixture() -> None:
    before = hashlib.sha256(FIXTURES.read_bytes()).hexdigest()
    load_documents(FIXTURES)
    assert hashlib.sha256(FIXTURES.read_bytes()).hexdigest() == before


def test_health() -> None:
    assert health() == "ok"
