"""Task package freezing and verification.

``freeze`` is a HUMAN pre-run step (CLI `freeze-task`): it binds the
contract hash, oracle tree, public/held-out fixtures, consumer fixture
baseline tree, source commit + git tree hash and acceptance commands
into a committed TaskPackageManifest with a root hash. The runner may
only ``verify`` — after a run starts, nothing regenerates the package.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from repoproof.domain.models import (
    ContractTampered,
    TaskContract,
    TaskPackageManifest,
    sha256_file,
)
from repoproof.harness.oracle_guard import OracleViolation


def _tree_sha(root: Path) -> str:
    """Content tree hash. Volatile build artifacts (__pycache__/*.pyc)
    are excluded — a host pytest import must not read as tampering.
    Symlinks are still rejected via hash_tree's guard semantics."""
    entries: dict[str, str] = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_symlink():
            raise OracleViolation(f"symlink not allowed in guarded tree: {p}")
        if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        entries[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    canon = json.dumps(entries, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()


def manifest_path_for(contract_path: Path) -> Path:
    return contract_path.parent / (contract_path.stem + ".package.json")


def freeze(project_root: Path, contract_path: Path, *, upstream_dir: Path) -> TaskPackageManifest:
    contract, contract_sha = TaskContract.load_frozen(contract_path, require_sidecar=True)
    oracle_dir = project_root / "oracle" / contract.task_id
    public_fx = oracle_dir / "fixtures" / "public_documents.json"
    held_out_fx = oracle_dir / "fixtures" / "held_out_documents.json"
    consumer_dir = project_root / Path(contract.target_project.path)

    git_tree = subprocess.run(
        ["git", "-C", str(upstream_dir), "rev-parse", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    head = subprocess.run(
        ["git", "-C", str(upstream_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    manifest = TaskPackageManifest(
        task_id=contract.task_id,
        contract_sha256=contract_sha,
        oracle_tree_sha256=_tree_sha(oracle_dir),
        public_fixture_sha256=sha256_file(public_fx),
        held_out_fixture_sha256=sha256_file(held_out_fx) if held_out_fx.exists() else None,
        consumer_fixture_tree_sha256=_tree_sha(consumer_dir),
        source_commit=head,
        source_git_tree_hash=git_tree,
        acceptance_capability_command=contract.acceptance.capability_command,
        acceptance_regression_command=contract.acceptance.regression_command,
    )
    manifest = manifest.model_copy(update={"root_hash": manifest.compute_root_hash()})
    out = manifest_path_for(contract_path)
    out.write_text(json.dumps(manifest.model_dump(), indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def load_and_verify(project_root: Path, contract_path: Path) -> TaskPackageManifest:
    """Runner-side: load the COMMITTED manifest and verify every binding
    against the working tree. Any mismatch refuses the run — the runner
    never regenerates the package."""
    mp = manifest_path_for(contract_path)
    if not mp.exists():
        raise ContractTampered(f"task package manifest missing: {mp.name} (run freeze-task first)")
    manifest = TaskPackageManifest.model_validate(json.loads(mp.read_text(encoding="utf-8")))
    if manifest.compute_root_hash() != manifest.root_hash:
        raise ContractTampered("task package root hash mismatch (manifest edited?)")

    contract, contract_sha = TaskContract.load_frozen(contract_path, require_sidecar=True)
    problems: list[str] = []
    if contract_sha != manifest.contract_sha256:
        problems.append("contract sha changed since freeze")
    oracle_dir = project_root / "oracle" / contract.task_id
    if _tree_sha(oracle_dir) != manifest.oracle_tree_sha256:
        problems.append("oracle tree changed since freeze")
    public_fx = oracle_dir / "fixtures" / "public_documents.json"
    if sha256_file(public_fx) != manifest.public_fixture_sha256:
        problems.append("public fixture changed since freeze")
    held = oracle_dir / "fixtures" / "held_out_documents.json"
    if manifest.held_out_fixture_sha256 and sha256_file(held) != manifest.held_out_fixture_sha256:
        problems.append("held-out fixture changed since freeze")
    consumer_dir = project_root / Path(contract.target_project.path)
    if _tree_sha(consumer_dir) != manifest.consumer_fixture_tree_sha256:
        problems.append("consumer fixture tree changed since freeze")
    if problems:
        raise ContractTampered("task package verification failed: " + "; ".join(problems))
    return manifest
