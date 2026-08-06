"""ORACLE — capability acceptance for adopt-chonkie-local-chunking-v2.

Read-only, hash-guarded, agent-invisible (agent-profile containers do
not mount /oracle at all). Parametrized over BOTH frozen strategies
(sentence, recursive — the only two the pinned upstream API supports)
and over the public + held-out fixture sets. The held-out set never
ships to the agent's workspace.

Contract-frozen parameters (verified against upstream source at commit
0a6baea): tokenizer="character", chunk_size=120, chunk_overlap=0.
``units`` semantics: chunk length in characters — MUST equal
char_end - char_start.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rag_consumer import CHUNK_RECORD_FIELDS, ConsumerChunkingError, chunk_documents

FIXDIR = Path(__file__).parent / "fixtures"
PUBLIC = FIXDIR / "public_documents.json"
HELD_OUT = FIXDIR / "held_out_documents.json"
STRATEGIES = ("sentence", "recursive")
CHUNK_SIZE = 120
LONG_DOC_MIN_CHARS = 200

# fixture file -> sentence repeated ≥3x whose occurrences must be
# separately addressable
REPEATED_MARKERS = {
    PUBLIC: {"doc-101-ops-manual": "本方案支持完全离线运行。", "doc-102-support-faq": "It supports offline chunking."},
    HELD_OUT: {"doc-201-incident-log": "系统在本地完成全部处理。"},
}


def _docs(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["documents"]


def _request(path: Path, strategy: str, *, include_blank: bool = False) -> dict:
    docs = _docs(path)
    if not include_blank:
        docs = [d for d in docs if "blank" not in d["document_id"]]
    return {"documents": docs, "strategy": strategy, "chunk_size": CHUNK_SIZE}


def _texts(request: dict) -> dict[str, str]:
    return {d["document_id"]: d["text"] for d in request["documents"]}


PARAMS = [(f, s) for f in (PUBLIC, HELD_OUT) for s in STRATEGIES]
IDS = [f"{p.name.split('_')[0]}-{s}" for p, s in PARAMS]


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_returns_records_for_each_document(fixture: Path, strategy: str) -> None:
    request = _request(fixture, strategy)
    response = chunk_documents(request)
    attributed = {rec.get("document_id") for rec in response["records"]}
    for doc in request["documents"]:
        assert doc["document_id"] in attributed, f"no records attributed to {doc['document_id']}"


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_multi_chunk_for_long_documents(fixture: Path, strategy: str) -> None:
    request = _request(fixture, strategy)
    response = chunk_documents(request)
    counts: dict[str, int] = {}
    for rec in response["records"]:
        counts[rec.get("document_id", "?")] = counts.get(rec.get("document_id", "?"), 0) + 1
    for doc in request["documents"]:
        if len(doc["text"]) > LONG_DOC_MIN_CHARS:
            assert counts.get(doc["document_id"], 0) >= 2, (
                f"{doc['document_id']} (len={len(doc['text'])}) produced "
                f"{counts.get(doc['document_id'], 0)} chunk(s) at chunk_size={CHUNK_SIZE}"
            )


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_record_schema_exact_fields(fixture: Path, strategy: str) -> None:
    response = chunk_documents(_request(fixture, strategy))
    assert response["records"], "no records at all"
    for rec in response["records"]:
        assert set(rec.keys()) == set(CHUNK_RECORD_FIELDS)


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_units_semantics_and_chunk_size(fixture: Path, strategy: str) -> None:
    """units == char_end - char_start (character tokenizer), and no
    chunk exceeds the frozen chunk_size."""
    response = chunk_documents(_request(fixture, strategy))
    for rec in response["records"]:
        assert rec["units"] == rec["char_end"] - rec["char_start"], (
            f"units {rec['units']} != span {rec['char_end'] - rec['char_start']}"
        )
        assert rec["units"] <= CHUNK_SIZE, f"chunk of {rec['units']} units exceeds chunk_size={CHUNK_SIZE}"


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_offsets_slice_back_and_in_bounds(fixture: Path, strategy: str) -> None:
    request = _request(fixture, strategy)
    texts = _texts(request)
    response = chunk_documents(request)
    for rec in response["records"]:
        src = texts[rec["document_id"]]
        assert 0 <= rec["char_start"] < rec["char_end"] <= len(src), (
            f"offsets out of bounds: [{rec['char_start']}, {rec['char_end']}) in len {len(src)}"
        )
        assert src[rec["char_start"] : rec["char_end"]] == rec["text"]


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_offsets_monotonic_and_non_overlapping(fixture: Path, strategy: str) -> None:
    response = chunk_documents(_request(fixture, strategy))
    per_doc: dict[str, list[dict]] = {}
    for rec in response["records"]:
        per_doc.setdefault(rec["document_id"], []).append(rec)
    for doc_id, recs in per_doc.items():
        ordered = sorted(recs, key=lambda r: r["ordinal"])
        prev_end = -1
        prev_start = -1
        for rec in ordered:
            assert rec["char_start"] > prev_start, f"{doc_id}: char_start not strictly increasing"
            assert rec["char_start"] >= prev_end, f"{doc_id}: chunks overlap (overlap frozen at 0)"
            prev_start, prev_end = rec["char_start"], rec["char_end"]


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_document_order_and_ordinals(fixture: Path, strategy: str) -> None:
    request = _request(fixture, strategy)
    response = chunk_documents(request)
    doc_order = [d["document_id"] for d in request["documents"]]
    seen: list[str] = []
    ordinals: dict[str, list[int]] = {}
    for rec in response["records"]:
        if rec["document_id"] not in seen:
            seen.append(rec["document_id"])
        ordinals.setdefault(rec["document_id"], []).append(rec["ordinal"])
    assert seen == doc_order
    for doc_id, seq in ordinals.items():
        assert seq == list(range(len(seq))), f"{doc_id}: ordinals not contiguous from 0"


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_ids_stable_unique_and_not_upstream(fixture: Path, strategy: str) -> None:
    first = chunk_documents(_request(fixture, strategy))
    second = chunk_documents(_request(fixture, strategy))
    ids1 = [r.get("chunk_id") for r in first["records"]]
    ids2 = [r.get("chunk_id") for r in second["records"]]
    assert all(ids1), "records carry no chunk_id"
    assert ids1 == ids2, "chunk ids changed between identical runs"
    assert len(ids1) == len(set(ids1)), "chunk ids not unique"
    leaked = [i for i in ids1 if isinstance(i, str) and i.startswith("chnk_")]
    assert not leaked, f"upstream per-call ids leaked: {leaked[:3]}"


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_metadata_passthrough(fixture: Path, strategy: str) -> None:
    request = _request(fixture, strategy)
    meta = {d["document_id"]: d["metadata"] for d in request["documents"]}
    response = chunk_documents(request)
    for rec in response["records"]:
        assert rec["metadata"] == meta[rec["document_id"]]


@pytest.mark.parametrize(("fixture", "strategy"), PARAMS, ids=IDS)
def test_repeated_sentence_occurrences_separately_addressed(fixture: Path, strategy: str) -> None:
    """A sentence repeated N times must be reachable at DISTINCT offsets
    — a str.find-from-zero implementation collapses them all onto the
    first occurrence and fails here."""
    request = _request(fixture, strategy)
    texts = _texts(request)
    response = chunk_documents(request)
    for doc_id, marker in REPEATED_MARKERS[fixture].items():
        containing = [r for r in response["records"] if r["document_id"] == doc_id and marker in r["text"]]
        starts = {r["char_start"] for r in containing}
        assert len(starts) >= 2, (
            f"{doc_id}: marker occurs {texts[doc_id].count(marker)}x in source but records "
            f"cover it at {len(starts)} distinct offset(s)"
        )


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_input_not_mutated(strategy: str) -> None:
    request = _request(PUBLIC, strategy)
    snapshot = copy.deepcopy(request)
    chunk_documents(request)
    assert request == snapshot


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_blank_document_yields_zero_records(strategy: str) -> None:
    response = chunk_documents(_request(PUBLIC, strategy, include_blank=True))
    blank = [r for r in response["records"] if r.get("document_id") == "doc-103-blank"]
    assert blank == []


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_upstream_errors_wrapped(strategy: str) -> None:
    with pytest.raises(ConsumerChunkingError):
        chunk_documents(
            {
                "documents": [{"document_id": "doc-bad", "text": None, "metadata": {}}],
                "strategy": strategy,
                "chunk_size": CHUNK_SIZE,
            }
        )
