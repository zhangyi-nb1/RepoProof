from pathlib import Path

import pytest

from repoproof.domain.models import ContractTampered, TaskContract

REPO = Path(__file__).resolve().parent.parent
CONTRACT = REPO / "contracts" / "adopt-chonkie-local-chunking-v1.yaml"


def test_contract_loads_and_matches_sidecar() -> None:
    contract, digest = TaskContract.load_frozen(CONTRACT)
    assert contract.task_id == "adopt-chonkie-local-chunking-v1"
    assert contract.source_repo.resolved_commit == "0a6baea1a42c9afe9b3bc31ecb37739e744bb1ec"
    assert contract.environment.network_test is False
    pinned = (CONTRACT.parent / (CONTRACT.name + ".sha256")).read_text().split()[0]
    assert digest == pinned


def test_contract_has_no_expected_verdict_leak() -> None:
    raw = CONTRACT.read_text(encoding="utf-8")
    assert "expected_verdict" not in raw
    assert "PASS_ADAPTED" not in raw  # the human benchmark label must not leak


def test_tampered_contract_rejected(tmp_path: Path) -> None:
    copy = tmp_path / "c.yaml"
    copy.write_bytes(CONTRACT.read_bytes())
    (tmp_path / "c.yaml.sha256").write_text("0" * 64 + "  c.yaml\n")
    with pytest.raises(ContractTampered):
        TaskContract.load_frozen(copy)


def test_agent_never_edits_contract_semantics(tmp_path: Path) -> None:
    """Any byte change flips the digest — freezing is byte-level."""
    copy = tmp_path / "c.yaml"
    data = CONTRACT.read_bytes().replace(b"max_agent_steps: 20", b"max_agent_steps: 99")
    copy.write_bytes(data)
    _, digest = TaskContract.load_frozen(copy)  # no sidecar -> loads
    _, original_digest = TaskContract.load_frozen(CONTRACT)
    assert digest != original_digest
