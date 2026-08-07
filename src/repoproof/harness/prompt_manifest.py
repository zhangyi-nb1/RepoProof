"""PromptManifest — hash binding of the Contract -> Prompt projection.

Gate 6 proved prompts can silently diverge from contracts
(HARNESS_PROMPT_CONTAMINATION); Gate 7 proved requirements can
silently NOT reach the prompt (CONTRACT_UNDERSPECIFICATION). The
manifest pins the projection: which requirement ids were rendered,
from which spec/examples/tests bytes, into which exact prompt sha."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from repoproof.harness.requirement_spec import RequirementSpec


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_prompt_manifest(
    *,
    task_id: str,
    public_contract_sha: str,
    requirement_spec_sha: str,
    public_examples_path: Path | None,
    public_tests_tree_sha: str | None,
    rendered_prompt: str,
    spec: RequirementSpec,
) -> dict:
    rendered_ids = [
        r.id
        for r in spec.requirements
        if " ".join(r.public_text.split()) in " ".join(rendered_prompt.split())
    ]
    return {
        "task_id": task_id,
        "public_contract_sha256": public_contract_sha,
        "requirement_spec_sha256": requirement_spec_sha,
        "public_examples_sha256": (
            _sha(public_examples_path.read_bytes()) if public_examples_path else None
        ),
        "public_smoke_tests_tree_sha256": public_tests_tree_sha,
        "rendered_prompt_sha256": _sha(rendered_prompt.encode("utf-8")),
        "requirement_ids_rendered": rendered_ids,
    }


def verify_prompt_manifest(manifest: dict, *, spec: RequirementSpec, rendered_prompt: str) -> list[str]:
    """Deterministic re-check at run time; returns failures (empty=ok)."""
    failures: list[str] = []
    got_sha = _sha(rendered_prompt.encode("utf-8"))
    if got_sha != manifest.get("rendered_prompt_sha256"):
        failures.append(
            f"rendered prompt sha mismatch: {got_sha[:12]} != "
            f"{str(manifest.get('rendered_prompt_sha256'))[:12]}"
        )
    rendered = set(manifest.get("requirement_ids_rendered", []))
    missing_hard = sorted(r.id for r in spec.hard() if r.id not in rendered)
    if missing_hard:
        failures.append(f"HARD requirements not rendered: {missing_hard}")
    return failures


def write_prompt_manifest(path: Path, manifest: dict) -> str:
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")
    return _sha(payload.encode("utf-8"))
