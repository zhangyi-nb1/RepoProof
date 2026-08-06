"""Trusted calibration probe — generate reference partitions from the
PINNED Chonkie inside the PINNED container env.

For each fixture document and each frozen strategy, instantiate the
chunker with the CONTRACT-frozen parameters (verified against the real
v1.7.0 signatures: SentenceChunker(tokenizer, chunk_size,
chunk_overlap, ...); RecursiveChunker(tokenizer, chunk_size, ...) — NO
chunk_overlap for recursive) and record:

  * every chunk's (start, end, text, token_count);
  * slice_back: text == source[start:end] for every chunk;
  * within_chunk_size: token_count <= chunk_size;
  * gaps between consecutive chunks and whether gaps are
    whitespace-only (coverage accounting);
  * strategy sensitivity: whether sentence vs recursive boundaries
    differ per document.

stdlib + chonkie only. Output: one JSON document on stdout.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    fixture_paths = sys.argv[1:]
    chunk_size = int(sys.argv[sys.argv.index("--chunk-size") + 1]) if "--chunk-size" in sys.argv else 120
    fixture_paths = [p for p in fixture_paths if not p.startswith("--") and not p.isdigit()]

    import chonkie

    chunkers = {
        "sentence": lambda: chonkie.SentenceChunker(
            tokenizer="character", chunk_size=chunk_size, chunk_overlap=0
        ),
        "recursive": lambda: chonkie.RecursiveChunker(
            tokenizer="character", chunk_size=chunk_size
        ),
    }

    out: dict = {"chonkie_version": chonkie.__version__, "chunk_size": chunk_size, "fixtures": {}}
    for path in fixture_paths:
        with open(path, encoding="utf-8") as fh:
            docs = json.load(fh)["documents"]
        fx: dict = {}
        for doc in docs:
            text = doc["text"]
            entry: dict = {"length": len(text), "strategies": {}}
            for name, make in chunkers.items():
                try:
                    chunks = make().chunk(text)
                except Exception as exc:  # noqa: BLE001 — recording upstream behaviour
                    entry["strategies"][name] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
                    continue
                rows = []
                slice_ok = True
                within = True
                gaps = []
                prev_end = 0
                for ch in chunks:
                    s, e = ch.start_index, ch.end_index
                    rows.append(
                        {"start": s, "end": e, "token_count": ch.token_count, "text": ch.text}
                    )
                    if text[s:e] != ch.text:
                        slice_ok = False
                    if ch.token_count > chunk_size:
                        within = False
                    if s > prev_end:
                        gap = text[prev_end:s]
                        gaps.append({"from": prev_end, "to": s, "ws_only": gap.strip() == ""})
                    prev_end = max(prev_end, e)
                tail_gap = len(text) - prev_end
                entry["strategies"][name] = {
                    "count": len(rows),
                    "slice_back_ok": slice_ok,
                    "all_within_chunk_size": within,
                    "gaps": gaps,
                    "tail_uncovered": tail_gap,
                    "tail_ws_only": text[prev_end:].strip() == "" if tail_gap else True,
                    "chunks": rows,
                }
            strategies = entry["strategies"]
            if "error" not in strategies.get("sentence", {}) and "error" not in strategies.get("recursive", {}):
                sb = [(c["start"], c["end"]) for c in strategies["sentence"]["chunks"]]
                rb = [(c["start"], c["end"]) for c in strategies["recursive"]["chunks"]]
                entry["strategy_sensitive"] = sb != rb
            fx[doc["document_id"]] = entry
        out["fixtures"][path.split("/")[-1]] = fx

    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
