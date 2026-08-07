"""Direct-adoption probe for the v2 frontmatter ingest task.

Runs the PINNED frontmatter parse over each fixture document and emits
the raw upstream observation plus the v2 flag split
(frontmatter_present via the contract's operational criterion,
metadata_nonempty) under projection P1. Records raw upstream errors
per document. stdlib + frontmatter only.
"""

from __future__ import annotations

import datetime
import json
import sys


def project(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): project(v) for k, v in value.items()}
    if isinstance(value, list):
        return [project(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as fh:
        docs = json.load(fh)["documents"]
    import frontmatter

    out = {"upstream": "python-frontmatter.parse", "records": {}}
    for d in docs:
        try:
            meta, content = frontmatter.parse(d["text"])
            out["records"][d["doc_id"]] = {
                "frontmatter_present": bool(meta) or (content != d["text"].strip()),
                "metadata_nonempty": len(meta) > 0,
                "metadata": project(meta),
                "content": content,
            }
        except Exception as exc:  # noqa: BLE001 — record raw upstream behaviour
            out["records"][d["doc_id"]] = {"upstream_error": f"{type(exc).__name__}: {exc}"[:200]}
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
