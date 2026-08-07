"""POSITIVE CONTROL (bm25 task) — trusted Reference Adapter, ORACLE
CALIBRATION ONLY. Never shipped to agent workspaces or bundles
(pinned by tests/test_gate5_portability.py)."""

from __future__ import annotations


def search_documents(request: dict) -> dict:
    from rag_search.search import SearchError

    try:
        from rank_bm25 import BM25Okapi

        docs = request["documents"]
        tokenized = [d["text"].lower().split() for d in docs]
        bm25 = BM25Okapi(tokenized)
        hits: list[dict] = []
        for q in request["queries"]:
            text = q.get("text")
            if not isinstance(text, str):
                raise SearchError(f"{q.get('query_id')}: query text must be a string")
            if text.strip() == "":  # S4
                continue
            scores = bm25.get_scores(text.lower().split())
            pairs = [
                {"chunk_id": docs[i]["chunk_id"], "score": round(float(s), 6), "text": docs[i]["text"]}
                for i, s in enumerate(scores)
            ]
            pairs.sort(key=lambda p: (-p["score"], p["chunk_id"]))  # S3
            for rank, p in enumerate(pairs[: int(q["top_k"])]):  # S5
                hits.append(
                    {
                        "query_id": q["query_id"],
                        "rank": rank,
                        "chunk_id": p["chunk_id"],
                        "score": p["score"],
                        "text": p["text"],
                    }
                )
        return {"hits": hits}
    except SearchError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SearchError(f"upstream failure: {type(exc).__name__}: {exc}") from exc
