"""
Adapter for rag_search / rag_consumer.

Provides:
  - search_documents(request) -> dict   (BM25 ranking via rank_bm25)
  - chunk_documents(request) -> dict    (sentence chunking via manual impl)
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any

import numpy as np

# Import BM25Okapi from the installed package (same as /upstream)
from rank_bm25 import BM25Okapi


# ---------------------------------------------------------------------------
# S1 helper: character tokenizer
# ---------------------------------------------------------------------------

def _char_tokenize(text: str) -> list[str]:
    """Tokenize text into individual characters (S1: character tokenizer)."""
    return list(text)


# ---------------------------------------------------------------------------
# search_documents
# ---------------------------------------------------------------------------

def search_documents(request: dict) -> dict:
    """Return host-schema SearchHit rows with BM25 ranking.

    Request shape:
      {
        "documents": [{"chunk_id": str, "text": str, "document_id": str, ...}, ...],
        "queries": [{"query_id": str, "text": str, "top_k": int | None}, ...]
      }

    Returns:
      {"hits": [{"query_id": str, "rank": int, "chunk_id": str,
                 "score": float, "text": str}, ...]}
    """
    documents = request.get("documents", [])
    queries = request.get("queries", [])

    # Validate request structure
    if not isinstance(documents, list):
        from rag_search.search import SearchError
        raise SearchError("request.documents must be a list")
    if not isinstance(queries, list):
        from rag_search.search import SearchError
        raise SearchError("request.queries must be a list")

    # Tokenize corpus using character tokenizer (S1)
    corpus_texts = [doc["text"] for doc in documents]
    tokenized_corpus = [_char_tokenize(t) for t in corpus_texts]

    # Build BM25 index (CPU-only, fully offline)
    bm25 = BM25Okapi(tokenized_corpus)

    all_hits: list[dict[str, Any]] = []

    for qi, query in enumerate(queries):
        query_id = query.get("query_id", f"q{qi}")
        query_text = query.get("text", "")
        top_k = query.get("top_k", None)

        # S4: empty queries yield zero hits
        if not query_text or not query_text.strip():
            continue

        # Tokenize query with character tokenizer (S1)
        tokenized_query = _char_tokenize(query_text)

        # Get BM25 scores
        scores = bm25.get_scores(tokenized_query)

        # Build (score, index, document) tuples
        indexed_scores = []
        for i, doc in enumerate(documents):
            score = float(scores[i])
            # S2: round scores (to 6 decimal places)
            score = round(score, 6)
            indexed_scores.append((score, i, doc))

        # Sort by score descending, then by original index ascending (S3: stable tie-break)
        indexed_scores.sort(key=lambda x: (-x[0], x[1]))

        # Apply top_k (S5)
        if top_k is not None and top_k > 0:
            indexed_scores = indexed_scores[:top_k]

        # Build hits with contiguous ranks from 0
        for rank, (score, idx, doc) in enumerate(indexed_scores):
            all_hits.append({
                "query_id": query_id,
                "rank": rank,
                "chunk_id": doc["chunk_id"],
                "score": score,
                "text": doc["text"],
            })

    return {"hits": all_hits}


# ---------------------------------------------------------------------------
# chunk_documents
# ---------------------------------------------------------------------------

# Simple sentence splitting regex (handles ., !, ?, and newlines)
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+')


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    if not text or not text.strip():
        return []
    # Split on sentence boundaries
    parts = _SENTENCE_SPLIT_RE.split(text)
    # Filter out empty sentences
    return [p for p in parts if p.strip()]


def _make_chunk_id(document_id: str, ordinal: int) -> str:
    """Create a stable deterministic chunk id."""
    raw = f"{document_id}:{ordinal}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def chunk_documents(request: dict) -> dict:
    """Chunk documents using sentence strategy with character tokenizer.

    Frozen parameters:
      - strategy: sentence
      - tokenizer: character
      - chunk_size: 120
      - chunk_overlap: 0

    Request shape:
      {
        "documents": [{"document_id": str, "text": str, "metadata": dict}, ...],
        "strategy": "sentence" | "recursive",
        "chunk_size": int
      }

    Returns:
      {"chunks": [{"chunk_id": str, "document_id": str, "ordinal": int,
                   "text": str, "char_start": int, "char_end": int,
                   "units": str, "metadata": dict}, ...]}
    """
    documents = request.get("documents", [])
    strategy = request.get("strategy", "sentence")
    chunk_size = request.get("chunk_size", 120)

    # For now, only sentence strategy is supported per frozen params
    if strategy not in ("sentence", "recursive"):
        from rag_search.search import SearchError
        raise SearchError(f"Unsupported strategy: {strategy}")

    all_chunks: list[dict[str, Any]] = []

    for doc in documents:
        document_id = doc["document_id"]
        text = doc.get("text", "")
        metadata = doc.get("metadata", {})

        # R1: whitespace-only documents yield ZERO records
        if not text or not text.strip():
            continue

        if strategy == "sentence":
            chunks = _chunk_sentence(text, chunk_size, document_id, metadata)
        else:
            # recursive strategy - for now, treat like sentence but with
            # recursive splitting on newlines then sentences
            chunks = _chunk_recursive(text, chunk_size, document_id, metadata)

        all_chunks.extend(chunks)

    return {"chunks": all_chunks}


def _chunk_sentence(
    text: str, chunk_size: int, document_id: str, metadata: dict
) -> list[dict[str, Any]]:
    """Sentence-based chunking."""
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks = []
    current_chunk = ""
    current_start = 0
    ordinal = 0

    # We need to track positions in the original text
    pos = 0
    for sentence in sentences:
        # Find the sentence in the text starting from pos
        idx = text.find(sentence, pos)
        if idx == -1:
            # Fallback: use pos
            idx = pos

        sentence_start = idx
        sentence_end = idx + len(sentence)

        if not current_chunk:
            current_start = sentence_start
            current_chunk = sentence
        elif len(current_chunk) + 1 + len(sentence) <= chunk_size:
            # Add a space between sentences
            # Find the actual separator
            sep_start = current_start + len(current_chunk)
            sep_end = sentence_start
            separator = text[sep_start:sep_end]
            current_chunk += separator + sentence
        else:
            # Current chunk is full; emit it
            chunk_end = current_start + len(current_chunk)
            chunks.append({
                "chunk_id": _make_chunk_id(document_id, ordinal),
                "document_id": document_id,
                "ordinal": ordinal,
                "text": current_chunk,
                "char_start": current_start,
                "char_end": chunk_end,
                "units": "",
                "metadata": metadata,
            })
            ordinal += 1
            current_start = sentence_start
            current_chunk = sentence

        pos = sentence_end

    # Emit last chunk
    if current_chunk:
        chunk_end = current_start + len(current_chunk)
        # R2: indivisible over-size chunk preserved verbatim
        chunks.append({
            "chunk_id": _make_chunk_id(document_id, ordinal),
            "document_id": document_id,
            "ordinal": ordinal,
            "text": current_chunk,
            "char_start": current_start,
            "char_end": chunk_end,
            "units": "",
            "metadata": metadata,
        })

    return chunks


def _chunk_recursive(
    text: str, chunk_size: int, document_id: str, metadata: dict
) -> list[dict[str, Any]]:
    """Recursive chunking: split on paragraphs then sentences."""
    # Split on double newlines first (paragraphs), then on single newlines, then sentences
    paragraphs = re.split(r'\n\s*\n', text)
    
    all_sentences = []
    for para in paragraphs:
        if not para.strip():
            continue
        # Split paragraph into lines
        lines = para.split('\n')
        for line in lines:
            if not line.strip():
                continue
            # Split line into sentences
            sents = _split_sentences(line)
            all_sentences.extend(sents)
    
    if not all_sentences:
        return []

    chunks = []
    current_chunk = ""
    current_start = 0
    ordinal = 0
    pos = 0

    for sentence in all_sentences:
        idx = text.find(sentence, pos)
        if idx == -1:
            idx = pos
        sentence_start = idx
        sentence_end = idx + len(sentence)

        if not current_chunk:
            current_start = sentence_start
            current_chunk = sentence
        elif len(current_chunk) + 1 + len(sentence) <= chunk_size:
            sep_start = current_start + len(current_chunk)
            sep_end = sentence_start
            separator = text[sep_start:sep_end]
            current_chunk += separator + sentence
        else:
            chunk_end = current_start + len(current_chunk)
            chunks.append({
                "chunk_id": _make_chunk_id(document_id, ordinal),
                "document_id": document_id,
                "ordinal": ordinal,
                "text": current_chunk,
                "char_start": current_start,
                "char_end": chunk_end,
                "units": "",
                "metadata": metadata,
            })
            ordinal += 1
            current_start = sentence_start
            current_chunk = sentence

        pos = sentence_end

    if current_chunk:
        chunk_end = current_start + len(current_chunk)
        chunks.append({
            "chunk_id": _make_chunk_id(document_id, ordinal),
            "document_id": document_id,
            "ordinal": ordinal,
            "text": current_chunk,
            "char_start": current_start,
            "char_end": chunk_end,
            "units": "",
            "metadata": metadata,
        })

    return chunks
