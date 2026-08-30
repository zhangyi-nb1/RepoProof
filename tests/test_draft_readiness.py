"""Core-owned Product draft readiness and freeze-gate parity."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from repoproof.adoption.assembly.example_compiler import truth_binding_sha256
from repoproof.adoption.delivery.product_profile import product_delivery_profile
from repoproof.adoption.intake.draft_readiness import (
    evaluate_draft_readiness,
    read_draft_readiness,
)
from repoproof.adoption.intake.intent_contract import (
    confirm_intent_contract,
    install_artifact_protocol,
    install_delivery_intent_from_interface,
    install_semantic_commitments,
    new_intent_contract,
)
from repoproof.adoption.intake.tool_confirm import check_draft_complete


def _draft(*, confirmed: bool = True) -> dict:
    draft = {
        "_delivery_profile": {"schema_version": 1, "profile_id": "cli_v2"},
        "_intent_contract": new_intent_contract(
            "Use the fixed upstream to transform one local input into text."
        ),
        "source_repo": {
            "url": "https://github.com/example/upstream",
            "resolved_commit": "a" * 40,
            "license": "MIT",
            "distribution": "upstream-dist",
            "import_module": "upstream_module",
        },
        "tool": {
            "schema_version": 3,
            "name": "sample-tool",
            "summary": "Transform one local input.",
            "interface": {
                "usage": "sample-tool <input> [--out FILE]",
                "input": {"kind": "file", "format": "TXT"},
                "output": {
                    "kind": "stdout",
                    "format": "plain text",
                    "contract": {
                        "media_type": "text/plain",
                        "root_type": "text",
                        "required": {},
                        "validation_profile": "plain_text_v1",
                    },
                },
                "exit_codes": {
                    "0": "success",
                    "1": "user_error",
                    "2": "internal_error",
                },
            },
        },
        "capability": {"statement": "", "output_schema": "TransformedText"},
    }
    install_delivery_intent_from_interface(draft, profile_id="cli_v2")
    install_semantic_commitments(draft, [{
        "commitment_id": "transform-input",
        "public_text": "Transform the input with the fixed upstream.",
        "rationale": "This is the requested public behaviour.",
    }])
    install_artifact_protocol(draft, {
        "schema_version": 1,
        "protocol_id": "transformed-text-v1",
        "observations": [{
            "observation_id": "transformed-body",
            "commitment_ids": ["transform-input"],
            "locator": "完整 UTF-8 文本正文",
            "value_encoding": "固定版本上游产生的 UTF-8 文本",
        }],
    })
    if confirmed:
        confirm_intent_contract(draft, confirmed_at="2026-08-30T00:00:00Z")
    return draft


def _bundle(root: Path, *, confirmed: bool = True) -> tuple[dict, Path]:
    root.mkdir()
    (root / "examples").mkdir()
    (root / "examples" / "one.txt").write_text("one", encoding="utf-8")
    draft = _draft(confirmed=confirmed)
    (root / "draft.yaml").write_text(
        yaml.safe_dump(draft, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (root / "examples.yaml").write_text(
        yaml.safe_dump({
            "examples": [
                {"input_file": "one.txt", "expected": "ONE"},
                {"input": "two", "expected": "TWO"},
                {"input": "three", "expected": "THREE"},
            ]
        }),
        encoding="utf-8",
    )
    (root / "reference_impl.py").write_text(
        "import upstream_module\n\n"
        "def extract(input_path):\n"
        "    return upstream_module.transform(input_path.read_text())\n",
        encoding="utf-8",
    )
    (root / "semantic_verifier.py").write_text(
        "import upstream_module\n\n"
        "def verify(input_path, artifact_path):\n"
        "    expected = upstream_module.transform(input_path.read_text())\n"
        "    ok = artifact_path.read_text() == expected\n"
        "    return {'ok': ok, 'reason_codes': [], "
        "'checked_commitment_ids': ['transform-input']}\n",
        encoding="utf-8",
    )
    (root / "reference.lock.txt").write_text(
        "upstream-dist==1.2.3\n",
        encoding="utf-8",
    )
    return draft, root


def test_current_complete_draft_is_ready_and_public_summary_has_no_source(
    tmp_path: Path,
) -> None:
    draft, bundle = _bundle(tmp_path / "draft")

    readiness = evaluate_draft_readiness(draft, bundle)

    assert readiness.status == "READY_TO_FREEZE"
    assert readiness.compatible is True
    assert readiness.current is True
    assert readiness.ready is True
    assert readiness.reason_codes == []
    assert readiness.public_summary.semantic_verifier_ready is True
    assert readiness.public_summary.commitment_coverage == "COMPLETE"
    assert readiness.public_summary.semantic_commitment_count == 1
    assert readiness.public_summary.verifier_declared_commitment_count == 1
    assert readiness.public_summary.dependency_lock_ready is True
    assert readiness.public_summary.example_count == 3
    serialised = readiness.model_dump_json()
    assert "upstream_module.transform" not in serialised
    assert check_draft_complete(draft, bundle) == []


def test_unconfirmed_current_draft_is_ready_to_confirm_not_freeze(
    tmp_path: Path,
) -> None:
    draft, bundle = _bundle(tmp_path / "draft", confirmed=False)

    readiness = evaluate_draft_readiness(draft, bundle)

    assert readiness.status == "READY_TO_CONFIRM"
    assert readiness.ready_to_confirm is True
    assert readiness.ready is False
    assert readiness.reason_codes == ["INTENT_CONFIRMATION_MISSING"]
    assert check_draft_complete(draft, bundle) == [
        "D:_intent_contract INTENT_CONFIRMATION_MISSING"
    ]


def test_unfrozen_v1_v2_and_future_drafts_are_incompatible(tmp_path: Path) -> None:
    current, bundle = _bundle(tmp_path / "draft")

    for version in (1, 2, 4):
        draft = deepcopy(current)
        draft["tool"]["schema_version"] = version
        readiness = evaluate_draft_readiness(draft, bundle)
        assert readiness.status == "INCOMPATIBLE"
        assert readiness.compatible is False
        assert readiness.current is False
        assert "TOOL_SPEC_VERSION_NOT_CURRENT" in readiness.reason_codes


def test_readiness_aggregates_verifier_lock_and_example_failures(
    tmp_path: Path,
) -> None:
    draft, bundle = _bundle(tmp_path / "draft")
    (bundle / "semantic_verifier.py").unlink()
    (bundle / "reference.lock.txt").unlink()
    (bundle / "examples.yaml").write_text("examples: []\n", encoding="utf-8")

    readiness = evaluate_draft_readiness(draft, bundle)

    assert readiness.status == "INCOMPLETE"
    assert readiness.compatible is True
    assert readiness.ready is False
    assert {
        "SEMANTIC_VERIFIER_MISSING",
        "DEPENDENCY_LOCK_MISSING",
        "EXAMPLES_INSUFFICIENT",
    }.issubset(readiness.reason_codes)


def test_dependency_lock_can_be_derived_from_the_pinned_tree(
    tmp_path: Path,
) -> None:
    draft, bundle = _bundle(tmp_path / "draft")
    (bundle / "reference.lock.txt").unlink()
    project = tmp_path / "project"
    upstream = project / "upstream-cache" / f"upstream-{'a' * 12}"
    upstream.mkdir(parents=True)
    (upstream / "pyproject.toml").write_text(
        '[project]\nname = "upstream-dist"\nversion = "1.2.3"\n',
        encoding="utf-8",
    )

    readiness = evaluate_draft_readiness(
        draft,
        bundle,
        project_root=project,
    )

    assert readiness.ready is True
    assert readiness.public_summary.dependency_lock_ready is True
    assert readiness.public_summary.dependency_lock_source == "derived"


def test_verifier_must_be_sync_while_coverage_style_is_not_a_static_gate(
    tmp_path: Path,
) -> None:
    draft, bundle = _bundle(tmp_path / "draft")
    (bundle / "semantic_verifier.py").write_text(
        "import upstream_module\n\n"
        "async def verify(input_path, artifact_path):\n"
        "    return {'ok': True, 'reason_codes': [], "
        "'checked_commitment_ids': []}\n",
        encoding="utf-8",
    )

    readiness = evaluate_draft_readiness(draft, bundle)

    assert "SEMANTIC_VERIFIER_PROTOCOL_INVALID" in readiness.reason_codes
    assert readiness.public_summary.commitment_coverage == "INCOMPLETE"

    (bundle / "semantic_verifier.py").write_text(
        "import upstream_module\n\n"
        "def verify(input_path, artifact_path):\n"
        "    def nested_only():\n"
        "        return {'ok': True, 'reason_codes': [], "
        "'checked_commitment_ids': ['transform-input']}\n",
        encoding="utf-8",
    )
    nested_only = evaluate_draft_readiness(draft, bundle)
    assert "SEMANTIC_VERIFIER_PROTOCOL_INVALID" in nested_only.reason_codes


def test_source_words_do_not_select_readiness_policy(tmp_path: Path) -> None:
    draft, bundle = _bundle(tmp_path / "draft")
    reference = bundle / "reference_impl.py"
    reference.write_text(
        '"""The word TODO is ordinary documentation here."""\n'
        + reference.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    verifier = bundle / "semantic_verifier.py"
    verifier.write_text(
        '"""A filename extension and format label are not policies."""\n'
        + verifier.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    assert evaluate_draft_readiness(draft, bundle).ready is True


def test_commitment_coverage_is_runtime_bound_not_literal_style(
    tmp_path: Path,
) -> None:
    draft, bundle = _bundle(tmp_path / "draft")
    (bundle / "semantic_verifier.py").write_text(
        "import upstream_module\n\n"
        "def _ids():\n"
        "    return ['transform-' + 'input']\n\n"
        "def verify(input_path, artifact_path):\n"
        "    expected = upstream_module.transform(input_path.read_text())\n"
        "    ok = artifact_path.read_text() == expected\n"
        "    return {'ok': ok, 'reason_codes': [], "
        "'checked_commitment_ids': _ids()}\n",
        encoding="utf-8",
    )

    readiness = evaluate_draft_readiness(draft, bundle)

    assert readiness.ready is True
    assert readiness.public_summary.commitment_coverage == "RUNTIME_PENDING"


def test_examples_reuse_safe_file_golden_and_truth_binding_checks(
    tmp_path: Path,
) -> None:
    draft, bundle = _bundle(tmp_path / "draft")
    (bundle / "examples" / "one.expected.txt").write_text(
        "ONE",
        encoding="utf-8",
    )
    (bundle / "examples.yaml").write_text(
        yaml.safe_dump({
            "examples": [
                {
                    "input_file": "one.txt",
                    "expected_file": "one.expected.txt",
                    "truth_provenance": "UPSTREAM_DERIVED_USER_CONFIRMED",
                    "truth_binding_sha256": "0" * 64,
                },
                {"input": "two", "expected": "bad\x00text"},
                {"input_file": "../escape.txt", "expected": "THREE"},
            ],
        }),
        encoding="utf-8",
    )

    readiness = evaluate_draft_readiness(draft, bundle)

    assert {
        "EXAMPLE_TRUTH_BINDING_INVALID",
        "GOLDEN_OUTPUT_INVALID",
        "EXAMPLE_INPUT_FILE_INVALID",
    }.issubset(readiness.reason_codes)
    assert readiness.ready is False
    assert truth_binding_sha256(b"one", b"ONE") != "0" * 64


def test_structured_contract_requires_exact_capability_golden(
    tmp_path: Path,
) -> None:
    draft, bundle = _bundle(tmp_path / "draft")
    format_name, contract = product_delivery_profile().contract_for("json")
    draft["tool"]["interface"]["output"] = {
        "kind": "stdout",
        "format": format_name,
        "contract": contract.model_dump(mode="json"),
    }
    install_delivery_intent_from_interface(draft, profile_id="cli_v2")
    confirm_intent_contract(draft, confirmed_at="2026-08-30T00:00:00Z")
    (bundle / "examples.yaml").write_text(
        yaml.safe_dump({
            "examples": [
                {"input_file": "one.txt", "expected": "contains:ONE"},
                {"input": "two", "expected": "contains:TWO"},
                {"input": "three", "expected": "contains:THREE"},
            ],
        }),
        encoding="utf-8",
    )

    readiness = evaluate_draft_readiness(draft, bundle)

    assert "EXACT_STRUCTURED_GOLDEN_MISSING" in readiness.reason_codes
    assert readiness.ready is False


def test_malformed_or_missing_draft_returns_structured_result(tmp_path: Path) -> None:
    bundle = tmp_path / "draft"
    bundle.mkdir()
    (bundle / "draft.yaml").write_text("- not\n- an\n- object\n", encoding="utf-8")
    invalid = read_draft_readiness(bundle)
    missing = read_draft_readiness(tmp_path / "missing")

    assert invalid.status == "INCOMPATIBLE"
    assert invalid.reason_codes == ["DRAFT_DOCUMENT_INVALID"]
    assert missing.reason_codes == ["DRAFT_DOCUMENT_MISSING"]
