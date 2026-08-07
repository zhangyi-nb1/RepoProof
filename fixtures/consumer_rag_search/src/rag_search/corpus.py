"""Pre-existing host capability: load the search corpus + queries."""

from __future__ import annotations

import json
from pathlib import Path


def load_corpus(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    for doc in payload["documents"]:
        if "chunk_id" not in doc or "text" not in doc:
            raise ValueError("corpus document must carry chunk_id and text")
    return payload


def health() -> str:
    return "ok"
