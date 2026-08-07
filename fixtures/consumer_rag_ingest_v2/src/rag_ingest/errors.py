"""Stable host-side error type with a machine-readable code."""

from __future__ import annotations


class IngestError(RuntimeError):
    """Raised for malformed inputs (code=INVALID_DOCUMENT_INPUT, from
    the host InputContractGuard) and for wrapped upstream parse
    failures (code=UPSTREAM_PARSE_ERROR, from the adapter)."""

    def __init__(self, message: str, *, code: str = "INGEST_ERROR"):
        super().__init__(message)
        self.code = code
