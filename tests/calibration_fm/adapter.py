"""POSITIVE CONTROL (frontmatter task) — trusted Reference Adapter,
ORACLE CALIBRATION ONLY. Never shipped to agents or bundles."""

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
    from rag_ingest.ingest import IngestError

    try:
        import frontmatter

        records = []
        for doc in request["documents"]:
            text = doc.get("text")
            if not isinstance(text, str):
                raise IngestError(f"{doc.get('doc_id')}: document text must be a string")
            post = frontmatter.loads(text)
            metadata = _project(post.metadata)
            records.append(
                {
                    "doc_id": doc["doc_id"],
                    "has_frontmatter": bool(post.metadata),  # P2
                    "metadata": metadata,
                    "content": post.content,
                }
            )
        return {"records": records}
    except IngestError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"upstream failure: {type(exc).__name__}: {exc}") from exc
