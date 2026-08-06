"""NEGATIVE CONTROL 2 — schema-perfect fixed-width slicer (cheat).

Never calls Chonkie. Produces a fully contract-shaped response: stable
ids, correct offsets that slice back, metadata passthrough, R1 blank
handling, wrapped errors — but chunks are fixed 120-char slices and
``sentence`` vs ``recursive`` produce IDENTICAL output. The v3 oracle
must reject it (boundaries differ from the Chonkie reference; the
strategy-sensitivity test fails). Test fixture only.
"""

from __future__ import annotations

import hashlib

WIDTH = 120


def chunk_documents(request: dict) -> dict:
    from rag_consumer.chunking import ConsumerChunkingError

    records: list[dict] = []
    for doc in request["documents"]:
        doc_id = doc["document_id"]
        text = doc.get("text")
        if not isinstance(text, str):
            raise ConsumerChunkingError(f"{doc_id}: document text must be a string")
        if text.strip() == "":
            continue
        for ordinal, start in enumerate(range(0, len(text), WIDTH)):
            piece = text[start : start + WIDTH]
            digest = hashlib.sha256(f"{doc_id}:{ordinal}:{piece}".encode()).hexdigest()[:12]
            records.append(
                {
                    "chunk_id": f"{doc_id}:{ordinal}:{digest}",
                    "document_id": doc_id,
                    "ordinal": ordinal,
                    "text": piece,
                    "char_start": start,
                    "char_end": start + len(piece),
                    "units": len(piece),
                    "metadata": doc.get("metadata", {}),
                }
            )
    return {"records": records}
