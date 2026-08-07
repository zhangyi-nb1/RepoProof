"""Host search entrypoint with an adapter seam (same pattern as the
chunking consumer): $REPOPROOF_ADAPTATION_DIR/adapter.py providing
search_documents(request) wins; otherwise the naive README-level
direct adoption of rank_bm25 runs — raw scores, no ids, no ranking
contract, whitespace split only. The direct path is deliberately NOT
a solution.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


class SearchError(RuntimeError):
    """Stable host-side error required for upstream/malformed failures."""


def _load_adapter():
    root = os.environ.get("REPOPROOF_ADAPTATION_DIR", "")
    if not root:
        return None
    candidate = Path(root) / "adapter.py"
    if not candidate.exists():
        return None
    spec = importlib.util.spec_from_file_location("repoproof_search_adapter", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def search_documents(request: dict) -> dict:
    adapter = _load_adapter()
    if adapter is not None:
        return adapter.search_documents(request)

    # ---- direct adoption (naive README-level, unadapted) ----
    from rank_bm25 import BM25Okapi

    corpus = [d["text"] for d in request["documents"]]
    bm25 = BM25Okapi([t.split() for t in corpus])
    hits = []
    for q in request["queries"]:
        scores = bm25.get_scores(q["text"].split())
        hits.append({"query": q["text"], "raw_scores": [float(s) for s in scores]})
    return {"hits": hits}
