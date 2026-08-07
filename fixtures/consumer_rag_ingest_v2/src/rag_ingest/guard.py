"""InputContractGuard — deterministic HOST-side input validation.

Runs BEFORE any adapter is consulted. Malformed request entries are
converted to a stable IngestError with code INVALID_DOCUMENT_INPUT.
This is Consumer/Host responsibility: agent adapters receive only
already-validated documents and MUST NOT re-implement (or bypass)
these checks. Zero dependencies, zero LLM, pure functions.
"""

from __future__ import annotations

from rag_ingest.errors import IngestError

INVALID_DOCUMENT_INPUT = "INVALID_DOCUMENT_INPUT"


def _reject(message: str) -> None:
    raise IngestError(message, code=INVALID_DOCUMENT_INPUT)


def validate_request(request: object) -> None:
    """Validate the full ingest request; raises IngestError(code=
    INVALID_DOCUMENT_INPUT) on the first violation. Never mutates or
    copies the input."""
    if not isinstance(request, dict):
        _reject("request must be a dict")
    documents = request.get("documents")
    if not isinstance(documents, list):
        _reject("request must contain a 'documents' list")
    for idx, doc in enumerate(documents):
        if not isinstance(doc, dict):
            _reject(f"document #{idx} must be a dict")
        if "doc_id" not in doc:
            _reject(f"document #{idx} is missing 'doc_id'")
        doc_id = doc["doc_id"]
        if not isinstance(doc_id, str) or not doc_id.strip():
            _reject(f"document #{idx} 'doc_id' must be a non-empty string")
        if "text" not in doc:
            _reject(f"document {doc_id!r} is missing 'text'")
        if not isinstance(doc["text"], str):
            _reject(f"document {doc_id!r} 'text' must be a string")
