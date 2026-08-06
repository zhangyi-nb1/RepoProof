from pathlib import Path

import pytest

from repoproof.harness.artifacts import ArtifactStore
from repoproof.harness.oracle_guard import OracleViolation, hash_tree, make_read_only, trees_equal
from repoproof.harness.policy import TrustZones, evaluate_argv, evaluate_write_path


def test_artifact_store_content_addressed(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    a = store.store_bytes(b"hello", media_type="text/plain", producer="t")
    b = store.store_bytes(b"hello", media_type="text/plain", producer="t2")
    assert a.sha256 == b.sha256
    assert store.read(a.sha256) == b"hello"
    assert (tmp_path / "objects" / a.sha256).exists()


def _zones(tmp_path: Path) -> TrustZones:
    for name in ("upstream", "oracle", "adaptation"):
        (tmp_path / name).mkdir(exist_ok=True)
    return TrustZones(
        upstream=tmp_path / "upstream",
        oracle=tmp_path / "oracle",
        adaptation=tmp_path / "adaptation",
    )


def test_policy_denies_oracle_and_upstream_writes(tmp_path: Path) -> None:
    z = _zones(tmp_path)
    assert not evaluate_write_path(z, z.oracle / "test_capability.py").allowed
    assert not evaluate_write_path(z, z.upstream / "setup.py").allowed
    assert evaluate_write_path(z, z.adaptation / "adapter.py").allowed


def test_policy_denies_traversal_out_of_zones(tmp_path: Path) -> None:
    z = _zones(tmp_path)
    sneaky = z.adaptation / ".." / "oracle" / "test_capability.py"
    assert not evaluate_write_path(z, sneaky).allowed


def test_argv_policy_blocks_forbidden_extras_and_privileged() -> None:
    assert not evaluate_argv(["pip", "install", "chonkie[all]"]).allowed
    assert not evaluate_argv(["pip", "install", "torch"]).allowed
    assert not evaluate_argv(["docker", "run", "--privileged", "x"]).allowed
    assert evaluate_argv(["/venv/env/bin/pip", "install", "/tmp/build"]).allowed
    assert evaluate_argv(["python", "-m", "pytest", "-q"]).allowed


def test_oracle_hash_and_symlink_rejection(tmp_path: Path) -> None:
    root = tmp_path / "oracle"
    root.mkdir()
    (root / "t.py").write_text("x = 1\n")
    before = hash_tree(root)
    (root / "t.py").write_text("x = 2\n")
    after = hash_tree(root)
    ok, diffs = trees_equal(before, after)
    assert not ok and diffs == ["t.py"]

    (root / "link.py").symlink_to("/etc/hosts")
    with pytest.raises(OracleViolation):
        hash_tree(root)


def test_make_read_only(tmp_path: Path) -> None:
    root = tmp_path / "guarded"
    root.mkdir()
    target = root / "f.txt"
    target.write_text("keep")
    make_read_only(root)
    with pytest.raises(PermissionError):
        target.write_text("nope")
