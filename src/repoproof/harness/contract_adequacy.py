"""ContractAdequacyGate — deterministic pre-agent admission.

Gate 7's verdict decomposition exposed two spec-side failure classes:
a rule the oracle enforced but no agent-visible surface defined
(CONTRACT_UNDERSPECIFICATION), and normative text living only in YAML
comments. This gate makes both structurally impossible: it refuses to
start an agent (verdict INVALID_TASK_SPEC, zero model calls) unless
the contract, RequirementSpec, oracle collection, rendered prompt and
control results are mutually adequate. Pure functions, no LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from repoproof.harness.requirement_spec import RequirementSpec

INVALID_TASK_SPEC = "INVALID_TASK_SPEC"

UNDEFINED_REFERENCE_PATTERNS = (
    re.compile(r"\bper\s+P\d+\b"),
    re.compile(r"\bsee\s+rules?\s+above\b", re.IGNORECASE),
    re.compile(r"见上文"),
)
NORMATIVE_COMMENT_PATTERN = re.compile(r"P\d+\s*[:=]|==\s*\(|:=")


@dataclass
class AdequacyResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    checked: dict[str, bool] = field(default_factory=dict)

    @property
    def state(self) -> str:
        return "ADEQUATE" if self.ok else INVALID_TASK_SPEC


def _normalize(text: str) -> str:
    return " ".join(text.split())


def evaluate_adequacy(
    *,
    spec: RequirementSpec,
    capability_nodes: list[str],
    regression_nodes: list[str],
    rendered_prompt: str,
    contract_path: Path | None = None,
    controls_summary: dict[str, str] | None = None,
    held_out_markers: tuple[str, ...] = ("[held",),
    forbidden_prompt_tokens: tuple[str, ...] = (),
) -> AdequacyResult:
    """Run every deterministic adequacy check; collect ALL failures
    (not fail-fast) so the report shows the full gap list."""
    failures: list[str] = []
    checked: dict[str, bool] = {}

    def check(name: str, ok: bool, message: str) -> None:
        checked[name] = ok
        if not ok:
            failures.append(f"{name}: {message}")

    mapped_nodes = spec.all_oracle_nodes()
    frozen_nodes = set(capability_nodes) | set(regression_nodes)
    prompt_norm = _normalize(rendered_prompt)

    # C1 every frozen oracle node maps to >=1 requirement
    orphans = sorted(frozen_nodes - mapped_nodes)
    check("orphan_oracle_nodes", not orphans, f"unmapped oracle nodes: {orphans}")

    # C1b every mapped node actually exists in the frozen collection
    ghosts = sorted(mapped_nodes - frozen_nodes)
    check("ghost_requirement_nodes", not ghosts, f"requirement maps to unknown nodes: {ghosts}")

    # C2 every HARD requirement is checked somewhere
    unchecked = sorted(
        r.id for r in spec.hard() if not r.oracle_nodes and not r.verified_by
    )
    check("hard_requirement_unchecked", not unchecked, f"HARD without any check: {unchecked}")

    # C3 every HARD requirement's public_text is rendered into the prompt
    missing_render = sorted(
        r.id for r in spec.hard() if _normalize(r.public_text) not in prompt_norm
    )
    check(
        "hard_public_text_rendered",
        not missing_render,
        f"HARD public_text missing from prompt: {missing_render}",
    )

    # C4 no undefined references in the prompt
    dangling = [p.pattern for p in UNDEFINED_REFERENCE_PATTERNS if p.search(rendered_prompt)]
    check("undefined_prompt_references", not dangling, f"undefined references: {dangling}")

    # C5 normative semantics must not live only in contract comments
    if contract_path is not None:
        bad_comments = [
            line.strip()
            for line in contract_path.read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("#") and NORMATIVE_COMMENT_PATTERN.search(line)
        ]
        check(
            "normative_comment_only",
            not bad_comments,
            f"normative definition inside comments: {bad_comments[:3]}",
        )

    # C6 boolean fields carry a truth table (>=2 examples)
    weak_booleans = sorted(
        r.id for r in spec.requirements if r.boolean_field and len(r.examples) < 2
    )
    check("boolean_truth_table", not weak_booleans, f"boolean without truth table: {weak_booleans}")

    # C7/C8 owner + severity enums are enforced at load time; re-assert
    check(
        "owner_severity_typed",
        all(r.owner and r.severity for r in spec.requirements),
        "requirement missing owner/severity",
    )

    # C9 deterministic input boundaries belong to the host guard
    misowned = sorted(
        r.id
        for r in spec.requirements
        if r.deterministic_input_boundary and r.owner != "HOST_INPUT_GUARD"
    )
    check("input_boundary_owner", not misowned, f"input boundary not host-owned: {misowned}")

    # C10 held-out nodes may only re-test PUBLIC semantics: any
    # requirement carried ONLY by held-out nodes is a hidden rule
    def _held(node: str) -> bool:
        return any(m in node for m in held_out_markers)

    hidden = sorted(
        r.id
        for r in spec.requirements
        if r.oracle_nodes and all(_held(n) for n in r.oracle_nodes)
    )
    check("held_out_only_semantics", not hidden, f"requirement tested only held-out: {hidden}")

    # C11/C12 controls
    if controls_summary is not None:
        pos = controls_summary.get("positive_control", "")
        check("positive_control", pos == "PASS", f"positive control = {pos!r}")
        bad_ncs = sorted(
            k for k, v in controls_summary.items()
            if k.startswith("negative_control") and v != "FAILED_AS_EXPECTED"
        )
        check("negative_controls", not bad_ncs, f"negative controls not failing: {bad_ncs}")

    # Extra: leak guard — forbidden tokens must not appear in the prompt
    leaked = [t for t in forbidden_prompt_tokens if t and t in rendered_prompt]
    check("prompt_leak_tokens", not leaked, f"forbidden tokens in prompt: {leaked}")

    return AdequacyResult(ok=not failures, failures=failures, checked=checked)
