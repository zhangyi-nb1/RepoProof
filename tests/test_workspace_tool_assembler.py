from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from repoproof.adoption.assembly import workspace_tool_assembler
from repoproof.adoption.assembly.example_compiler import CompileError
from repoproof.adoption.assembly.workspace_tool_assembler import (
    WorkspaceGoldenExampleV1,
    assemble_workspace_tool_task,
    workspace_truth_binding_sha256,
)
from repoproof.adoption.intake.intent_contract import (
    confirm_intent_contract,
    install_artifact_protocol,
    install_delivery_intent_from_interface,
    install_semantic_commitments,
    new_intent_contract,
)
from repoproof.adoption.intake.tool_confirm import confirm_tool_draft
from repoproof.domain.models import TaskContract, ToolSpec
from repoproof.execution.workspace_bundle import (
    build_artifact_manifest,
    identify_input_path,
)
from repoproof.harness.requirement_spec import load_requirement_spec
from repoproof.runner.host_guided import HostContract, build_host_prompt
from repoproof.runner.tool_export import install_verified_tool
from repoproof.runner.tool_host_bridge import (
    ensure_materialized_tool_controls_current,
    materialize_tool_task,
    synthesize_host_contract,
)
from repoproof.runner.tool_registry import (
    list_tools,
    release_audit_trust_identity_from_contract,
)
from repoproof.runner.tool_release import audit_tool
from repoproof.ui.services.product_mode import validate_draft_output_examples
from repoproof.verification.workspace_semantic import (
    SemanticVerifierEvidenceV2,
    workspace_semantic_evidence_sha256,
    write_workspace_semantic_evidence,
)


