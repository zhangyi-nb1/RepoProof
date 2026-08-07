"""NEGATIVE CONTROL NC1 (v2) — flag conflation cheat.

Reuses metadata_nonempty as frontmatter_present (the exact ambiguity
v2 was created to kill): an empty-but-recognised block reports
frontmatter_present=false. Schema-perfect otherwise. The oracle must
reject it on the truth table / reference rows for empty fences.
Test fixture only."""

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
    from rag_ingest.errors import IngestError

    import frontmatter

    records = []
    for doc in request["documents"]:
        try:
            metadata, content = frontmatter.parse(doc["text"])
        except Exception as exc:  # noqa: BLE001
            raise IngestError("upstream parse failed", code="UPSTREAM_PARSE_ERROR") from exc
        nonempty = len(metadata) > 0
        records.append(
            {
                "doc_id": doc["doc_id"],
                "frontmatter_present": nonempty,  # CHEAT: conflated with nonempty
                "metadata_nonempty": nonempty,
                "metadata": _project(metadata),
                "content": content,
            }
        )
    return {"records": records}
