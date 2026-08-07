"""Adapter: bridges Chonkie offline chunking into the host RAG consumer contract.

Frozen parameters (from pinned upstream API):
  - tokenizer: character
  - chunk_size: 120
  - chunk_overlap (sentence strategy only): 0
"""

from __future__ import annotations

from typing import Any

from chonkie import RecursiveChunker, SentenceChunker
from chonkie.types import Chunk as ChonkieChunk

# ---------------------------------------------------------------------------
# Frozen upstream configuration
# ---------------------------------------------------------------------------
_TOKENIZER = "character"
_CHUNK_SIZE = 120
_SENTENCE_CHUNK_OVERLAP = 0


def _make_chunk_id(document_id: str, ordinal: int) -> str:
    """Stable deterministic chunk id, never upstream per-call ids."""
    return f"{document_id}-{ordinal}"


def _is_blank(text: str) -> bool:
    """R1: whitespace-only documents yield ZERO records."""
    return not text.strip()


def _build_chunkers():
    """Create the two strategy chunkers with frozen parameters."""
    sentence = SentenceChunker(
        tokenizer=_TOKENIZER,
        chunk_size=_CHUNK_SIZE,
        chunk_overlap=_SENTENCE_CHUNK_OVERLAP,
    )
    recursive = RecursiveChunker(
        tokenizer=_TOKENIZER,
        chunk_size=_CHUNK_SIZE,
    )
    return {"sentence": sentence, "recursive": recursive}


# Pre-warm chunkers at module level (CPU-only, offline-safe)
_CHUNKERS = _build_chunkers()


def _chunk_one_document(
    doc: dict[str, Any],
    chunker: SentenceChunker | RecursiveChunker,
) -> list[dict[str, Any]]:
    """Chunk a single document and return host-schema records."""
    text: str = doc["text"]
    document_id: str = doc["document_id"]
    metadata: dict[str, Any] = doc.get("metadata", {})

    # R1: whitespace-only yields zero records
    if _is_blank(text):
        return []

    try:
        upstream_chunks: list[ChonkieChunk] = chunker.chunk(text)
    except Exception:
        from rag_consumer.chunking import ConsumerChunkingError
        raise ConsumerChunkingError(
            f"Chonkie chunking failed for document {document_id!r}"
        )

    records: list[dict[str, Any]] = []
    for ordinal, ch in enumerate(upstream_chunks):
        # R2: indivisible over-size chunks preserved verbatim (never re-split).
        # We trust upstream boundaries completely.
        char_start: int = ch.start_index
        char_end: int = ch.end_index
        units: int = ch.token_count  # character tokenizer → units == len(text)

        records.append({
            "chunk_id": _make_chunk_id(document_id, ordinal),
            "document_id": document_id,
            "ordinal": ordinal,
            "text": ch.text,
            "char_start": char_start,
            "char_end": char_end,
            "units": units,
            "metadata": dict(metadata),  # shallow copy for safety
        })

    return records


def chunk_documents(request: dict) -> dict:
    """Host entry point: chunk documents with the requested strategy.

    Args:
        request: {"documents": [{"document_id", "text", "metadata"}...],
                  "strategy": "sentence"|"recursive", "chunk_size": int}

    Returns:
        {"records": [{"chunk_id", "document_id", "ordinal", "text",
                       "char_start", "char_end", "units", "metadata"}, ...]}

    """
    strategy: str = request.get("strategy", "sentence")
    if strategy not in _CHUNKERS:
        from rag_consumer.chunking import ConsumerChunkingError
        raise ConsumerChunkingError(
            f"Unknown strategy {strategy!r}; must be 'sentence' or 'recursive'"
        )

    chunker = _CHUNKERS[strategy]
    documents: list[dict[str, Any]] = request.get("documents", [])

    all_records: list[dict[str, Any]] = []
    for doc in documents:
        all_records.extend(_chunk_one_document(doc, chunker))

    return {"records": all_records}
