"""Adapter: Delegates to pinned Chonkie chunkers, mapping to host ChunkRecord schema."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from chonkie import RecursiveChunker, SentenceChunker
from chonkie.types import Chunk as UpstreamChunk

# ---------------------------------------------------------------------------
# Frozen parameters (from pinned upstream API)
# ---------------------------------------------------------------------------
_TOKENIZER = "character"
_CHUNK_SIZE = 120
_CHUNK_OVERLAP = 0  # sentence strategy only


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stable_chunk_id(document_id: str, ordinal: int) -> str:
    """Produce a stable, deterministic chunk id that is NOT an upstream per-call id."""
    digest = hashlib.sha256(f"{document_id}|{ordinal}".encode()).hexdigest()[:16]
    return f"chk-{digest}"


def _build_chunker(strategy: str):
    """Return a configured Chonkie chunker for the requested strategy.

    Raises:
        ValueError: if the strategy is unknown.
    """
    if strategy == "sentence":
        return SentenceChunker(
            tokenizer=_TOKENIZER,
            chunk_size=_CHUNK_SIZE,
            chunk_overlap=_CHUNK_OVERLAP,
        )
    elif strategy == "recursive":
        return RecursiveChunker(
            tokenizer=_TOKENIZER,
            chunk_size=_CHUNK_SIZE,
        )
    else:
        raise ValueError(
            f"Unknown strategy: {strategy!r}. Expected 'sentence' or 'recursive'."
        )


def _is_blank(text: str) -> bool:
    """R1: detect whitespace-only documents."""
    return not text.strip()


def _wrap_error(message: str) -> "ConsumerChunkingError":
    """Import and return a ConsumerChunkingError with the given message."""
    from rag_consumer.chunking import ConsumerChunkingError

    return ConsumerChunkingError(message)


# ---------------------------------------------------------------------------
# Adapter entry point
# ---------------------------------------------------------------------------

def chunk_documents(request: Dict[str, Any]) -> Dict[str, Any]:
    """Chunk documents using Chonkie, returning host-schema records.

    Args:
        request: A dict with keys:
            - "documents": list of {document_id, text, metadata}
            - "strategy": "sentence" | "recursive"
            - "chunk_size": int (ignored; frozen to 120)

    Returns:
        {"records": [ChunkRecord-as-dict, ...]}
    """
    strategy: str = request.get("strategy", "")
    if strategy not in ("sentence", "recursive"):
        raise _wrap_error(
            f"Invalid or missing strategy: {strategy!r}. "
            "Expected 'sentence' or 'recursive'."
        )

    documents: List[Dict[str, Any]] = request.get("documents", [])

    # Build the chunker once for the requested strategy.
    try:
        chunker = _build_chunker(strategy)
    except Exception as exc:
        raise _wrap_error(
            f"Failed to initialise Chonkie chunker for strategy {strategy!r}: {exc}"
        ) from exc

    records: List[Dict[str, Any]] = []

    for doc in documents:
        document_id: str = doc["document_id"]
        text: str = doc["text"]
        metadata: Dict[str, Any] = dict(doc.get("metadata") or {})

        # R1: whitespace-only documents produce zero records.
        if _is_blank(text):
            continue

        try:
            upstream_chunks: List[UpstreamChunk] = chunker.chunk(text)
        except Exception as exc:
            raise _wrap_error(
                f"Chonkie chunking failed for document {document_id!r} "
                f"with strategy {strategy!r}: {exc}"
            ) from exc

        for ordinal, ch in enumerate(upstream_chunks):
            char_start: int = ch.start_index
            char_end: int = ch.end_index
            units: int = char_end - char_start

            records.append(
                {
                    "chunk_id": _stable_chunk_id(document_id, ordinal),
                    "document_id": document_id,
                    "ordinal": ordinal,
                    "text": ch.text,
                    "char_start": char_start,
                    "char_end": char_end,
                    "units": units,
                    "metadata": metadata,
                }
            )

    return {"records": records}
