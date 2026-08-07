"""Adapter: ingest documents using python-frontmatter, producing host-schema records."""

from __future__ import annotations

import datetime
import json

import frontmatter


def _make_json_safe(obj):
    """Project a value to be JSON-safe (P1: dates become ISO strings)."""
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_json_safe(v) for v in obj]
    return obj


def ingest_documents(request: dict) -> dict:
    records = []
    for doc in request.get("documents", []):
        # P4: malformed request entries — missing required fields
        if not isinstance(doc, dict):
            raise _IngestError("each document must be a dict")
        if "document_id" not in doc:
            raise _IngestError("document missing 'document_id'")
        if "text" not in doc:
            raise _IngestError("document missing 'text'")

        doc_id = doc["document_id"]
        text = doc["text"]
        incoming_meta = doc.get("metadata", {})

        # P2: has_frontmatter detection
        has_fm = frontmatter.checks(text)

        # Parse with upstream (python-frontmatter)
        metadata, content = frontmatter.parse(text)

        # Merge incoming metadata with frontmatter metadata
        # (frontmatter metadata overrides? Or incoming overrides?)
        merged_meta = {}
        if isinstance(incoming_meta, dict):
            merged_meta.update(incoming_meta)
        if isinstance(metadata, dict):
            merged_meta.update(metadata)

        # P1: project metadata JSON-safe
        safe_meta = _make_json_safe(merged_meta)

        records.append({
            "doc_id": doc_id,
            "has_frontmatter": has_fm,
            "metadata": safe_meta,
            "content": content,
        })

    return {"records": records}


# Local reference for IngestError; import from host at module level if available,
# otherwise define our own matching class.
try:
    from rag_ingest import IngestError as _IngestError
except ImportError:
    class _IngestError(RuntimeError):
        """Stable host-side error for malformed inputs / upstream failures."""
