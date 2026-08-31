from __future__ import annotations

import sys
from pathlib import Path

from repoproof.verification.workspace_semantic import (
    run_workspace_semantic_verifier,
    workspace_semantic_evidence_sha256,
)

_VERIFIER = '''from pathlib import Path
import miniworkspace

def verify(input_path: Path, artifact_path: Path) -> dict:
    text = (input_path / "brief.txt").read_text() if input_path.is_dir() else input_path.read_text()
    expected = miniworkspace.render(text)
    actual = (artifact_path / "README.md").read_text()
    ok = actual == expected
    return {
        "ok": ok,
        "reason_codes": [] if ok else ["VALUE_MISMATCH"],
        "checked_commitment_ids": ["render-workspace"],
    }
'''


def _world(tmp_path: Path, *, verifier: str = _VERIFIER) -> dict[str, Path]:
    upstream = tmp_path / "upstream"
    upstream.mkdir(parents=True)
    (upstream / "miniworkspace.py").write_text(
        "def render(text):\n    return '# ' + text.strip() + '\\n'\n",
        encoding="utf-8",
    )
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "brief.txt").write_text("Experiment", encoding="utf-8")
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "README.md").write_text("# Experiment\n", encoding="utf-8")
    verifier_path = tmp_path / "semantic_verifier.py"
    verifier_path.write_text(verifier, encoding="utf-8")
    return {
        "upstream": upstream,
        "input": input_dir,
        "artifact": artifact,
        "verifier": verifier_path,
    }


def _run(world: dict[str, Path]):
    return run_workspace_semantic_verifier(
        verifier_id="workspace-semantics-v1",
        verifier_source=world["verifier"],
        input_path=world["input"],
        artifact_dir=world["artifact"],
        python_exe=sys.executable,
        upstream_dir=world["upstream"],
        import_module="miniworkspace",
        upstream_commit="a" * 40,
        workspace_contract_sha256="b" * 64,
        intent_confirmation_sha256="c" * 64,
        required_commitment_ids=["render-workspace"],
        isolation_required=False,
    )


def test_workspace_semantic_pass_binds_directory_and_controls(tmp_path: Path) -> None:
    evidence = _run(_world(tmp_path))
    assert evidence.passed is True
    assert evidence.input_kind == "directory"
    assert evidence.upstream_calls == 1
    assert evidence.input_negative_control_result == "REJECTED"
    assert evidence.artifact_negative_control_result == "REJECTED"
    assert evidence.upstream_result_counterfactual_result == "REJECTED"
    assert len(workspace_semantic_evidence_sha256(evidence)) == 64


def test_workspace_verifier_that_ignores_artifact_is_rejected(tmp_path: Path) -> None:
    verifier = '''import miniworkspace
def verify(input_path, artifact_path):
    ok = miniworkspace.render((input_path / "brief.txt").read_text()).startswith("#")
    return {"ok": ok, "reason_codes": [], "checked_commitment_ids": ["render-workspace"]}
'''
    evidence = _run(_world(tmp_path, verifier=verifier))
    assert evidence.passed is False
    assert evidence.reason_codes == ("ARTIFACT_BINDING_CONTROL_FAILED",)


def test_workspace_verifier_that_ignores_input_is_rejected(tmp_path: Path) -> None:
    verifier = '''import miniworkspace
def verify(input_path, artifact_path):
    expected = miniworkspace.render("Experiment")
    ok = (artifact_path / "README.md").read_text() == expected
    return {"ok": ok, "reason_codes": [], "checked_commitment_ids": ["render-workspace"]}
'''
    evidence = _run(_world(tmp_path, verifier=verifier))
    assert evidence.passed is False
    assert evidence.reason_codes == ("INPUT_BINDING_CONTROL_FAILED",)


def test_workspace_semantic_detects_domain_mismatch(tmp_path: Path) -> None:
    world = _world(tmp_path)
    (world["artifact"] / "README.md").write_text("wrong", encoding="utf-8")
    evidence = _run(world)
    assert evidence.passed is False
    assert evidence.reason_codes == ("VALUE_MISMATCH",)
