"""Pre-existing host capability: load raw markdown documents."""

from __future__ import annotations

import json
from pathlib import Path


def load_documents(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        docs = json.load(fh)["documents"]
    for d in docs:
        if "doc_id" not in d or "text" not in d:
            raise ValueError("document must carry doc_id and text")
    return docs


def health() -> str:
    return "ok"
