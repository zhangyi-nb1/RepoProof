"""Calibration/diagnostic probe for the rank_bm25 adoption task.

Runs the PINNED rank_bm25 with the contract-frozen tokenization
(lowercased whitespace split) over the fixture corpus and emits, per
query, the FULL deterministic ranking [(chunk_id, score)] with scores
rounded to 6 decimals and ties broken by (score desc, chunk_id asc).
stdlib + rank_bm25 only.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    path = sys.argv[1]
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    docs = payload["documents"]
    queries = payload.get("queries", [])

    from rank_bm25 import BM25Okapi

    tokenized = [d["text"].lower().split() for d in docs]
    bm25 = BM25Okapi(tokenized)
    out: dict = {"upstream": "rank_bm25.BM25Okapi", "tokenization": "lower+whitespace", "rankings": {}}
    for q in queries:
        scores = bm25.get_scores(q["text"].lower().split())
        pairs = [
            {"chunk_id": docs[i]["chunk_id"], "score": round(float(s), 6)}
            for i, s in enumerate(scores)
        ]
        pairs.sort(key=lambda p: (-p["score"], p["chunk_id"]))
        out["rankings"][q["query_id"]] = pairs
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
