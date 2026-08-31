"""Task-specific semantics run through one repository-agnostic evidence protocol."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from repoproof.verification.semantic_artifact import (
    SemanticVerifierError,
    run_semantic_verifier,
    screen_semantic_candidate,
    semantic_verifier_evidence_sha256,
    write_semantic_verifier_evidence,
)


def _screen(world: dict):
    return screen_semantic_candidate(
        verifier_source=world["verifier"],
        input_path=world["input"],
        artifact_path=world["artifact"],
        python_exe=sys.executable,
        upstream_dir=world["upstream"],
        import_module="minishout",
        required_commitment_ids=["transform-input"],
        isolation_required=False,
    )


def _world(tmp_path: Path, *, verifier_source: str, artifact: str = "HELLO!") -> dict:
    upstream = tmp_path / "upstream"
    upstream.mkdir(parents=True)
    (upstream / "minishout.py").write_text(
        "def shout(text):\n    return text.strip().upper() + '!'\n",
        encoding="utf-8",
    )
    verifier = tmp_path / "semantic_verifier.py"
    verifier.write_text(verifier_source, encoding="utf-8")
    input_path = tmp_path / "input.txt"
    input_path.write_text("hello", encoding="utf-8")
    artifact_path = tmp_path / "artifact.txt"
    artifact_path.write_text(artifact, encoding="utf-8")
    return {
        "upstream": upstream,
        "verifier": verifier,
        "input": input_path,
        "artifact": artifact_path,
    }


_VERIFIER = '''from pathlib import Path

import minishout


def verify(input_path: Path, artifact_path: Path) -> dict:
    expected = minishout.shout(input_path.read_text(encoding="utf-8"))
    ok = artifact_path.read_text(encoding="utf-8") == expected
    return {
        "ok": ok,
        "reason_codes": [] if ok else ["VALUE_MISMATCH"],
        "checked_commitment_ids": ["transform-input"],
    }
'''


def _run(world: dict):
    return run_semantic_verifier(
        verifier_id="independent-text-semantics-v1",
        verifier_source=world["verifier"],
        input_path=world["input"],
        artifact_path=world["artifact"],
        python_exe=sys.executable,
        upstream_dir=world["upstream"],
        import_module="minishout",
        upstream_commit="a" * 40,
        output_contract_sha256="b" * 64,
        intent_confirmation_sha256="c" * 64,
        required_commitment_ids=["transform-input"],
        isolation_required=False,
    )


def test_semantic_verifier_pass_binds_artifact_contract_intent_and_upstream(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path, verifier_source=_VERIFIER)
    evidence = _run(world)

    assert evidence.passed is True
    assert evidence.reason_codes == ()
    assert evidence.upstream_imports == 1
    assert evidence.upstream_calls == 1
    assert evidence.input_negative_control_result == "REJECTED"
    assert evidence.input_negative_control_sha256 != evidence.input_sha256
    assert evidence.artifact_negative_control_result == "REJECTED"
    assert evidence.artifact_negative_control_upstream_calls == 1
    assert evidence.upstream_result_counterfactual_result == "REJECTED"
    assert evidence.upstream_result_counterfactual_upstream_calls == 1
    assert evidence.artifact_negative_control_sha256 != evidence.artifact_sha256
    assert evidence.artifact_sha256
    assert len(semantic_verifier_evidence_sha256(evidence)) == 64


def test_artifact_control_does_not_depend_on_verifier_evaluation_order(
    tmp_path: Path,
) -> None:
    world = _world(
        tmp_path,
        verifier_source='''from pathlib import Path

import minishout


def verify(input_path: Path, artifact_path: Path) -> dict:
    # Deliberately inspect the artifact first.  The Harness counterexample is
    # binary and therefore rejects at this line before any upstream call.
    artifact = artifact_path.read_text(encoding="utf-8")
    expected = minishout.shout(input_path.read_text(encoding="utf-8"))
    ok = artifact == expected
    return {
        "ok": ok,
        "reason_codes": [] if ok else ["VALUE_MISMATCH"],
        "checked_commitment_ids": ["transform-input"],
    }
''',
    )

    evidence = _run(world)

    assert evidence.passed is True
    assert evidence.reason_codes == ()
    assert evidence.artifact_negative_control_result == "REJECTED"
    assert evidence.artifact_negative_control_upstream_calls == 0
    assert evidence.upstream_result_counterfactual_result == "REJECTED"
    assert evidence.upstream_result_counterfactual_upstream_calls == 1


def test_verifier_that_ignores_artifact_fails_artifact_binding_control(
    tmp_path: Path,
) -> None:
    world = _world(
        tmp_path,
        verifier_source='''from pathlib import Path

import minishout


def verify(input_path: Path, artifact_path: Path) -> dict:
    expected = minishout.shout(input_path.read_text(encoding="utf-8"))
    ok = expected == "HELLO!"
    return {
        "ok": ok,
        "reason_codes": [] if ok else ["VALUE_MISMATCH"],
        "checked_commitment_ids": ["transform-input"],
    }
''',
    )

    evidence = _run(world)

    assert evidence.passed is False
    assert evidence.artifact_negative_control_result == "ACCEPTED"
    assert evidence.reason_codes == ("ARTIFACT_BINDING_CONTROL_FAILED",)


def test_domain_mismatch_is_a_task_verifier_failure_not_a_core_format_rule(
    tmp_path: Path,
) -> None:
    evidence = _run(_world(tmp_path, verifier_source=_VERIFIER, artifact="WRONG"))

    assert evidence.passed is False
    assert evidence.reason_codes == ("VALUE_MISMATCH",)
    assert evidence.upstream_calls == 1


def test_candidate_screen_admits_only_a_pair_accepted_by_independent_verifier(
    tmp_path: Path,
) -> None:
    accepted = _screen(_world(tmp_path / "ok", verifier_source=_VERIFIER))
    rejected = _screen(
        _world(tmp_path / "bad", verifier_source=_VERIFIER, artifact="WRONG")
    )

    assert accepted.mechanism_ok and accepted.passed
    assert accepted.reason_codes == ()
    assert rejected.mechanism_ok and not rejected.passed
    assert rejected.reason_codes == ("VALUE_MISMATCH",)


def test_candidate_screen_distinguishes_verifier_mechanism_failure(
    tmp_path: Path,
) -> None:
    world = _world(
        tmp_path,
        verifier_source=(
            "def verify(input_path, artifact_path):\n"
            "    return {'ok': True, 'reason_codes': [], "
            "'checked_commitment_ids': ['transform-input']}\n"
        ),
    )

    result = _screen(world)

    assert not result.mechanism_ok and not result.passed
    assert result.reason_codes == ("UPSTREAM_CALL_NOT_OBSERVED",)


def test_verifier_cannot_claim_pass_without_calling_declared_upstream(
    tmp_path: Path,
) -> None:
    world = _world(
        tmp_path,
        verifier_source=(
            "def verify(input_path, artifact_path):\n"
            "    return {'ok': True, 'reason_codes': [], "
            "'checked_commitment_ids': ['transform-input']}\n"
        ),
    )
    evidence = _run(world)

    assert evidence.passed is False
    assert "UPSTREAM_CALL_NOT_OBSERVED" in evidence.reason_codes
    assert evidence.upstream_calls == 0


def test_verifier_must_cover_every_frozen_commitment(tmp_path: Path) -> None:
    world = _world(
        tmp_path,
        verifier_source=(
            "import minishout\n"
            "def verify(input_path, artifact_path):\n"
            "    minishout.shout(input_path.read_text())\n"
            "    return {'ok': True, 'reason_codes': [], "
            "'checked_commitment_ids': []}\n"
        ),
    )

    evidence = _run(world)

    assert evidence.passed is False
    assert "COMMITMENT_COVERAGE_MISMATCH" in evidence.reason_codes
    assert evidence.required_commitment_ids == ("transform-input",)
    assert evidence.checked_commitment_ids == ()


def test_task_verifier_cannot_forge_harness_reason_codes(tmp_path: Path) -> None:
    world = _world(
        tmp_path,
        verifier_source=(
            "import minishout\n"
            "def verify(input_path, artifact_path):\n"
            "    minishout.shout(input_path.read_text())\n"
            "    return {'ok': False, "
            "'reason_codes': ['UPSTREAM_CALL_NOT_OBSERVED'], "
            "'checked_commitment_ids': ['transform-input']}\n"
        ),
    )

    evidence = _run(world)

    assert evidence.passed is False
    assert evidence.reason_codes == ("VERIFIER_PROTOCOL_ERROR",)


def test_artifact_sensitive_verifier_that_ignores_upstream_result_is_rejected(
    tmp_path: Path,
) -> None:
    world = _world(
        tmp_path,
        verifier_source='''from pathlib import Path

import minishout


def verify(input_path: Path, artifact_path: Path) -> dict:
    minishout.shout(input_path.read_text(encoding="utf-8"))
    ok = artifact_path.read_text(encoding="utf-8") == "HELLO!"
    return {
        "ok": ok,
        "reason_codes": [] if ok else ["VALUE_MISMATCH"],
        "checked_commitment_ids": ["transform-input"],
    }
''',
    )

    evidence = _run(world)

    assert evidence.passed is False
    # It really inspects the artifact, so the ordinary negative control works.
    assert evidence.artifact_negative_control_result == "REJECTED"
    # But substituting the upstream return does not affect the verdict: the
    # purported judge only called upstream for show and must fail closed.
    assert evidence.upstream_result_counterfactual_result == "ACCEPTED"
    assert evidence.upstream_result_counterfactual_upstream_calls == 1
    assert evidence.reason_codes == ("VERIFIER_PROTOCOL_ERROR",)


def test_upstream_sensitive_verifier_that_ignores_audited_input_is_rejected(
    tmp_path: Path,
) -> None:
    world = _world(
        tmp_path,
        verifier_source='''from pathlib import Path

import minishout


def verify(input_path: Path, artifact_path: Path) -> dict:
    expected = minishout.shout("hello")
    ok = artifact_path.read_text(encoding="utf-8") == expected
    return {
        "ok": ok,
        "reason_codes": [] if ok else ["VALUE_MISMATCH"],
        "checked_commitment_ids": ["transform-input"],
    }
''',
    )

    evidence = _run(world)

    assert evidence.passed is False
    assert evidence.input_negative_control_result == "ACCEPTED"
    assert evidence.input_negative_control_upstream_calls == 1
    assert evidence.reason_codes == ("INPUT_BINDING_CONTROL_FAILED",)


def test_execution_uses_the_exact_hashed_snapshots_when_live_paths_are_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repoproof.verification import semantic_artifact as semantic_module

    world = _world(tmp_path, verifier_source=_VERIFIER)
    original_source = world["verifier"].read_bytes()
    original_input = world["input"].read_bytes()
    original_artifact = world["artifact"].read_bytes()
    real_run = semantic_module.subprocess.run
    replaced = False

    def replacing_run(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            replaced = True
            replacements = {
                world["verifier"]: b"def verify(*args):\n    return {}\n",
                world["input"]: b"attacker-input",
                world["artifact"]: b"attacker-artifact",
            }
            for target, payload in replacements.items():
                pending = target.with_name(target.name + ".replacement")
                pending.write_bytes(payload)
                os.replace(pending, target)
        return real_run(*args, **kwargs)

    monkeypatch.setattr(semantic_module.subprocess, "run", replacing_run)

    evidence = _run(world)

    assert evidence.passed is True
    assert evidence.verifier_source_sha256 == hashlib.sha256(
        original_source
    ).hexdigest()
    assert evidence.input_sha256 == hashlib.sha256(original_input).hexdigest()
    assert evidence.artifact_sha256 == hashlib.sha256(original_artifact).hexdigest()
    assert evidence.verifier_source_sha256 != hashlib.sha256(
        world["verifier"].read_bytes()
    ).hexdigest()
    assert evidence.input_sha256 != hashlib.sha256(
        world["input"].read_bytes()
    ).hexdigest()
    assert evidence.artifact_sha256 != hashlib.sha256(
        world["artifact"].read_bytes()
    ).hexdigest()


def test_semantic_evidence_is_append_only_and_rejects_symlink_input(
    tmp_path: Path,
) -> None:
    world = _world(tmp_path, verifier_source=_VERIFIER)
    evidence = _run(world)
    path = write_semantic_verifier_evidence(tmp_path / "evidence" / "case.json", evidence)
    assert json.loads(path.read_text(encoding="utf-8"))["passed"] is True
    with pytest.raises(SemanticVerifierError, match="append-only"):
        write_semantic_verifier_evidence(path, evidence)

    linked = tmp_path / "linked-input.txt"
    linked.symlink_to(world["input"])
    world["input"] = linked
    with pytest.raises(SemanticVerifierError, match="non-symlink"):
        _run(world)
