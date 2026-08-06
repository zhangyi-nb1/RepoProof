"""POSITIVE CONTROL — trusted Reference Adapter, ORACLE CALIBRATION ONLY.

Proves the v3 oracle is satisfiable: calls the pinned Chonkie with the
contract-frozen per-strategy parameters and maps the output into the
host ChunkRecord schema (stable ids, contract post-processing rules R1
whitespace-doc→zero-records and R2 preserve-indivisible-chunks).

MUST NEVER be copied into the agent workspace, fixtures/consumer_rag,
any adaptation zone, or an Adoption Bundle — pinned by
tests/test_oracle_controls.py::test_reference_adapter_not_leaked.
Runs only inside the trusted calibration container.
"""

from __future__ import annotations

import hashlib


def chunk_documents(request: dict) -> dict:
    from rag_consumer.chunking import ConsumerChunkingError

    strategy = request.get("strategy", "sentence")
    chunk_size = int(request.get("chunk_size", 120))
    try:
        import chonkie

        records: list[dict] = []
        for doc in request["documents"]:
            doc_id = doc["document_id"]
            text = doc.get("text")
            if not isinstance(text, str):
                raise ConsumerChunkingError(f"{doc_id}: document text must be a string")
            if text.strip() == "":  # R1
                continue
            if strategy == "sentence":
                chunker = chonkie.SentenceChunker(
                    tokenizer="character", chunk_size=chunk_size, chunk_overlap=0
                )
            elif strategy == "recursive":
                chunker = chonkie.RecursiveChunker(tokenizer="character", chunk_size=chunk_size)
            else:
                raise ConsumerChunkingError(f"unsupported strategy: {strategy}")
            for ordinal, chunk in enumerate(chunker.chunk(text)):
                digest = hashlib.sha256(
                    f"{doc_id}:{ordinal}:{chunk.text}".encode()
                ).hexdigest()[:12]
                records.append(
                    {
                        "chunk_id": f"{doc_id}:{ordinal}:{digest}",
                        "document_id": doc_id,
                        "ordinal": ordinal,
                        "text": chunk.text,  # R2: upstream boundaries preserved verbatim
                        "char_start": chunk.start_index,
                        "char_end": chunk.end_index,
                        "units": chunk.end_index - chunk.start_index,
                        "metadata": doc.get("metadata", {}),
                    }
                )
        return {"records": records}
    except ConsumerChunkingError:
        raise
    except Exception as exc:  # noqa: BLE001 — contract: wrap upstream errors
        raise ConsumerChunkingError(f"upstream failure: {type(exc).__name__}: {exc}") from exc
