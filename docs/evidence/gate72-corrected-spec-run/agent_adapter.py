"""Adapter: wraps pinned python-frontmatter for the rag_ingest consumer."""

from __future__ import annotations

import datetime as _dt
import json as _json

import frontmatter as _fm

from rag_ingest.errors import IngestError

UPSTREAM_PARSE_ERROR = "UPSTREAM_PARSE_ERROR"


def _json_safe(value: object) -> object:
    """Project a single value to be JSON-safe recursively."""
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    # Fallback: convert to string for anything unexpected
    return str(value)


def ingest_documents(request: dict) -> dict:
    records = []
    for doc in request["documents"]:
        text: str = doc["text"]
        doc_id: str = doc["doc_id"]

        # Strip the input the same way parse() does internally
        original_stripped = text.strip()

        try:
            metadata, content = _fm.parse(text)
        except Exception:
            # Upstream parse failure (YAML/JSON parse error on a
            # structurally complete fence)
            raise IngestError(
                f"Upstream parse error for document {doc_id!r}",
                code=UPSTREAM_PARSE_ERROR,
            ) from None

        # frontmatter_present: upstream recognised AND stripped a block
        frontmatter_present = bool(metadata) or (content != original_stripped)

        # metadata_nonempty: parsed metadata has at least one key
        metadata_nonempty = bool(metadata)

        # Project metadata values to be JSON-safe
        safe_metadata = _json_safe(metadata)

        records.append(
            {
                "doc_id": doc_id,
                "frontmatter_present": frontmatter_present,
                "metadata_nonempty": metadata_nonempty,
                "metadata": safe_metadata,
                "content": content,
            }
        )

    return {"records": records}
