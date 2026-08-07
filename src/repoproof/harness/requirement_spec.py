"""RequirementSpec — structured, machine-checkable requirement inventory.

Every verdict-affecting rule of a v2+ task lives here as a typed
requirement with an owner, a severity, public text (rendered verbatim
into the agent prompt), examples, and oracle-node bindings. Normative
semantics in YAML comments are FORBIDDEN — the Gate 7 failure
(CONTRACT_UNDERSPECIFICATION: a rule defined only in comments) is the
reason this module exists.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import BaseModel

OWNERS = ("HOST_INPUT_GUARD", "ADAPTER", "HARNESS", "UPSTREAM")
SEVERITIES = ("HARD", "SOFT")


class SpecError(ValueError):
    """Structural violation inside a RequirementSpec file."""


class Requirement(BaseModel):
    id: str
    owner: str
    severity: str
    source_field: str
    public_text: str
    examples: list[str] = []
    oracle_nodes: list[str] = []
    boolean_field: str | None = None
    deterministic_input_boundary: bool = False
    verified_by: str | None = None
    """For HARD requirements without oracle nodes (HARNESS/UPSTREAM
    owners): the non-oracle verifier that covers them."""


class NegativeControl(BaseModel):
    path: str
    label: str
    must_fail_nodes: list[str]


class ControlsSpec(BaseModel):
    positive: str
    negatives: list[NegativeControl]


class RequirementSpec(BaseModel):
    task_id: str
    requirements: list[Requirement]
    controls: ControlsSpec | None = None

    def by_id(self) -> dict[str, Requirement]:
        return {r.id: r for r in self.requirements}

    def hard(self) -> list[Requirement]:
        return [r for r in self.requirements if r.severity == "HARD"]

    def all_oracle_nodes(self) -> set[str]:
        return {n for r in self.requirements for n in r.oracle_nodes}

    def responsibility_matrix(self) -> dict[str, list[str]]:
        matrix: dict[str, list[str]] = {}
        for r in self.requirements:
            matrix.setdefault(r.owner, []).append(r.id)
        return {k: sorted(v) for k, v in sorted(matrix.items())}


def load_requirement_spec(path: Path) -> tuple[RequirementSpec, str]:
    """Load + structurally validate; returns (spec, sha256 of bytes)."""
    raw = path.read_bytes()
    spec = RequirementSpec.model_validate(yaml.safe_load(raw))
    seen: set[str] = set()
    for r in spec.requirements:
        if r.id in seen:
            raise SpecError(f"duplicate requirement id {r.id!r}")
        seen.add(r.id)
        if r.owner not in OWNERS:
            raise SpecError(f"{r.id}: owner {r.owner!r} not in {OWNERS}")
        if r.severity not in SEVERITIES:
            raise SpecError(f"{r.id}: severity {r.severity!r} not in {SEVERITIES}")
        if not r.public_text.strip():
            raise SpecError(f"{r.id}: public_text is empty")
        if r.deterministic_input_boundary and r.owner != "HOST_INPUT_GUARD":
            raise SpecError(
                f"{r.id}: deterministic input boundaries are host responsibility "
                f"(owner must be HOST_INPUT_GUARD, got {r.owner})"
            )
        if r.severity == "HARD" and not r.oracle_nodes and not r.verified_by:
            raise SpecError(f"{r.id}: HARD requirement has neither oracle_nodes nor verified_by")
    return spec, hashlib.sha256(raw).hexdigest()
