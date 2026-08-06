"""RunStore protocol + Gate 2 file/JSONL implementation.

MySQL is deliberately deferred until the agent loop is stable (design
spec §12); JSONL remains the export format either way. Any future
MySQL store implements this same protocol.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from repoproof.domain.models import ArtifactRef, RunEvent, VerificationResult
from repoproof.harness.artifacts import ArtifactStore
from repoproof.harness.trace import TraceWriter


class RunStore(Protocol):
    def append_event(
        self, event: str, *, actor: str, payload: dict | None = None, artifact_refs: list[str] | None = None
    ) -> RunEvent: ...

    def store_artifact(self, data: bytes, *, media_type: str, producer: str, name_hint: str = "") -> ArtifactRef: ...

    def save_verification(self, result: VerificationResult) -> Path: ...

    def save_json(self, name: str, payload: dict) -> Path: ...


class FileRunStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.trace = TraceWriter(self.run_dir / "trace.jsonl")
        self.artifacts = ArtifactStore(self.run_dir / "artifacts")
        (self.run_dir / "verification").mkdir(exist_ok=True)

    @property
    def trace_path(self) -> Path:
        return self.run_dir / "trace.jsonl"

    def append_event(
        self, event: str, *, actor: str, payload: dict | None = None, artifact_refs: list[str] | None = None
    ) -> RunEvent:
        return self.trace.append(event, actor=actor, payload=payload, artifact_refs=artifact_refs)

    def store_artifact(self, data: bytes, *, media_type: str, producer: str, name_hint: str = "") -> ArtifactRef:
        return self.artifacts.store_bytes(data, media_type=media_type, producer=producer, name_hint=name_hint)

    def save_verification(self, result: VerificationResult) -> Path:
        path = self.run_dir / "verification" / f"{result.verifier}.json"
        path.write_text(json.dumps(result.model_dump(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def save_json(self, name: str, payload: dict) -> Path:
        path = self.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return path
