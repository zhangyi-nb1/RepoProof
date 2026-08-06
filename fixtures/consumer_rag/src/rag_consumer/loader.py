"""Pre-existing host capability: load documents for the RAG pipeline.

This is the part of the host fixture that must KEEP working after any
adoption — covered by the oracle regression tests.
"""

from __future__ import annotations

import json
from pathlib import Path


def load_documents(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    docs = payload["documents"]
    for doc in docs:
        if "document_id" not in doc or "text" not in doc:
            raise ValueError("document must carry document_id and text")
    return docs


def health() -> str:
    return "ok"
