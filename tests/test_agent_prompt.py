"""Prompt contamination regression — born from the Gate 6 run.

The old module-level AGENT_PROMPT_TEMPLATE hardcoded chonkie deliverable
text; the frontmatter task's agent received 'def chunk_documents' /
'document_id' / 'ConsumerChunkingError' inside its prompt and trusted
the contaminated request shape over the consumer source it had already
read. These tests pin the contract-driven renderer so no task's prompt
can ever carry another task's tokens again."""

from __future__ import annotations

from pathlib import Path

from repoproof.domain.models import TaskContract
from repoproof.runner.agent_run import render_agent_prompt

REPO = Path(__file__).resolve().parent.parent
FM = REPO / "contracts" / "adopt-frontmatter-local-ingest-v1.yaml"
BM25 = REPO / "contracts" / "adopt-rank-bm25-local-search-v1.yaml"
CHONKIE_V3 = REPO / "contracts" / "adopt-chonkie-local-chunking-v3.yaml"

CHONKIE_TOKENS = (
    "chunk_documents", "rag_consumer", "document_id", "chunk_id",
    "ConsumerChunkingError", "chonkie", "sample_documents.json",
    "whitespace-only documents", "never re-split",
)


def _prompt(path: Path, installed: str, sample: str = "") -> str:
    contract, _ = TaskContract.load_frozen(path, require_sidecar=True)
    return render_agent_prompt(
        contract, command_budget=40, cmd_timeout=300,
        installed_note=installed, sample_inputs_line=sample,
    )


def test_frontmatter_prompt_has_no_chonkie_tokens() -> None:
    prompt = _prompt(FM, "python-frontmatter 1.3.0")
    for token in CHONKIE_TOKENS:
        assert token not in prompt, f"contaminated by {token!r}"
    assert "def ingest_documents(request: dict) -> dict" in prompt
    assert "from rag_ingest import ingest_documents" in prompt
    assert "/consumer/src/rag_ingest/" in prompt
    assert "AUTHORITATIVE" in prompt  # do-not-invent-field-names clause
    assert "python-frontmatter 1.3.0" in prompt
    assert "FROZEN PARAMETERS" not in prompt  # chunking params absent
    assert "model calls: 20" in prompt


def test_chonkie_v3_prompt_still_renders_its_own_task() -> None:
    prompt = _prompt(CHONKIE_V3, "chonkie 1.7.0",
                     "- /consumer/sample_documents.json   public sample inputs you may test with\n")
    assert "def chunk_documents(request: dict) -> dict" in prompt
    assert "from rag_consumer import chunk_documents" in prompt
    assert "FROZEN PARAMETERS" in prompt and "chunk_size" in prompt
    assert "frontmatter" not in prompt and "rag_ingest" not in prompt


def test_no_cross_contract_entry_point_leakage() -> None:
    contracts = {
        p: TaskContract.load_frozen(p, require_sidecar=True)[0]
        for p in (FM, BM25, CHONKIE_V3)
    }
    for path, contract in contracts.items():
        prompt = render_agent_prompt(
            contract, command_budget=40, cmd_timeout=300,
            installed_note=contract.source_repo.distribution,
        )
        for other_path, other in contracts.items():
            if other_path is path or other.target_project.entry_point == contract.target_project.entry_point:
                continue
            assert other.target_project.entry_point not in prompt, (
                f"{path.name} prompt leaks {other.target_project.entry_point}"
            )
            assert other.target_project.package not in prompt


def test_prompt_never_hardcodes_request_field_names() -> None:
    """The renderer must not assert request/record field names — the
    consumer source is the single authority (that is the exact failure
    the Gate 6 agent hit)."""
    prompt = _prompt(FM, "python-frontmatter 1.3.0")
    assert "Request shape:" not in prompt
    assert '"doc_id"' not in prompt and '"document_id"' not in prompt
