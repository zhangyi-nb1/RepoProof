"""POSITIVE CONTROL (frontmatter v2) — trusted Reference Adapter,
ORACLE CALIBRATION ONLY. Proves the v2 contract is satisfiable. Never
shipped to agents, prompts, or adoption bundles."""

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
    from rag_ingest.errors import IngestError

    records = []
    for doc in request["documents"]:
        text = doc["text"]
        try:
            metadata, content = frontmatter.parse(text)
        except Exception as exc:  # noqa: BLE001 — wrap per contract
            raise IngestError(
                f"upstream parse failed for {doc['doc_id']!r}: {type(exc).__name__}",
                code="UPSTREAM_PARSE_ERROR",
            ) from exc
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
