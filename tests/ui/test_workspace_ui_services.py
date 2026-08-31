from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import yaml

from repoproof.adoption.intake import example_proposer, workspace_fixtures
from repoproof.adoption.intake.workspace_fixtures import InputFixtureCandidateV1
from repoproof.execution.workspace_bundle import (
    build_artifact_manifest,
    identify_input_path,
)
from repoproof.ui.services import product_jobs


def _tool() -> dict:
    return {
        "schema_version": 4,
        "name": "study-workspace",
        "summary": "Build an offline workspace",
        "delivery_profile_id": "workspace_bundle_v1",
        "workspace_contract": {
            "schema_version": 1,
            "rules": [
                {
                    "path_pattern": "README.md",
                    "role": "documentation",
                    "media_type": "text/markdown",
                    "validation_profile": "text_utf8_v1",
                }
            ],
            "allow_extra_files": False,
            "entrypoints": [],
            "runnable": False,
            "smoke_command": [],
            "smoke_timeout_seconds": 30,
            "require_offline_wheelhouse": False,
        },
        "interface": {
            "usage": "study-workspace <input> --out-dir <new-directory>",
            "input": {"kind": "directory", "format": "research files"},
            "output": {"kind": "directory", "format": "offline workspace"},
            "exit_codes": {
                "0": "success",
                "1": "invalid input",
                "2": "internal failure",
            },
        },
    }


