"""Append-only, tamper-evident run trace.

Re-implemented for RepoProof (concept referenced read-only from
LocalFlow's append-only trace.jsonl; no code copied — see
docs/lineage.md). Each JSONL line carries the SHA-256 of the previous
raw line, so any in-place edit, deletion, or reordering breaks the
chain and is detectable by ``verify_chain``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from repoproof.domain.models import RunEvent, sha256_bytes


class TraceTampered(RuntimeError):
    pass


class TraceWriter:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = 0
        self._prev_hash: str | None = None
        if self.path.exists():
            # Resume append-only — but FIRST verify the existing chain;
            # appending to a tampered trace would launder it.
            ok, at, err = verify_chain(self.path)
            if not ok:
                raise TraceTampered(f"refusing to append to broken trace at seq {at}: {err}")
            lines = self.path.read_bytes().splitlines()
            self._seq = len(lines)
            if lines:
                self._prev_hash = sha256_bytes(lines[-1])

    def append(
        self,
        event: str,
        *,
        actor: str,
        payload: dict | None = None,
        artifact_refs: list[str] | None = None,
    ) -> RunEvent:
        row = RunEvent(
            seq=self._seq,
            ts=datetime.now(UTC).isoformat(),
            event=event,
            actor=actor,
            payload=payload or {},
            artifact_refs=artifact_refs or [],
            prev_sha256=self._prev_hash,
        )
        line = json.dumps(row.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        self._prev_hash = sha256_bytes(line.encode("utf-8"))
        self._seq += 1
        return row


def verify_chain(path: Path) -> tuple[bool, int, str]:
    """Walk the trace and re-derive the hash chain.

    Returns (ok, n_events, error). Any modified, dropped, or reordered
    line surfaces as a chain break at the first affected seq.
    """
    lines = Path(path).read_bytes().splitlines()
    prev_hash: str | None = None
    for i, raw in enumerate(lines):
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            return False, i, f"line {i}: not JSON ({exc})"
        if row.get("seq") != i:
            return False, i, f"line {i}: seq={row.get('seq')} expected {i}"
        if row.get("prev_sha256") != prev_hash:
            return False, i, f"line {i}: prev_sha256 mismatch (chain broken)"
        prev_hash = sha256_bytes(raw)
    return True, len(lines), ""


def scan_events(path: Path, event: str | None = None) -> list[dict]:
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if event is None:
        return rows
    return [r for r in rows if r.get("event") == event]