def test_golden_identity_ignores_oracle_read_only_hardening(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Freezing expected fixtures read-only must not change product truth."""

    ordinary = tmp_path / "ordinary"
    hardened = tmp_path / "hardened"
    ordinary.mkdir()
    hardened.mkdir()
    (ordinary / "report.txt").write_text("same payload\n", encoding="utf-8")
    (hardened / "report.txt").write_text("same payload\n", encoding="utf-8")
    (ordinary / "report.txt").chmod(0o644)
    (hardened / "report.txt").chmod(0o444)
    monkeypatch.setenv("REPOPROOF_TOOL_BIN", "/bin/true")
    namespace: dict[str, object] = {"__file__": str(tmp_path / "test_contract.py")}
    prelude = workspace_tool_assembler._TEST_PRELUDE.split("def _run_case", 1)[0]
    exec(prelude, namespace)

    assert namespace["_tree_sha"](ordinary) != namespace["_tree_sha"](hardened)
    assert namespace["_golden_sha"](ordinary) == namespace["_golden_sha"](hardened)


def test_held_workspace_acceptance_uses_frozen_semantics_not_incidental_bytes(
    tmp_path: Path,
) -> None:
    """Held-out inputs may hide values, not an undeclared punctuation rule."""

    oracle = tmp_path / "oracle"
    source = oracle / "fixtures" / "equivalent" / "input"
    expected = oracle / "fixtures" / "equivalent" / "expected"
    source.mkdir(parents=True)
    expected.mkdir(parents=True)
    (source / "items.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    (expected / "report.txt").write_text("alpha、beta\n", encoding="utf-8")
    (oracle / "semantic_verifier.py").write_text(
        "from pathlib import Path\n\n"
        "def verify(input_path: Path, artifact_path: Path) -> dict:\n"
        "    expected = set((input_path / 'items.txt').read_text().split())\n"
        "    actual = (artifact_path / 'report.txt').read_text().strip()\n"
        "    found = set(actual.replace('、', ';').split(';'))\n"
        "    ok = found == expected\n"
        "    return {'ok': ok, 'reason_codes': [] if ok else ['ITEMS_MISMATCH'], "
        "'checked_commitment_ids': ['render-items']}\n",
        encoding="utf-8",
    )
    tool = tmp_path / "anonymous-tool"
    tool.write_text(
        f"#!{sys.executable}\n"
        "import argparse\n"
        "from pathlib import Path\n"
        "parser = argparse.ArgumentParser()\n"
        "parser.add_argument('input')\n"
        "parser.add_argument('--out-dir', required=True)\n"
        "args = parser.parse_args()\n"
        "output = Path(args.out_dir)\n"
        "output.mkdir()\n"
        "(output / 'report.txt').write_text('alpha;beta\\n')\n",
        encoding="utf-8",
    )
    tool.chmod(0o755)
    example = WorkspaceGoldenExampleV1(
        example_id="equivalent",
        input_path="equivalent/input",
        expected_dir="equivalent/expected",
        truth_provenance="UPSTREAM_DERIVED_USER_CONFIRMED",
        truth_binding_sha256="0" * 64,
    )
    test_source = oracle / "test_capability.py"
    test_source.write_text(
        workspace_tool_assembler._test_source([example], held=True),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(test_source)],
        env={**os.environ, "REPOPROOF_TOOL_BIN": str(tool)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr

    tool.write_text(
        tool.read_text(encoding="utf-8").replace("alpha;beta", "alpha;gamma"),
        encoding="utf-8",
    )
    rejected = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(test_source)],
        env={**os.environ, "REPOPROOF_TOOL_BIN": str(tool)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert rejected.returncode != 0
    assert "ITEMS_MISMATCH" in rejected.stdout


def _tool() -> ToolSpec:
    return ToolSpec.model_validate(
        {
            "schema_version": 4,
            "name": "study-workspace-tool",
            "summary": "Build an offline study workspace",
            "delivery_profile_id": "workspace_bundle_v1",
            "workspace_contract": {
                "schema_version": 1,
                "rules": [
                    {
                        "path_pattern": "README.md",
                        "role": "human documentation",
                        "media_type": "text/markdown",
                        "validation_profile": "text_utf8_v1",
                    },
                    {
                        "path_pattern": "data/*.txt",
                        "role": "derived data",
                        "media_type": "text/plain",
                        "validation_profile": "text_utf8_v1",
                        "min_count": 1,
                        "max_count": 3,
                    },
                ],
                "allow_extra_files": False,
                "entrypoints": [],
                "runnable": False,
                "require_offline_wheelhouse": False,
            },
            "interface": {
                "usage": "study-workspace-tool <input> --out-dir <new-directory>",
                "input": {"kind": "directory", "format": "study brief directory"},
                "output": {"kind": "directory", "format": "offline workspace"},
                "exit_codes": {
                    "0": "success",
                    "1": "user error",
                    "2": "internal error",
                },
            },
        }
    )


def _world(tmp_path: Path) -> tuple[Path, list[dict]]:
    examples_root = tmp_path / "example-source"
    examples: list[dict] = []
    for index, text in enumerate(("alpha", "beta", "gamma"), start=1):
        input_dir = examples_root / f"case-{index}" / "input"
        output_dir = examples_root / f"case-{index}" / "expected"
        (input_dir).mkdir(parents=True)
        (output_dir / "data").mkdir(parents=True)
        (input_dir / "brief.txt").write_text(text, encoding="utf-8")
        (output_dir / "README.md").write_text(f"# {text}\n", encoding="utf-8")
        (output_dir / "data" / "value.txt").write_text(text.upper(), encoding="utf-8")
        binding = workspace_truth_binding_sha256(
            identify_input_path(input_dir).sha256,
            build_artifact_manifest(output_dir).tree_sha256,
        )
        examples.append(
            {
                "example_id": f"case-{index}",
                "input_path": f"case-{index}/input",
                "expected_dir": f"case-{index}/expected",
                "truth_provenance": "UPSTREAM_DERIVED_USER_CONFIRMED",
                "truth_binding_sha256": binding,
            }
        )
    return examples_root, examples


def _intent(
    tool: ToolSpec,
    *,
    output_schema: str = "workspace_bundle",
) -> tuple[str, dict]:
    user_goal = "把学习材料整理成一个能离线交接的工作目录"
    draft = {
        "_intent_contract": new_intent_contract(user_goal),
        "tool": tool.model_dump(mode="json"),
        "capability": {"statement": "", "output_schema": output_schema},
    }
    install_delivery_intent_from_interface(draft, profile_id="workspace_bundle_v1")
    install_semantic_commitments(
        draft,
        [
            {
                "commitment_id": "compose-study-workspace",
                "public_text": "把输入材料组织成含说明和派生数据的离线工作目录。",
                "rationale": "这是用户确认的交付结果。",
            }
        ],
    )
    install_artifact_protocol(
        draft,
        {
            "schema_version": 1,
            "protocol_id": "study-workspace-v1",
            "observations": [
                {
                    "observation_id": "workspace-content",
                    "commitment_ids": ["compose-study-workspace"],
                    "locator": "README and data files",
                    "value_encoding": "validated directory tree",
                }
            ],
        },
    )
    confirm_intent_contract(draft, confirmed_at="2026-08-31T00:00:00Z")
    return draft["capability"]["statement"], draft["_intent_contract"]


_REFERENCE = """from pathlib import Path
import synthetic_upstream

class UserInputError(ValueError):
    pass

def build_workspace(input_path: Path, output_dir: Path) -> None:
    text = (input_path / "brief.txt").read_text()
    value = synthetic_upstream.transform(text)
    (output_dir / "data").mkdir()
    (output_dir / "README.md").write_text(f"# {text}\\n")
    (output_dir / "data" / "value.txt").write_text(value)
"""

_VERIFIER = """from pathlib import Path
import synthetic_upstream

def verify(input_path: Path, artifact_path: Path) -> dict:
    text = (input_path / "brief.txt").read_text()
    expected = synthetic_upstream.transform(text)
    ok = (artifact_path / "data" / "value.txt").read_text() == expected
    return {"ok": ok, "reason_codes": [] if ok else ["VALUE_MISMATCH"],
            "checked_commitment_ids": ["compose-study-workspace"]}
"""

_FIXTURE_BUILDER = """from pathlib import Path

def build(blueprint, output_path: Path) -> None:
    output_path.mkdir()
    (output_path / "brief.txt").write_text(blueprint["parameters"]["text"])
"""

_FIXTURE_BLUEPRINTS = [
    {
        "blueprint_id": f"study-{index}",
        "title": f"Study {index}",
        "scenario": "One realistic study folder.",
        "input_kind": "directory",
        "parameters": {"text": text},
    }
    for index, text in enumerate(("alpha", "beta", "gamma"), start=1)
]


def test_workspace_assembler_freezes_v4_task_and_runs_public_controls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tool = _tool()
    source_root, examples = _world(tmp_path)
    goal, intent = _intent(tool)
    project = tmp_path / "project"
    result = assemble_workspace_tool_task(
        project,
        goal=goal,
        repo_url="https://example.invalid/synthetic",
        resolved_commit="a" * 40,
        distribution="synthetic-upstream",
        import_module="synthetic_upstream",
        license_id="MIT",
        tool=tool,
        examples=examples,
        example_src_dir=source_root,
        reference_impl=_REFERENCE,
        semantic_verifier_source=_VERIFIER,
        fixture_builder_source=_FIXTURE_BUILDER,
        fixture_blueprints=_FIXTURE_BLUEPRINTS,
        reference_lock="synthetic-upstream==1.0.0\n",
        intent_contract=intent,
        output_schema="workspace_bundle",
    )
    contract_path = project / "contracts" / f"{result['task_id']}.yaml"
    contract, _ = TaskContract.load_frozen(contract_path, require_sidecar=True)
    assert contract.tool is not None
    assert contract.tool.schema_version == 4
    assert contract.tool.delivery_profile_id == "workspace_bundle_v1"
    requirement_spec, _ = load_requirement_spec(project / "contracts" / f"{result['task_id']}.requirements.yaml")
    assert requirement_spec.by_id()["workspace-structure"].verified_by == ("workspace-structure-validator-v1")
    assert result["public"] == 2 and result["held"] == 1

    host_document = synthesize_host_contract(
        contract,
        [{"id": "workspace-examples", "text": "Generate the frozen workspace."}],
        host_copy=tmp_path / "host",
        wheelhouse=tmp_path / "wheels",
        skeleton_commit="b" * 64,
        hook_min_calls=3,
    )
    host_contract = HostContract.model_validate(host_document)
    assert host_contract.prompt_profile == "workspace-tool-v1"
    prompt = build_host_prompt(host_contract, wheel_note="package wheelhouse")
    assert "build_workspace(input_path, output_dir)" in prompt
    assert "impl.extract" not in prompt
    assert "directory manifests" in prompt
    assert "hidden tests only" in prompt

    materialized_contract = materialize_tool_task(
        project,
        contract_path,
        out_root=project / "tool_tasks",
        host_copy_root=tmp_path / "bench",
        setup_commands=[[sys.executable, "-c", "print('ready')"]],
    )
    materialized_positive = (
        materialized_contract.parent / "controls" / "positive" / "impl.py"
    )
    assert "_repoproof_reference_build_workspace_v1" in (
        materialized_positive.read_text(encoding="utf-8")
    )
    materialized_positive.write_text("stale derived control\n", encoding="utf-8")
    assert ensure_materialized_tool_controls_current(
        project, contract_path, materialized_contract
    ) is True
    assert "_repoproof_reference_build_workspace_v1" in (
        materialized_positive.read_text(encoding="utf-8")
    )
    assert ensure_materialized_tool_controls_current(
        project, contract_path, materialized_contract
    ) is False

    skeleton = project / contract.target_project.path
    shutil.copy2(
        project / "controls" / result["task_id"] / "positive" / "impl.py",
        skeleton / "src" / contract.target_project.package / "impl.py",
    )
    shim = tmp_path / "tool-shim"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"sys.path.insert(0, {str(skeleton / 'src')!r})\n"
        f"from {contract.target_project.package}.main import cli\n"
        "raise SystemExit(cli())\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    env = {**os.environ, "REPOPROOF_TOOL_BIN": str(shim)}
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "public_tests", "-q"],
        cwd=skeleton,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stdout + run.stderr

    (skeleton / "src" / contract.target_project.package / "impl.py").write_text(
        "from pathlib import Path\n\n"
        "class UserInputError(ValueError):\n    pass\n\n"
        "def build_workspace(input_path: Path, output_dir: Path) -> None:\n"
        "    value = (input_path / 'brief.txt').read_text()\n"
        "    (output_dir / 'data').mkdir()\n"
        "    (output_dir / 'README.md').write_text(f'# {value}\\n')\n"
        "    (output_dir / 'data/value.txt').write_text(value.upper())\n",
        encoding="utf-8",
    )

    export_host = tmp_path / "export-host"
    shutil.copytree(skeleton, export_host)
    host_contract_path = tmp_path / "export-host.yaml"
    host_contract_path.write_text(
        yaml.safe_dump({"host": {"copy_path": str(export_host)}}),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "report.json").write_text(
        json.dumps(
            {
                "task_id": result["task_id"],
                "run_id": "workspace-run-v1",
                "verdict": "PASS_ADAPTED",
                "verdict_public": "VERIFIED_TOOL_READY",
            }
        ),
        encoding="utf-8",
    )
    tools_root = tmp_path / "tools"
    installed = install_verified_tool(
        run_dir,
        host_contract_path=host_contract_path,
        tool_contract_path=contract_path,
        dest_root=tools_root,
        exported_at="2026-08-31T00:00:00Z",
    )
    installed_manifest = json.loads((installed / "tool.json").read_text(encoding="utf-8"))
    assert installed_manifest["contract_schema_version"] == 4
    row = list_tools(tools_root, scan=False)[0]
    assert row["status"] == "OK"
    assert row["operational_status"] == "REVIEW_REQUIRED"

    runtime_python = installed / ".venv/bin/python"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text(
        f'#!/bin/sh\nexport PYTHONPATH={str(installed / "src")!s}:$PYTHONPATH\nexec {sys.executable} "$@"\n',
        encoding="utf-8",
    )
    runtime_python.chmod(0o755)
    trust = release_audit_trust_identity_from_contract(contract)
    assert trust is not None
    semantic_calls = 0

    def semantic_stub(**kwargs):
        nonlocal semantic_calls
        semantic_calls += 1
        artifact = Path(kwargs["artifact"])
        input_path = Path(kwargs["input_path"])
        artifact_manifest = build_artifact_manifest(artifact)
        manifest_sha = hashlib.sha256(
            json.dumps(
                artifact_manifest.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        evidence = SemanticVerifierEvidenceV2(
            verifier_id=trust.semantic_verifier.verifier_id,
            verifier_source_sha256=trust.semantic_verifier.source_sha256,
            input_kind="directory",
            input_sha256=identify_input_path(input_path).sha256,
            artifact_tree_sha256=artifact_manifest.tree_sha256,
            artifact_manifest_sha256=manifest_sha,
            workspace_contract_sha256=trust.output_contract_sha256,
            intent_confirmation_sha256=trust.intent_confirmation_sha256,
            upstream_commit=trust.upstream_commit,
            import_module=trust.import_module,
            upstream_imports=1,
            upstream_calls=1,
            input_negative_control_sha256="1" * 64,
            input_negative_control_result="REJECTED",
            artifact_negative_control_tree_sha256="2" * 64,
            artifact_negative_control_result="REJECTED",
            upstream_result_counterfactual_result="REJECTED",
            upstream_result_counterfactual_upstream_imports=1,
            upstream_result_counterfactual_upstream_calls=1,
            required_commitment_ids=trust.required_commitment_ids,
            checked_commitment_ids=trust.required_commitment_ids,
            passed=True,
        )
        semantic_path = (
            installed
            / "evidence/semantic-audits"
            / f"fresh-{semantic_calls}-{artifact_manifest.tree_sha256[:16]}.json"
        )
        write_workspace_semantic_evidence(semantic_path, evidence)
        return {
            "verifier_id": evidence.verifier_id,
            "artifact_tree_sha256": evidence.artifact_tree_sha256,
            "artifact_manifest_sha256": evidence.artifact_manifest_sha256,
            "evidence_sha256": workspace_semantic_evidence_sha256(evidence),
            "evidence_path": str(semantic_path),
            "passed": True,
            "reason_codes": [],
            "required_commitment_ids": list(evidence.required_commitment_ids),
            "checked_commitment_ids": list(evidence.checked_commitment_ids),
        }

    monkeypatch.setattr(
        "repoproof.runner.tool_release._run_required_semantic_audit",
        semantic_stub,
    )
    fresh_input = tmp_path / "fresh-input"
    fresh_expected = tmp_path / "fresh-expected"
    fresh_input.mkdir()
    (fresh_input / "brief.txt").write_text("delta", encoding="utf-8")
    (fresh_expected / "data").mkdir(parents=True)
    (fresh_expected / "README.md").write_text("# delta\n", encoding="utf-8")
    (fresh_expected / "data/value.txt").write_text("DELTA", encoding="utf-8")
    audited = audit_tool(
        tools_root,
        tool.name,
        input_path=fresh_input,
        expected_file=fresh_expected,
        expected_task_id=result["task_id"],
        project_root=project,
        run_build=False,
    )
    assert audited["operational_status"] == "ACTIVE"
    active_row = list_tools(tools_root, scan=False)[0]
    assert active_row["operational_status"] == "ACTIVE"


def test_workspace_assembler_rejects_drifted_truth_binding(tmp_path: Path) -> None:
    tool = _tool()
    source_root, examples = _world(tmp_path)
    goal, intent = _intent(tool)
    examples[0]["truth_binding_sha256"] = hashlib.sha256(b"tampered").hexdigest()
    try:
        assemble_workspace_tool_task(
            tmp_path / "project",
            goal=goal,
            repo_url="https://example.invalid/synthetic",
            resolved_commit="a" * 40,
            distribution="synthetic-upstream",
            import_module="synthetic_upstream",
            license_id="MIT",
            tool=tool,
            examples=examples,
            example_src_dir=source_root,
            reference_impl=_REFERENCE,
            semantic_verifier_source=_VERIFIER,
            fixture_builder_source=_FIXTURE_BUILDER,
            fixture_blueprints=_FIXTURE_BLUEPRINTS,
            reference_lock="synthetic-upstream==1.0.0\n",
            intent_contract=intent,
            output_schema="workspace_bundle",
        )
    except CompileError as exc:
        assert "binding drift" in str(exc)
    else:
        raise AssertionError("drifted workspace truth binding was accepted")


def test_workspace_assembler_preserves_confirmed_task_output_schema(
    tmp_path: Path,
) -> None:
    tool = _tool()
    source_root, examples = _world(tmp_path)
    output_schema = "ReadableStudyWorkspace"
    goal, intent = _intent(tool, output_schema=output_schema)

    result = assemble_workspace_tool_task(
        tmp_path / "project",
        goal=goal,
        repo_url="https://example.invalid/synthetic",
        resolved_commit="a" * 40,
        distribution="synthetic-upstream",
        import_module="synthetic_upstream",
        license_id="MIT",
        tool=tool,
        examples=examples,
        example_src_dir=source_root,
        reference_impl=_REFERENCE,
        semantic_verifier_source=_VERIFIER,
        fixture_builder_source=_FIXTURE_BUILDER,
        fixture_blueprints=_FIXTURE_BLUEPRINTS,
        reference_lock="synthetic-upstream==1.0.0\n",
        intent_contract=intent,
        output_schema=output_schema,
    )

    contract_path = (
        tmp_path / "project" / "contracts" / f"{result['task_id']}.yaml"
    )
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    assert contract["capability"]["output_schema"] == output_schema
    manifest_path = (
        tmp_path
        / "project"
        / contract["target_project"]["path"]
        / "tool.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["capability"]["output_schema"] == output_schema


def test_confirm_dispatches_current_workspace_draft_to_v4_assembler(
    tmp_path: Path,
) -> None:
    tool = _tool()
    source_root, examples = _world(tmp_path)
    goal, intent = _intent(tool)
    draft_dir = tmp_path / "draft"
    shutil.copytree(source_root, draft_dir / "examples")
    draft = {
        "_delivery_profile": {
            "schema_version": 1,
            "profile_id": "workspace_bundle_v1",
        },
        "_intent_contract": intent,
        "source_repo": {
            "url": "https://example.invalid/synthetic",
            "revision": "1.0.0",
            "resolved_commit": "a" * 40,
            "license": "MIT",
            "distribution": "synthetic-upstream",
            "import_module": "synthetic_upstream",
        },
        "tool": tool.model_dump(mode="json"),
        "capability": {"statement": goal, "output_schema": "workspace_bundle"},
    }
    (draft_dir / "draft.yaml").write_text(
        yaml.safe_dump(draft, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (draft_dir / "workspace_examples.yaml").write_text(
        yaml.safe_dump({"examples": examples}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (draft_dir / "reference_impl.py").write_text(_REFERENCE, encoding="utf-8")
    (draft_dir / "semantic_verifier.py").write_text(_VERIFIER, encoding="utf-8")
    (draft_dir / "fixture_builder.py").write_text(
        _FIXTURE_BUILDER,
        encoding="utf-8",
    )
    (draft_dir / "fixture_blueprints.json").write_text(
        json.dumps(
            {"schema_version": 1, "blueprints": _FIXTURE_BLUEPRINTS}
        ),
        encoding="utf-8",
    )
    (draft_dir / "reference.lock.txt").write_text("synthetic-upstream==1.0.0\n", encoding="utf-8")

    validation = validate_draft_output_examples(draft_dir)
    assert validation["ok"] is True
    assert validation["artifact_kind"] == "directory"

    result = confirm_tool_draft(draft_dir, tmp_path / "project")

    assert result["delivery_profile_id"] == "workspace_bundle_v1"
    assert result["public"] == 2
    assert result["held"] == 1
