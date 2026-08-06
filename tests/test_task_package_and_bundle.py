"""Task package freeze/verify + bundle integrity + trace resume guard."""

import json
import subprocess
from pathlib import Path

import pytest

from repoproof.domain.models import ContractTampered, TaskContract
from repoproof.harness import task_package
from repoproof.harness.trace import TraceTampered, TraceWriter, verify_chain
from repoproof.persistence.run_store import FileRunStore
from repoproof.verification.bundle_check import verify_bundle

MINI_CONTRACT = """\
task_id: mini-task
source_repo:
  url: file:///nowhere
  revision: main
  resolved_commit: "{commit}"
  license: MIT
target_project:
  kind: consumer_fixture
  path: consumer
capability:
  statement: mini
  output_schema: ChunkRecord
environment: {{}}
constraints: {{}}
budgets: {{}}
acceptance:
  capability_command: ["pytest", "-q", "/oracle/test_capability.py"]
  regression_command: ["pytest", "-q", "/oracle/test_regression.py"]
"""


def _mini_project(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Self-contained mini project + git upstream for package tests."""
    root = tmp_path / "proj"
    (root / "oracle" / "mini-task" / "fixtures").mkdir(parents=True)
    (root / "oracle" / "mini-task" / "fixtures" / "public_documents.json").write_text('{"documents": []}')
    (root / "oracle" / "mini-task" / "test_capability.py").write_text("def test_x():\n    assert True\n")
    (root / "consumer").mkdir()
    (root / "consumer" / "app.py").write_text("VALUE = 1\n")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "pkg.py").write_text("X = 1\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=upstream, check=True)
    subprocess.run(["git", "add", "-A"], cwd=upstream, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"],
        cwd=upstream,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=upstream, capture_output=True, text=True, check=True
    ).stdout.strip()
    contract = root / "contracts" / "mini-task.yaml"
    contract.parent.mkdir()
    contract.write_text(MINI_CONTRACT.format(commit=commit))
    import hashlib

    (contract.parent / "mini-task.yaml.sha256").write_text(
        hashlib.sha256(contract.read_bytes()).hexdigest() + "  mini-task.yaml\n"
    )
    return root, contract, upstream


def test_freeze_then_verify_roundtrip(tmp_path: Path) -> None:
    root, contract, upstream = _mini_project(tmp_path)
    manifest = task_package.freeze(root, contract, upstream_dir=upstream)
    assert manifest.root_hash == manifest.compute_root_hash()
    loaded = task_package.load_and_verify(root, contract)
    assert loaded.root_hash == manifest.root_hash


def test_oracle_edit_after_freeze_is_refused(tmp_path: Path) -> None:
    root, contract, upstream = _mini_project(tmp_path)
    task_package.freeze(root, contract, upstream_dir=upstream)
    (root / "oracle" / "mini-task" / "test_capability.py").write_text("def test_x():\n    assert False\n")
    with pytest.raises(ContractTampered, match="oracle tree changed"):
        task_package.load_and_verify(root, contract)


def test_manifest_edit_is_refused(tmp_path: Path) -> None:
    root, contract, upstream = _mini_project(tmp_path)
    task_package.freeze(root, contract, upstream_dir=upstream)
    mp = task_package.manifest_path_for(contract)
    data = json.loads(mp.read_text())
    data["source_commit"] = "0" * 40
    mp.write_text(json.dumps(data))
    with pytest.raises(ContractTampered, match="root hash mismatch"):
        task_package.load_and_verify(root, contract)


def test_missing_sidecar_refused(tmp_path: Path) -> None:
    c = tmp_path / "c.yaml"
    c.write_text(MINI_CONTRACT.format(commit="0" * 40))
    with pytest.raises(ContractTampered, match="not frozen"):
        TaskContract.load_frozen(c, require_sidecar=True)


def test_trace_resume_refuses_tampered_chain(tmp_path: Path) -> None:
    p = tmp_path / "trace.jsonl"
    tw = TraceWriter(p)
    tw.append("run.start", actor="runner")
    tw.append("run.end", actor="runner")
    lines = p.read_text().splitlines()
    row = json.loads(lines[0])
    row["payload"]["forged"] = True
    lines[0] = json.dumps(row, ensure_ascii=False, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    with pytest.raises(TraceTampered):
        TraceWriter(p)


def test_bundle_check_detects_artifact_corruption(tmp_path: Path) -> None:
    store = FileRunStore(tmp_path / "run")
    ref = store.store_artifact(b"evidence", media_type="text/plain", producer="t")
    store.append_event("action.end", actor="runner", payload={"action_id": "a1"}, artifact_refs=[ref.sha256])
    from repoproof.domain.models import VerificationResult, sha256_file

    store.save_verification(
        VerificationResult(verifier="CapabilityVerifier", passed=True, detail="t", evidence=[ref.sha256])
    )
    ok, n, _ = verify_chain(store.trace_path)
    assert ok
    store.save_json(
        "run_manifest.json",
        {"final_trace_sha256": sha256_file(store.trace_path), "trace_events": n},
    )
    good = verify_bundle(store.run_dir, tmp_path, None)
    by_name = {c["name"]: c for c in good["checks"]}
    assert by_name["trace_chain"]["ok"] and by_name["final_trace_sha256"]["ok"] and by_name["artifacts"]["ok"]

    # corrupt the stored artifact content
    obj = store.run_dir / "artifacts" / "objects" / ref.sha256
    obj.write_bytes(b"tampered")
    bad = verify_bundle(store.run_dir, tmp_path, None)
    assert not bad["ok"]
    assert any(c["name"] == "artifacts" and not c["ok"] for c in bad["checks"])
