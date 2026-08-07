"""Adapter: maps Chonkie chunkers to host Consumer ChunkRecord contract.

Frozen parameters:
  - tokenizer: character
  - chunk_size: 120
  - chunk_overlap: 0 (sentence strategy only)
"""
from __future__ import annotations

from typing import Any, Dict, List

from chonkie import RecursiveChunker, SentenceChunker
from chonkie.types.base import Chunk

from rag_consumer.chunking import ConsumerChunkingError


# ---------------------------------------------------------------------------
# Frozen configuration
# ---------------------------------------------------------------------------
_FROZEN_TOKENIZER = "character"
_FROZEN_CHUNK_SIZE = 120
_FROZEN_CHUNK_OVERLAP = 0  # sentence only

_STRATEGIES = ("sentence", "recursive")


def _make_chunker(strategy: str):
    """Return a configured Chonkie chunker for *strategy*."""
    if strategy == "sentence":
        return SentenceChunker(
            tokenizer=_FROZEN_TOKENIZER,
            chunk_size=_FROZEN_CHUNK_SIZE,
            chunk_overlap=_FROZEN_CHUNK_OVERLAP,
        )
    if strategy == "recursive":
        return RecursiveChunker(
            tokenizer=_FROZEN_TOKENIZER,
            chunk_size=_FROZEN_CHUNK_SIZE,
        )
    raise ConsumerChunkingError(
        f"Unknown strategy {strategy!r}; expected one of {_STRATEGIES}"
    )


def _is_blank(text: str) -> bool:
    """R1: whitespace-only text is blank → zero records."""
    return not text.strip()


def _stable_chunk_id(document_id: str, ordinal: int) -> str:
    """Deterministic, stable chunk id (never upstream per-call ids)."""
    return f"{document_id}__{ordinal}"


def chunk_documents(request: dict) -> dict:
    """Entrypoint matching host's adapter seam.

    Returns {"records": [...]} with each record carrying:
        chunk_id, document_id, ordinal, text, char_start, char_end, units, metadata
    """
    strategy = request.get("strategy", "sentence")
    if strategy not in _STRATEGIES:
        raise ConsumerChunkingError(
            f"Unknown strategy {strategy!r}; expected one of {_STRATEGIES}"
        )

    documents: List[Dict[str, Any]] = request.get("documents", [])

    try:
        chunker = _make_chunker(strategy)
    except ConsumerChunkingError:
        raise
    except Exception as exc:
        raise ConsumerChunkingError(str(exc)) from exc

    records: List[Dict[str, Any]] = []

    for doc in documents:
        document_id: str = doc["document_id"]
        text: str = doc["text"]
        metadata: dict = doc.get("metadata", {})

        # R1: blank documents → zero records
        if _is_blank(text):
            continue

        try:
            chunks: List[Chunk] = chunker.chunk(text)
        except Exception as exc:
            raise ConsumerChunkingError(str(exc)) from exc

        for ordinal, chunk in enumerate(chunks):
            records.append({
                "chunk_id": _stable_chunk_id(document_id, ordinal),
                "document_id": document_id,
                "ordinal": ordinal,
                "text": chunk.text,
                "char_start": chunk.start_index,
                "char_end": chunk.end_index,
                "units": chunk.end_index - chunk.start_index,
                "metadata": metadata,
            })

    return {"records": records}
