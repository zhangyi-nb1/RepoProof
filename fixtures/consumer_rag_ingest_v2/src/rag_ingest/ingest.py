"""Host ingest entrypoint (v2) with the standard adapter seam.

Pipeline: InputContractGuard (host, deterministic, ALWAYS first) ->
adapter ($REPOPROOF_ADAPTATION_DIR/adapter.py -> ingest_documents) or
the naive direct fallback. The fallback is the README-level upstream
call returning raw Post attributes — deliberately NOT contract-shaped
(no flag split, metadata not JSON-safe, upstream errors unwrapped)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from rag_ingest.errors import IngestError
from rag_ingest.guard import validate_request

__all__ = ["IngestError", "ingest_documents"]


def _load_adapter():
    root = os.environ.get("REPOPROOF_ADAPTATION_DIR", "")
    if not root:
        return None
    candidate = Path(root) / "adapter.py"
    if not candidate.exists():
        return None
    spec = importlib.util.spec_from_file_location("repoproof_ingest_adapter", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def ingest_documents(request: dict) -> dict:
    validate_request(request)  # host guard: adapters never see invalid input

    adapter = _load_adapter()
    if adapter is not None:
        return adapter.ingest_documents(request)

    # ---- direct adoption (naive, unadapted) ----
    import frontmatter

    records = []
    for doc in request["documents"]:
        post = frontmatter.loads(doc["text"])
        records.append({"metadata": post.metadata, "content": post.content})
    return {"records": records}
