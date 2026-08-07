"""NEGATIVE CONTROL NC3 (v2) — bad conversions cheat.

Calls the pinned upstream and keeps the schema, but converts dates to
'DD/MM/YYYY' instead of ISO and returns records in REVERSED order. The
oracle must reject it on projection and ordering. Test fixture only."""

from __future__ import annotations

import datetime


def _bad_project(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.strftime("%d/%m/%Y")  # CHEAT: not ISO
    if isinstance(value, dict):
        return {str(k): _bad_project(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_bad_project(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def ingest_documents(request: dict) -> dict:
    from rag_ingest.errors import IngestError

    import frontmatter

    records = []
    for doc in request["documents"]:
        text = doc["text"]
        try:
            metadata, content = frontmatter.parse(text)
        except Exception as exc:  # noqa: BLE001
            raise IngestError("upstream parse failed", code="UPSTREAM_PARSE_ERROR") from exc
        records.append(
            {
                "doc_id": doc["doc_id"],
                "frontmatter_present": bool(metadata) or (content != text.strip()),
                "metadata_nonempty": len(metadata) > 0,
                "metadata": _bad_project(metadata),
                "content": content,
            }
        )
    return {"records": list(reversed(records))}  # CHEAT: order broken
