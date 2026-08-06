"""Host-side chunk contract types. stdlib-only on purpose — the
consumer fixture must run in the container with zero extra installs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

CHUNK_RECORD_FIELDS = (
    "chunk_id",
    "document_id",
    "ordinal",
    "text",
    "char_start",
    "char_end",
    "units",
    "metadata",
)


@dataclass
class ChunkRecord:
    chunk_id: str
    document_id: str
    ordinal: int
    text: str
    char_start: int
    char_end: int
    units: int
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
