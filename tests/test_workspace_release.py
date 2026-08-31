from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from repoproof.domain.models import SemanticVerifierSpec
from repoproof.execution.workspace_bundle import build_artifact_manifest
from repoproof.runner import tool_release
from repoproof.runner.tool_registry import ReleaseAuditTrustIdentityV1
from repoproof.verification.workspace_semantic import (
    SemanticVerifierEvidenceV2,
    workspace_semantic_evidence_sha256,
    write_workspace_semantic_evidence,
)


def _workspace_contract() -> dict:
    return {
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
        "require_offline_wheelhouse": False,
    }


@pytest.mark.parametrize(
    ("reference_semantic_pass", "expected_status", "expected_reason"),
    [
        (True, "ACTIVE", "FRESH_INPUT_SEMANTIC_PASS"),
        (False, "REVIEW_REQUIRED", "REFERENCE_SEMANTIC_MISMATCH"),
    ],
)
def test_workspace_release_requires_reference_and_delivery_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference_semantic_pass: bool,
    expected_status: str,
    expected_reason: str,
) -> None:
    dest_root = tmp_path / "tools"
    tool_dir = dest_root / "workspace-tool"
    executable = tool_dir / "bin/workspace-tool"
    executable.parent.mkdir(parents=True)
    (tool_dir / "evidence").mkdir()
    executable.write_text(
        '#!/bin/sh\nset -eu\nout=$3\nmkdir "$out"\nprintf \'# %s\\n\' "$(cat "$1")" > "$out/README.md"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    manifest = {
        "name": "workspace-tool",
        "workspace_contract": _workspace_contract(),
    }
    input_path = tmp_path / "fresh.txt"
    input_path.write_text("alpha", encoding="utf-8")
    expected = tmp_path / "expected"
    expected.mkdir()
    # The reference may choose different presentation bytes while satisfying
    # the same public semantic commitment.
    (expected / "README.md").write_text("# Reference wording: alpha\n", encoding="utf-8")
    semantic_identity = {"verifier": "frozen"}
    monkeypatch.setattr(
        tool_release,
        "_tool_context",
        lambda *_args, **_kwargs: (
            tool_dir,
            manifest,
            "tool-workspace-tool-v1",
            "run-v4",
        ),
    )
    monkeypatch.setattr(tool_release, "_package_control_identity", lambda *_: "pkg")
    monkeypatch.setattr(tool_release, "runtime_environment_sha256", lambda *_: "runtime")
    monkeypatch.setattr(
        tool_release,
        "_managed_release_identity",
        lambda **_kwargs: (4, semantic_identity, None),
    )
    semantic_artifacts: list[Path] = []

    def semantic_pass(**kwargs):
        artifact = Path(kwargs["artifact"])
        semantic_artifacts.append(artifact)
        passed = reference_semantic_pass if artifact == expected else True
        return {
            "verifier_id": "generic-workspace-v1",
            "artifact_tree_sha256": build_artifact_manifest(artifact).tree_sha256,
            "artifact_manifest_sha256": "a" * 64,
            "evidence_sha256": "b" * 64,
            "evidence_path": "unused",
            "passed": passed,
            "reason_codes": [] if passed else ["REFERENCE_RULE_MISMATCH"],
            "required_commitment_ids": ["workspace-result"],
            "checked_commitment_ids": ["workspace-result"],
        }

    monkeypatch.setattr(
        tool_release,
        "_run_required_semantic_audit",
        semantic_pass,
    )
    evidence = {
        "schema_version": 2,
        "tool": "workspace-tool",
        "task_id": "tool-workspace-tool-v1",
        "run_id": "run-v4",
        "historical_verdict": "VERIFIED_TOOL_READY",
        "input_sha256": hashlib.sha256(b"alpha").hexdigest(),
        "expected_sha256": build_artifact_manifest(expected).tree_sha256,
        "runtime_environment_sha256": "runtime",
    }

    result = tool_release._audit_workspace_execution(
        dest_root=dest_root,
        name="workspace-tool",
        tool_dir=tool_dir,
        manifest=manifest,
        task_id="tool-workspace-tool-v1",
        run_id="run-v4",
        input_path=input_path,
        expected_dir=expected,
        executable=executable,
        timeout=30,
        evidence=evidence,
        project_root=tmp_path,
        package_identity="pkg",
        runtime_environment_identity="runtime",
        required_schema_version=4,
        required_semantic_identity=semantic_identity,
        required_release_identity=None,
    )

    assert result["operational_status"] == expected_status
    assert result["reason_code"] == expected_reason
    assert evidence["reference_tree_match"] is False
    assert semantic_artifacts[0] == expected
    if reference_semantic_pass:
        assert len(semantic_artifacts) == 2
        assert semantic_artifacts[1].name == "artifact"
        assert result["semantic_verifier_artifact_tree_sha256"] == evidence["execution"]["artifact_tree_sha256"]
    else:
        assert len(semantic_artifacts) == 1
        assert "semantic_verifier_artifact_tree_sha256" not in result


