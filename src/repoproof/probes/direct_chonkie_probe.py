"""Direct-adoption probe: call Chonkie the naive README way and dump
EXACTLY what comes back (introspected), per fixture document.

This is diagnostic evidence, not an adapter: it records the raw
upstream return shape (field names, id style, offsets semantics,
errors on edge inputs) so the REAL gap between upstream output and the
host ChunkRecord contract is captured — without solving it.

stdlib only. Runs inside the network-none container.
"""

from __future__ import annotations

import json
import sys
import traceback

_ATTRS = (
    "id",
    "text",
    "start_index",
    "end_index",
    "token_count",
    "level",
    "sentences",
    "context",
)


def _serialize_chunk(chunk: object) -> dict:
    out: dict = {"_type": type(chunk).__name__}
    for attr in _ATTRS:
        if hasattr(chunk, attr):
            value = getattr(chunk, attr)
            try:
                json.dumps(value)
                out[attr] = value
            except (TypeError, ValueError):
                out[attr] = repr(value)[:200]
    return out


def main() -> int:
    fixture_path = sys.argv[1]
    with open(fixture_path, encoding="utf-8") as fh:
        documents = json.load(fh)["documents"]

    import chonkie

    result: dict = {
        "chonkie_version": getattr(chonkie, "__version__", "?"),
        "documents": {},
    }
    chunker_specs = []
    for name in ("SentenceChunker", "RecursiveChunker"):
        cls = getattr(chonkie, name, None)
        if cls is not None:
            chunker_specs.append((name, cls))
    result["available_chunkers"] = [n for n, _ in chunker_specs]

    for doc in documents:
        doc_out: dict = {}
        for name, cls in chunker_specs:
            entry: dict = {}
            try:
                chunker = cls()
                chunks = chunker.chunk(doc["text"])
                entry["chunks"] = [_serialize_chunk(c) for c in chunks]
                entry["count"] = len(chunks)
            except Exception as exc:  # noqa: BLE001 — recording raw upstream behaviour is the point
                entry["error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc)[:300],
                    "trace_tail": traceback.format_exc().splitlines()[-2:],
                }
            doc_out[name] = entry
        result["documents"][doc["document_id"]] = doc_out

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
