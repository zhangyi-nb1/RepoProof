"""NEGATIVE CONTROL (bm25 task) — naive word-count ranker (cheat).

Schema-perfect hits, but scores are raw query-term counts — never
calls rank_bm25. The v4 oracle must reject it (rankings/scores differ
from the pinned BM25 reference). Test fixture only."""

from __future__ import annotations


def search_documents(request: dict) -> dict:
    from rag_search.search import SearchError

    docs = request["documents"]
    hits: list[dict] = []
    for q in request["queries"]:
        text = q.get("text")
        if not isinstance(text, str):
            raise SearchError("query text must be a string")
        if text.strip() == "":
            continue
        terms = text.lower().split()
        pairs = [
            {
                "chunk_id": d["chunk_id"],
                "score": round(float(sum(d["text"].lower().split().count(t) for t in terms)), 6),
                "text": d["text"],
            }
            for d in docs
        ]
        pairs.sort(key=lambda p: (-p["score"], p["chunk_id"]))
        for rank, p in enumerate(pairs[: int(q["top_k"])]):
            hits.append({"query_id": q["query_id"], "rank": rank, **p})
    return {"hits": hits}
