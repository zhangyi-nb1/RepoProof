"""Calibration probe for the python-frontmatter adoption task.

Runs the PINNED frontmatter.loads over each fixture document and emits
the reference records under the contract's JSON-safety projection P1:
date/datetime metadata values -> ISO strings; str/int/float/bool/None
kept; lists/dicts projected recursively; anything else -> str(value).
has_frontmatter = (metadata != {}). stdlib + frontmatter only.
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

    out = {"upstream": "python-frontmatter.loads", "records": {}}
    for d in docs:
        try:
            post = frontmatter.loads(d["text"])
            meta = project(post.metadata)
            out["records"][d["doc_id"]] = {
                "has_frontmatter": bool(post.metadata),
                "metadata": meta,
                "content": post.content,
            }
        except Exception as exc:  # noqa: BLE001 — record raw upstream behaviour
            out["records"][d["doc_id"]] = {"upstream_error": f"{type(exc).__name__}: {exc}"[:200]}
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
