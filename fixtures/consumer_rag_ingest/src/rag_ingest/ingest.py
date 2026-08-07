"""Host ingest entrypoint with the standard adapter seam
($REPOPROOF_ADAPTATION_DIR/adapter.py -> ingest_documents). The direct
fallback is the naive README-level python-frontmatter call returning
raw Post attributes — deliberately NOT contract-shaped (metadata not
JSON-safe, no doc attribution fields, upstream errors unwrapped)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


class IngestError(RuntimeError):
    """Stable host-side error for malformed inputs / upstream failures."""


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
