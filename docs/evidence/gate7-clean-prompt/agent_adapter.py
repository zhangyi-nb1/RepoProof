"""Adapter: ingest_documents using python-frontmatter with host schema.

Contract (from /consumer/src/rag_ingest):
  INGEST_RECORD_FIELDS = ("doc_id", "has_frontmatter", "metadata", "content")

  request  -> {"documents": [{"doc_id": str, "text": str}, ...]}
  response -> {"records": [record, ...]}

P1  – metadata values projected JSON-safe: datetime.date / datetime.datetime -> ISO string.
P2  – has_frontmatter set via upstream frontmatter.checks().
P3  – upstream behaviour preserved for malformed fences (parse returns empty metadata + raw text).
P4  – malformed request entries wrapped as rag_ingest.IngestError.
"""

from __future__ import annotations

import datetime as _datetime
from typing import Any

import frontmatter

from rag_ingest import IngestError


def _make_json_safe(value: Any) -> Any:
    """Recursively convert non-JSON-safe values (dates -> ISO strings)."""
    if isinstance(value, (_datetime.date, _datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_safe(v) for v in value]
    return value


def ingest_documents(request: dict) -> dict:
    # -- validate request shape (P4) --
    if not isinstance(request, dict):
        raise IngestError("request must be a dict")
    documents = request.get("documents")
    if not isinstance(documents, list):
        raise IngestError("request must contain a 'documents' list")

    records: list[dict[str, Any]] = []

    for idx, doc in enumerate(documents):
        if not isinstance(doc, dict):
            raise IngestError(
                f"document at index {idx} is not a dict: {type(doc).__name__}"
            )
        if "doc_id" not in doc:
            raise IngestError(
                f"document at index {idx} missing required field 'doc_id'"
            )
        if "text" not in doc:
            raise IngestError(
                f"document at index {idx} missing required field 'text'"
            )

        doc_id = doc["doc_id"]
        text = doc["text"]

        # -- P2: detect frontmatter presence --
        has_fm = frontmatter.checks(text)

        # -- parse with upstream behaviour (P3 preserved) --
        metadata, content = frontmatter.parse(text)

        # -- P1: project metadata JSON-safe --
        safe_metadata = _make_json_safe(metadata)

        records.append(
            {
                "doc_id": doc_id,
                "has_frontmatter": has_fm,
                "metadata": safe_metadata,
                "content": content,
            }
        )

    return {"records": records}
