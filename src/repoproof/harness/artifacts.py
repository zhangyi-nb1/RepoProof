"""Content-addressed artifact store (SHA-256).

Large outputs (stdout/stderr, pip logs, probe dumps, manifests) live
here as immutable objects; trace events reference them by hash, never
by mutable path alone.
"""

from __future__ import annotations

import json
from pathlib import Path

from repoproof.domain.models import ArtifactRef, sha256_bytes


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "objects").mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.jsonl"

    def store_bytes(
        self, data: bytes, *, media_type: str, producer: str, name_hint: str = ""
    ) -> ArtifactRef:
        digest = sha256_bytes(data)
        obj = self.root / "objects" / digest
        if not obj.exists():
            obj.write_bytes(data)
        ref = ArtifactRef(
            sha256=digest,
            size=len(data),
            media_type=media_type,
            producer=producer,
            name_hint=name_hint,
            stored_path=str(obj),
        )
        with self.index_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ref.model_dump(), ensure_ascii=False, sort_keys=True) + "\n")
        return ref

    def store_file(self, path: Path, *, media_type: str, producer: str) -> ArtifactRef:
        p = Path(path)
        return self.store_bytes(
            p.read_bytes(), media_type=media_type, producer=producer, name_hint=p.name
        )

    def read(self, sha256: str) -> bytes:
        return (self.root / "objects" / sha256).read_bytes()