def test_v2_workspace_semantic_record_is_revalidated_from_ledger_evidence(
    tmp_path: Path,
) -> None:
    tool_dir = tmp_path / "workspace-tool"
    semantic_dir = tool_dir / "evidence/semantic-audits"
    release_dir = tool_dir / "evidence/release-audits"
    semantic_dir.mkdir(parents=True)
    release_dir.mkdir()
    verifier = SemanticVerifierSpec(
        protocol="repoproof-workspace-semantic-verifier-v2",
        verifier_id="generic-workspace-v1",
        source_file="oracle/semantic.py",
        source_sha256="1" * 64,
        required_for_operational_active=True,
    )
    trust = ReleaseAuditTrustIdentityV1(
        semantic_verifier=verifier,
        output_contract_sha256="2" * 64,
        intent_confirmation_sha256="3" * 64,
        upstream_commit="4" * 40,
        import_module="fixture_upstream",
        required_commitment_ids=("workspace-result",),
    )
    nested = SemanticVerifierEvidenceV2(
        verifier_id=verifier.verifier_id,
        verifier_source_sha256=verifier.source_sha256,
        input_kind="file",
        input_sha256="5" * 64,
        artifact_tree_sha256="6" * 64,
        artifact_manifest_sha256="7" * 64,
        workspace_contract_sha256=trust.output_contract_sha256,
        intent_confirmation_sha256=trust.intent_confirmation_sha256,
        upstream_commit=trust.upstream_commit,
        import_module=trust.import_module,
        upstream_imports=1,
        upstream_calls=1,
        input_negative_control_sha256="8" * 64,
        input_negative_control_result="REJECTED",
        artifact_negative_control_tree_sha256="9" * 64,
        artifact_negative_control_result="REJECTED",
        upstream_result_counterfactual_result="REJECTED",
        upstream_result_counterfactual_upstream_imports=1,
        upstream_result_counterfactual_upstream_calls=1,
        required_commitment_ids=trust.required_commitment_ids,
        checked_commitment_ids=trust.required_commitment_ids,
        passed=True,
    )
    nested_path = semantic_dir / "semantic.json"
    write_workspace_semantic_evidence(nested_path, nested)
    nested_hash = workspace_semantic_evidence_sha256(nested)
    (tool_dir / "tool.json").write_text(
        json.dumps({"workspace_contract": _workspace_contract()}),
        encoding="utf-8",
    )
    runtime_hash = tool_release.runtime_environment_sha256(tool_dir)
    outer = {
        "schema_version": 2,
        "input_sha256": nested.input_sha256,
        "runtime_environment_sha256": runtime_hash,
        "execution": {
            "artifact_tree_sha256": nested.artifact_tree_sha256,
            "artifact_manifest_sha256": nested.artifact_manifest_sha256,
        },
        "semantic_verifier": {
            "verifier_id": verifier.verifier_id,
            "artifact_tree_sha256": nested.artifact_tree_sha256,
            "artifact_manifest_sha256": nested.artifact_manifest_sha256,
            "evidence_sha256": nested_hash,
            "evidence_path": str(nested_path),
            "passed": True,
            "required_commitment_ids": list(trust.required_commitment_ids),
            "checked_commitment_ids": list(trust.required_commitment_ids),
        },
    }
    (release_dir / "audit.json").write_text(json.dumps(outer), encoding="utf-8")
    outer_hash = hashlib.sha256(json.dumps(outer, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    assert tool_release.validate_release_audit_evidence(
        tool_dir,
        evidence_sha256=outer_hash,
        require_semantic_pass=True,
        trust_identity=trust,
    )

    tampered = json.loads(nested_path.read_text(encoding="utf-8"))
    tampered["artifact_tree_sha256"] = "a" * 64
    nested_path.write_text(json.dumps(tampered), encoding="utf-8")
    assert not tool_release.validate_release_audit_evidence(
        tool_dir,
        evidence_sha256=outer_hash,
        require_semantic_pass=True,
        trust_identity=trust,
    )
