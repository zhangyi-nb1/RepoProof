"""Host chunking entrypoint with an adapter seam.

Resolution order:
  1. If ``$REPOPROOF_ADAPTATION_DIR/adapter.py`` exists (the future
     agent's deliverable, Gate 3), load it and delegate.
  2. Otherwise fall back to DIRECT ADOPTION: the naive README-level
     Chonkie call, returning whatever upstream returns, upstream field
     names, upstream ids, upstream exceptions and all.

The direct path is intentionally NOT a solution — it is the honest
baseline any integrator gets on day one, and the oracle capability
tests measure exactly where it falls short of the ChunkRecord
contract. Writing the real mapping is the agent's job, not ours.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


class ConsumerChunkingError(RuntimeError):
    """Stable host-side error the contract requires for upstream failures."""


def _load_adapter():
    root = os.environ.get("REPOPROOF_ADAPTATION_DIR", "")
    if not root:
        return None
    candidate = Path(root) / "adapter.py"
    if not candidate.exists():
        return None
    spec = importlib.util.spec_from_file_location("repoproof_adapter", candidate)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def chunk_documents(request: dict) -> dict:
    adapter = _load_adapter()
    if adapter is not None:
        return adapter.chunk_documents(request)

    # ---- direct adoption (naive, deliberately unadapted) ----
    from chonkie import SentenceChunker

    chunker = SentenceChunker()
    records = []
    for doc in request["documents"]:
        for chunk in chunker.chunk(doc["text"]):
            rec = {}
            for attr in ("id", "text", "start_index", "end_index", "token_count"):
                if hasattr(chunk, attr):
                    rec[attr] = getattr(chunk, attr)
            records.append(rec)
    return {"records": records}
