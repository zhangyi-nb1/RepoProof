"""NEGATIVE CONTROL (frontmatter task) — regex fence-stripper (cheat).

Schema-perfect records but front matter is 'parsed' by a naive regex
that treats the YAML block as raw key: value lines — no YAML types, no
nesting, no dates, wrong content on tricky fences. Never calls
python-frontmatter. The oracle must reject it. Test fixture only."""

from __future__ import annotations

import re

_FENCE = re.compile(r"\A---\s*\n(.*?)\n?---\s*\n?(.*)\Z", re.DOTALL)


def ingest_documents(request: dict) -> dict:
    from rag_ingest.ingest import IngestError

    records = []
    for doc in request["documents"]:
        text = doc.get("text")
        if not isinstance(text, str):
            raise IngestError("document text must be a string")
        m = _FENCE.match(text)
        if m:
            meta = {}
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()  # everything is a string — wrong
            records.append(
                {"doc_id": doc["doc_id"], "has_frontmatter": bool(meta), "metadata": meta, "content": m.group(2)}
            )
        else:
            records.append(
                {"doc_id": doc["doc_id"], "has_frontmatter": False, "metadata": {}, "content": text}
            )
    return {"records": records}
