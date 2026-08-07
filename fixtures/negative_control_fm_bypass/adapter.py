"""NEGATIVE CONTROL NC4 (v2) — exception-contract breaker.

Handles the happy path correctly but lets raw upstream exceptions
escape (no IngestError wrapping) — breaking the host's unified error
type. The oracle must reject it on the upstream-error contract. (The
host InputContractGuard itself cannot be bypassed structurally: it
runs before the adapter is consulted; this control targets the
adapter-owned half of the error contract.) Test fixture only."""

from __future__ import annotations

import datetime


def _project(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _project(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_project(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def ingest_documents(request: dict) -> dict:
    import frontmatter

    records = []
    for doc in request["documents"]:
        text = doc["text"]
        metadata, content = frontmatter.parse(text)  # CHEAT: raw ParserError escapes
        records.append(
            {
                "doc_id": doc["doc_id"],
                "frontmatter_present": bool(metadata) or (content != text.strip()),
                "metadata_nonempty": len(metadata) > 0,
                "metadata": _project(metadata),
                "content": content,
            }
        )
    return {"records": records}
