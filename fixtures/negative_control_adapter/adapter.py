"""NEGATIVE CONTROL — a deliberately cheating "adapter".

This implementation never calls Chonkie: it returns exactly ONE
full-span record per document, schema-shaped and offset-consistent.
It exists to PROVE the v2 oracle cannot be satisfied by a trivial
passthrough — the capability suite must reject it (multi-chunk,
chunk_size cap, repeated-occurrence addressing, blank-doc handling,
error wrapping all fail).

Never place this file in a real run's adaptation zone. It is a test
fixture consumed by tests/test_negative_control.py only.
"""

from __future__ import annotations


def chunk_documents(request: dict) -> dict:
    records = []
    for doc in request["documents"]:
        text = doc["text"]
        records.append(
            {
                "chunk_id": f"{doc['document_id']}#0",
                "document_id": doc["document_id"],
                "ordinal": 0,
                "text": text,
                "char_start": 0,
                "char_end": len(text),
                "units": len(text),
                "metadata": doc.get("metadata", {}),
            }
        )
    return {"records": records}
