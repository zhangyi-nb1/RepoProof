"""NEGATIVE CONTROL NC2 (v2) — regex splitter, never calls the pinned
upstream. Schema-perfect records; naive 'key: value' string parsing —
no YAML types, no dates, no JSON fences, wrong on tricky inputs. The
oracle must reject it against the reference. Test fixture only."""

from __future__ import annotations

import re

_FENCE = re.compile(r"\A---\s*\n(.*?)\n?---\s*\n?(.*)\Z", re.DOTALL)


def ingest_documents(request: dict) -> dict:
    records = []
    for doc in request["documents"]:
        text = doc["text"]
        m = _FENCE.match(text)
        if m:
            meta = {}
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()  # everything a string — wrong
            records.append(
                {
                    "doc_id": doc["doc_id"],
                    "frontmatter_present": True,
                    "metadata_nonempty": bool(meta),
                    "metadata": meta,
                    "content": m.group(2),
                }
            )
        else:
            records.append(
                {
                    "doc_id": doc["doc_id"],
                    "frontmatter_present": False,
                    "metadata_nonempty": False,
                    "metadata": {},
                    "content": text,
                }
            )
    return {"records": records}
