"""NEGATIVE CONTROL 3 — strategy-ignoring adapter (cheat).

Calls the real pinned Chonkie but ALWAYS uses SentenceChunker, for
``sentence`` and ``recursive`` requests alike. Everything else is
contract-shaped. The v3 oracle must reject it: recursive requests get
sentence boundaries, which diverge from the recursive reference on the
strategy-sensitive run-on documents. Test fixture only; requires the
pinned container (chonkie) to run.
"""

from __future__ import annotations

import hashlib


def chunk_documents(request: dict) -> dict:
    from rag_consumer.chunking import ConsumerChunkingError

    chunk_size = int(request.get("chunk_size", 120))
    try:
        import chonkie

        records: list[dict] = []
        for doc in request["documents"]:
            doc_id = doc["document_id"]
            text = doc.get("text")
            if not isinstance(text, str):
                raise ConsumerChunkingError(f"{doc_id}: document text must be a string")
            if text.strip() == "":
                continue
            chunker = chonkie.SentenceChunker(
                tokenizer="character", chunk_size=chunk_size, chunk_overlap=0
            )  # deliberately ignores request["strategy"]
            for ordinal, chunk in enumerate(chunker.chunk(text)):
                digest = hashlib.sha256(f"{doc_id}:{ordinal}:{chunk.text}".encode()).hexdigest()[:12]
                records.append(
                    {
                        "chunk_id": f"{doc_id}:{ordinal}:{digest}",
                        "document_id": doc_id,
                        "ordinal": ordinal,
                        "text": chunk.text,
                        "char_start": chunk.start_index,
                        "char_end": chunk.end_index,
                        "units": chunk.end_index - chunk.start_index,
                        "metadata": doc.get("metadata", {}),
                    }
                )
        return {"records": records}
    except ConsumerChunkingError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConsumerChunkingError(f"upstream failure: {type(exc).__name__}: {exc}") from exc
