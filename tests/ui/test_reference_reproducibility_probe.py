"""候选生成必须证明 reference 可复现(incident-reference-reproducibility-unprobed-*)。

不变量:同一候选输入、间隔 ≥2 秒的第二次 reference 执行,其目录树身份必须
与第一次相同;不同即 WORKSPACE_REFERENCE_NOT_REPRODUCIBLE,诊断按路径给出
分歧类型(BYTES_DIFFER / ZIP_METADATA_ONLY …),路由到 reference 修复。
自检通过后再在冻结 preflight 才发现黄金树漂移,是这两起事故的共同根因。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from contextlib import contextmanager
from pathlib import Path

from repoproof.adoption.intake import example_proposer, workspace_fixtures
from repoproof.adoption.intake.workspace_fixtures import InputFixtureCandidateV1
from repoproof.execution.workspace_bundle import build_artifact_manifest, identify_input_path
from repoproof.ui.services import product_jobs

_spec = importlib.util.spec_from_file_location(
    "_workspace_ui_fixtures", Path(__file__).with_name("test_workspace_ui_services.py")
)
_fixtures = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fixtures)


def _prepare(tmp_path: Path, monkeypatch, *, drift: bool):
    draft = _fixtures._managed_draft(tmp_path, monkeypatch)
    (draft / "fixture_builder.py").write_text(
        "def build(blueprint, output_path):\n    raise AssertionError\n", encoding="utf-8"
    )
    (draft / "fixture_blueprints.json").write_text(
        json.dumps(
            {
                "blueprints": [
                    {
                        "blueprint_id": "ordinary-study",
                        "title": "Ordinary study",
                        "scenario": "s",
                        "input_kind": "directory",
                        "parameters": {"variant": "ordinary"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        product_jobs, "_core_draft_readiness", lambda *_a, **_k: _fixtures._Readiness(compatible=True, current=True)
    )
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    monkeypatch.setattr(product_jobs, "_draft_upstream_dir", lambda _draft: (upstream, None))
    monkeypatch.setattr(product_jobs, "resolved_dependency_lock", lambda *_a, **_k: "anonymous-package==1.0")

    @contextmanager
    def prepared_environment(*_args, **_kwargs):
        yield sys.executable

    monkeypatch.setattr(example_proposer, "prepared_reference_environment", prepared_environment)
    monkeypatch.setattr(product_jobs.time, "sleep", lambda _s: None)
    fixture = tmp_path / "study-input"
    fixture.mkdir()
    (fixture / "brief.txt").write_text("study\n", encoding="utf-8")
    identity = identify_input_path(fixture)
    monkeypatch.setattr(
        workspace_fixtures,
        "build_fixture_candidate",
        lambda *, blueprint, **_k: InputFixtureCandidateV1(
            blueprint=blueprint,
            builder_id="anonymous-builder-v1",
            builder_source_sha256="a" * 64,
            fixture_path=str(fixture),
            fixture_identity=identity,
        ),
    )
    runs: list[Path] = []

    def fake_reference(*, expected_dir, **_kwargs):
        expected_dir.mkdir(parents=True)
        body = f"# Result {len(runs)}\n" if drift else "# Result\n"
        (expected_dir / "README.md").write_text(body, encoding="utf-8")
        runs.append(expected_dir)
        manifest = build_artifact_manifest(expected_dir)
        return {
            "tree_sha256": manifest.tree_sha256,
            "file_count": manifest.file_count,
            "total_bytes": manifest.total_bytes,
        }

    monkeypatch.setattr(product_jobs, "_run_workspace_reference_candidate", fake_reference)
    monkeypatch.setattr(
        "repoproof.verification.workspace_semantic.run_workspace_semantic_verifier",
        lambda **_k: type("S", (), {"passed": True, "reason_codes": [], "evidence": None})(),
    )
    return draft, runs


def test_drifting_reference_is_rejected_with_path_level_divergence(tmp_path: Path, monkeypatch) -> None:
    draft, runs = _prepare(tmp_path, monkeypatch, drift=True)
    result = product_jobs.propose_workspace_fixture_candidates(draft, n=1, offline=True)
    assert result["ok"] is False
    assert result["reason_codes"] == ["WORKSPACE_REFERENCE_NOT_REPRODUCIBLE"]
    assert result["failure_owner"] == "CONTRACT"
    assert any(item.startswith("README.md=BYTES_DIFFER") for item in result["diagnostics"])  # @locus may follow
    assert len(runs) == 2
    assert not (draft / "workspace_fixture_candidates.json").exists()


def test_reproducible_reference_runs_twice_and_is_not_rejected_for_drift(tmp_path: Path, monkeypatch) -> None:
    draft, runs = _prepare(tmp_path, monkeypatch, drift=False)
    result = product_jobs.propose_workspace_fixture_candidates(draft, n=1, offline=True)
    assert result.get("reason_codes") != ["WORKSPACE_REFERENCE_NOT_REPRODUCIBLE"]
    assert len(runs) == 2
