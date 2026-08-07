"""ORACLE — host regression for adopt-rank-bm25-local-search-v1.
Pre-existing consumer capabilities; none touch rank_bm25."""

from __future__ import annotations

import hashlib
from pathlib import Path

from rag_search import health, load_corpus

FIXTURES = Path(__file__).parent / "fixtures" / "public_documents.json"


def test_corpus_loads() -> None:
    payload = load_corpus(FIXTURES)
    assert len(payload["documents"]) == 10
    assert payload["documents"][0]["chunk_id"] == "c-001"
    assert len(payload["queries"]) == 5


def test_loader_does_not_modify_fixture() -> None:
    before = hashlib.sha256(FIXTURES.read_bytes()).hexdigest()
    load_corpus(FIXTURES)
    assert hashlib.sha256(FIXTURES.read_bytes()).hexdigest() == before


def test_health() -> None:
    assert health() == "ok"