def _managed_draft(tmp_path: Path, monkeypatch) -> Path:
    state = tmp_path / "state"
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    draft = state / "drafts" / "workspace"
    (draft / "examples").mkdir(parents=True)
    (draft / "draft.yaml").write_text(
        yaml.safe_dump(
            {
                "task_id": "tool-study-workspace-v1",
                "tool": _tool(),
                "capability": {
                    "statement": "Create an offline study workspace.",
                    "output_schema": "workspace_bundle",
                },
                "source_repo": {},
                "target_project": {
                    "path": "fixtures/tool_skeleton_study-workspace",
                    "package": "study_workspace",
                    "entry_point": "study-workspace",
                },
                "_delivery_profile": {
                    "schema_version": 1,
                    "profile_id": "workspace_bundle_v1",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (draft / "reference_impl.py").write_text(
        "def build_workspace(input_path, output_dir):\n    pass\n",
        encoding="utf-8",
    )
    (draft / "semantic_verifier.py").write_text(
        "def verify(input_path, artifact_dir):\n    return {'ok': False}\n",
        encoding="utf-8",
    )
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft / "workspace_examples.yaml").write_text(
        "examples: []\n", encoding="utf-8"
    )
    return draft


class _Readiness(SimpleNamespace):
    ready_to_confirm = False
    reason_codes = ["EXAMPLES_INSUFFICIENT"]
    recommended_action = "Confirm three examples."

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return {
            "status": "NEEDS_EXAMPLES",
            "compatible": self.compatible,
            "current": self.current,
            "ready": False,
            "ready_to_confirm": False,
            "reason_codes": ["EXAMPLES_INSUFFICIENT"],
            "recommended_action": "Confirm three examples.",
            "public_summary": {"example_count": 0},
        }


def test_workspace_review_reads_workspace_examples_not_stdout_manifest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    draft = _managed_draft(tmp_path, monkeypatch)
    (draft / "examples.yaml").write_text(
        "examples:\n  - input: must-not-leak\n", encoding="utf-8"
    )
    (draft / "workspace_examples.yaml").write_text(
        "examples:\n  - example_id: workspace-one\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        product_jobs,
        "_core_draft_readiness",
        lambda *_a, **_k: _Readiness(compatible=True, current=True),
    )

    review = product_jobs.read_managed_draft_review(draft)

    assert review["ok"] is True
    assert review["delivery_profile_id"] == "workspace_bundle_v1"
    assert review["examples"] == [{"example_id": "workspace-one"}]
    assert review["workspace_contract"]["rules"][0]["path_pattern"] == "README.md"


def test_workspace_candidate_generation_rejects_duplicate_input_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    draft = _managed_draft(tmp_path, monkeypatch)
    (draft / "fixture_builder.py").write_text(
        "def build(blueprint, output_path):\n    raise AssertionError\n",
        encoding="utf-8",
    )
    (draft / "fixture_blueprints.json").write_text(
        json.dumps(
            {
                "blueprints": [
                    {
                        "blueprint_id": "ordinary-study",
                        "title": "Ordinary study",
                        "scenario": "An ordinary local study input.",
                        "input_kind": "directory",
                        "parameters": {"variant": "ordinary"},
                    },
                    {
                        "blueprint_id": "edge-study",
                        "title": "Edge study",
                        "scenario": "A distinct edge-case study input.",
                        "input_kind": "directory",
                        "parameters": {"variant": "edge"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        product_jobs,
        "_core_draft_readiness",
        lambda *_a, **_k: _Readiness(compatible=True, current=True),
    )
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    monkeypatch.setattr(
        product_jobs,
        "_draft_upstream_dir",
        lambda _draft: (upstream, None),
    )
    monkeypatch.setattr(
        product_jobs,
        "resolved_dependency_lock",
        lambda *_a, **_k: "anonymous-package==1.0",
    )

    @contextmanager
    def prepared_environment(*_args, **_kwargs):
        yield sys.executable

    monkeypatch.setattr(
        example_proposer,
        "prepared_reference_environment",
        prepared_environment,
    )
    fixture = tmp_path / "identical-input"
    fixture.mkdir()
    (fixture / "brief.txt").write_text("same exact bytes", encoding="utf-8")
    identity = identify_input_path(fixture)

    def duplicate_candidate(*, blueprint, **_kwargs):
        return InputFixtureCandidateV1(
            blueprint=blueprint,
            builder_id="anonymous-builder-v1",
            builder_source_sha256="a" * 64,
            fixture_path=str(fixture),
            fixture_identity=identity,
        )

    monkeypatch.setattr(
        workspace_fixtures,
        "build_fixture_candidate",
        duplicate_candidate,
    )

    def fake_reference(*, expected_dir, **_kwargs):
        expected_dir.mkdir(parents=True)
        (expected_dir / "README.md").write_text("# Result\n", encoding="utf-8")
        manifest = build_artifact_manifest(expected_dir)
        return {
            "tree_sha256": manifest.tree_sha256,
            "file_count": manifest.file_count,
            "total_bytes": manifest.total_bytes,
        }

    monkeypatch.setattr(
        product_jobs,
        "_run_workspace_reference_candidate",
        fake_reference,
    )

    result = product_jobs.propose_workspace_fixture_candidates(
        draft,
        n=2,
        offline=True,
    )

    assert result["ok"] is False
    assert result["failure_owner"] == "CONTRACT"
    assert result["reason_codes"] == ["FIXTURE_INPUT_DUPLICATE"]
    assert not (draft / "workspace_fixture_candidates.json").exists()


def test_workspace_candidate_preview_zip_and_confirmation_are_tree_bound(
    tmp_path: Path,
    monkeypatch,
) -> None:
    draft = _managed_draft(tmp_path, monkeypatch)
    monkeypatch.setattr(
        product_jobs,
        "_core_draft_readiness",
        lambda *_a, **_k: _Readiness(compatible=True, current=True),
    )
    monkeypatch.setattr(
        product_jobs,
        "invalidate_intent_confirmation",
        lambda _draft: None,
    )
    generation_id = "generation-12345678-deadbeef"
    root = draft / "workspace-candidates" / generation_id
    input_dir = root / "inputs" / "typical-study"
    expected_dir = root / "expected" / "typical-study"
    input_dir.mkdir(parents=True)
    expected_dir.mkdir(parents=True)
    (input_dir / "brief.txt").write_text("Study alpha", encoding="utf-8")
    (expected_dir / "README.md").write_text("# Study alpha\n", encoding="utf-8")
    input_identity = identify_input_path(input_dir)
    expected_manifest = build_artifact_manifest(expected_dir)
    record: dict[str, object] = {
        "blueprint_id": "typical-study",
        "title": "Typical study",
        "scenario": "One ordinary study folder",
        "input_kind": "directory",
        "builder_source_sha256": "a" * 64,
        "input_path": str(input_dir.resolve()),
        "input_sha256": input_identity.sha256,
        "input_file_count": input_identity.file_count,
        "input_total_bytes": input_identity.total_bytes,
        "expected_dir": str(expected_dir.resolve()),
        "expected_tree_sha256": expected_manifest.tree_sha256,
        "expected_file_count": expected_manifest.file_count,
        "expected_total_bytes": expected_manifest.total_bytes,
        "confirmed": False,
        "generation_id": generation_id,
    }
    token = product_jobs._workspace_candidate_token(record)
    record["candidate_token"] = token
    (draft / "workspace_fixture_candidates.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation_id": generation_id,
                "records": [record],
            }
        ),
        encoding="utf-8",
    )

    preview = product_jobs.workspace_candidate_preview(
        draft,
        candidate_token=token,
    )
    archive = product_jobs.workspace_candidate_zip(
        draft,
        candidate_token=token,
    )
    confirmed = product_jobs.confirm_workspace_fixture_candidate(
        draft,
        candidate_token=token,
    )

    assert preview["ok"] is True
    assert preview["expected_tree"]["tree_sha256"] == expected_manifest.tree_sha256
    assert archive["ok"] is True
    assert archive["bytes"].startswith(b"PK")
    assert confirmed["ok"] is True
    manifest = yaml.safe_load(
        (draft / "workspace_examples.yaml").read_text(encoding="utf-8")
    )
    assert manifest["examples"][0]["example_id"] == "typical-study"
    assert (draft / "examples/workspace-expected/typical-study/README.md").is_file()


def test_workspace_candidate_state_cannot_escape_managed_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    draft = _managed_draft(tmp_path, monkeypatch)
    generation_id = "generation-12345678-deadbeef"
    (draft / "workspace-candidates" / generation_id).mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    record = {
        "candidate_token": "b" * 64,
        "input_path": str(outside),
        "expected_dir": str(outside),
    }
    (draft / "workspace_fixture_candidates.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation_id": generation_id,
                "records": [record],
            }
        ),
        encoding="utf-8",
    )

    result = product_jobs.workspace_candidate_preview(
        draft,
        candidate_token="b" * 64,
    )

    assert result["ok"] is False
    assert "PATH_ESCAPE" in result["error"]


def _workspace_audit_world(tmp_path: Path, monkeypatch) -> tuple[Path, str, str]:
    from repoproof.domain.models import TaskContract, ToolSpec

    state = tmp_path / "state"
    tools = tmp_path / "tools"
    package = tools / "study-workspace"
    package.mkdir(parents=True)
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    monkeypatch.setattr(
        "repoproof.ui.services.product_mode.project_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "repoproof.ui.services.product_mode.list_tools",
        lambda _root: {
            "tools": [
                {
                    "name": "study-workspace",
                    "task_id": "tool-study-workspace-v1",
                    "path": str(package),
                    "health": "OK",
                }
            ],
            "registry_error": None,
            "release_error": None,
        },
    )
    monkeypatch.setattr(
        "repoproof.harness.task_package.load_and_verify",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        TaskContract,
        "load_frozen",
        staticmethod(
            lambda *_args, **_kwargs: (
                SimpleNamespace(
                    task_id="tool-study-workspace-v1",
                    tool=ToolSpec.model_validate(_tool()),
                ),
                "contract-sha",
            )
        ),
    )
    store = product_jobs._workspace_audit_candidate_store(
        tool_name="study-workspace",
        task_id="tool-study-workspace-v1",
        dest_root=tools,
    )
    generation_id = "generation-12345678-deadbeef"
    generation = store / generation_id
    input_dir = generation / "inputs" / "fresh-study"
    expected_dir = generation / "expected" / "fresh-study"
    input_dir.mkdir(parents=True)
    expected_dir.mkdir(parents=True)
    (input_dir / "brief.txt").write_text("Fresh study", encoding="utf-8")
    (expected_dir / "README.md").write_text("# Fresh study\n", encoding="utf-8")
    input_identity = identify_input_path(input_dir)
    expected_manifest = build_artifact_manifest(expected_dir)
    record: dict[str, object] = {
        "blueprint_id": "fresh-study",
        "title": "Fresh study",
        "scenario": "A scenario not used during construction",
        "input_kind": "directory",
        "builder_source_sha256": "a" * 64,
        "input_path": str(input_dir.resolve()),
        "input_sha256": input_identity.sha256,
        "input_file_count": input_identity.file_count,
        "input_total_bytes": input_identity.total_bytes,
        "expected_dir": str(expected_dir.resolve()),
        "expected_tree_sha256": expected_manifest.tree_sha256,
        "expected_file_count": expected_manifest.file_count,
        "expected_total_bytes": expected_manifest.total_bytes,
    }
    token = product_jobs._workspace_candidate_token(record)
    record["candidate_token"] = token
    (store / "state.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tool_name": "study-workspace",
                "task_id": "tool-study-workspace-v1",
                "dest_root": str(tools),
                "generation_id": generation_id,
                "records": [record],
            }
        ),
        encoding="utf-8",
    )
    return tools, token, str(expected_dir)


def test_workspace_audit_preview_and_materialization_recheck_tree_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tools, token, expected_dir = _workspace_audit_world(tmp_path, monkeypatch)

    preview = product_jobs.workspace_audit_candidate_preview(
        "study-workspace",
        dest_root=tools,
        expected_task_id="tool-study-workspace-v1",
        candidate_token=token,
    )
    materialized = product_jobs.materialize_workspace_audit_candidate(
        "study-workspace",
        dest_root=tools,
        expected_task_id="tool-study-workspace-v1",
        candidate_token=token,
    )

    assert preview["ok"] is True
    assert preview["expected_tree"]["entries"][0]["path"] == "README.md"
    assert materialized["ok"] is True
    assert materialized["expected"] == expected_dir

    (Path(expected_dir) / "README.md").write_text("tampered\n", encoding="utf-8")
    rejected = product_jobs.materialize_workspace_audit_candidate(
        "study-workspace",
        dest_root=tools,
        expected_task_id="tool-study-workspace-v1",
        candidate_token=token,
    )
    assert rejected["ok"] is False
    assert "CONTENT_DRIFT" in rejected["error"]


def test_workspace_audit_state_path_escape_is_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tools, token, _expected_dir = _workspace_audit_world(tmp_path, monkeypatch)
    store = product_jobs._workspace_audit_candidate_store(
        tool_name="study-workspace",
        task_id="tool-study-workspace-v1",
        dest_root=tools,
    )
    state = json.loads((store / "state.json").read_text(encoding="utf-8"))
    outside = tmp_path / "outside"
    outside.mkdir()
    state["records"][0]["expected_dir"] = str(outside)
    (store / "state.json").write_text(json.dumps(state), encoding="utf-8")

    rejected = product_jobs.workspace_audit_candidate_preview(
        "study-workspace",
        dest_root=tools,
        expected_task_id="tool-study-workspace-v1",
        candidate_token=token,
    )

    assert rejected["ok"] is False
    assert "PATH_ESCAPE" in rejected["error"]


def test_installed_workspace_preview_and_zip_revalidate_current_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tools = tmp_path / "tools"
    package = tools / "study-workspace"
    package.mkdir(parents=True)
    (package / "tool.json").write_text(
        json.dumps(
            {
                "name": "study-workspace",
                "workspace_contract": _tool()["workspace_contract"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "repoproof.ui.services.product_mode.list_tools",
        lambda _root: {
            "tools": [
                {
                    "name": "study-workspace",
                    "path": str(package),
                    "health": "OK",
                    "operational_status": "ACTIVE",
                    "delivery_profile_id": "workspace_bundle_v1",
                }
            ],
            "registry_error": None,
            "release_error": None,
        },
    )
    output = tmp_path / "generated-workspace"
    output.mkdir()
    (output / "README.md").write_text("# Generated\n", encoding="utf-8")

    inspected = product_jobs.inspect_workspace_artifact(
        "study-workspace",
        artifact_dir=output,
        dest_root=tools,
    )
    archive = product_jobs.workspace_artifact_zip(
        "study-workspace",
        artifact_dir=output,
        dest_root=tools,
    )

    assert inspected["ok"] is True
    assert inspected["entries"][0]["path"] == "README.md"
    assert archive["ok"] is True
    assert archive["bytes"].startswith(b"PK")

    (output / "unexpected.txt").write_text("not contracted", encoding="utf-8")
    rejected = product_jobs.inspect_workspace_artifact(
        "study-workspace",
        artifact_dir=output,
        dest_root=tools,
    )
    assert rejected["ok"] is False
    assert "WORKSPACE_EXTRA_FILE_FORBIDDEN" in rejected["reason_codes"]
