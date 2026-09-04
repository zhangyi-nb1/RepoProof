"""Draft self-check: the pre-freeze consistency proof for machine-drafted controls.

A workspace draft carries four machine-authored control files (fixture builder,
fixture blueprints, reference implementation, independent verifier).  Before
2026-09-02 their mutual consistency was only exercised when a human asked for
candidate examples, and every defect the screen found had to be repaired by a
human.  This module owns the durable proof that the Harness itself materialised
the controls, judged them with its existing rulers (builder → distinct inputs →
reference → verifier + counterfactual controls + coverage) plus the verifier
discrimination probe, and — when allowed — repaired them within a bound.

The report binds the exact bytes it proved.  Any later edit to a control file
or to the public semantics makes it STALE; readiness then blocks freezing (not
human review) until a fresh self-check passes.  Hand-authored drafts (no
``draft_meta.json``) and cli_v2 drafts are out of scope by design.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from repoproof.execution.core_execution import atomic_write_json

SELF_CHECK_FILENAME = "draft_selfcheck.json"
DRAFT_META_FILENAME = "draft_meta.json"
WORKSPACE_PROFILE_ID = "workspace_bundle_v1"
CONTROL_FILES: tuple[str, ...] = (
    "fixture_builder.py",
    "fixture_blueprints.json",
    "reference_impl.py",
    "semantic_verifier.py",
)
MAX_REPAIR_ROUNDS = 3
# The stall budget above is spent only by repairs that face a failure already
# seen; a repair facing a brand-new failure is progress and is free — up to this
# hard cap on repairs in one self-check (incident-selfcheck-bound-monotone-progress-*).
#
# The cap is a backstop against an unbounded loop, not the judge of whether a
# draft is converging: that judgement belongs to the stall budget, which reads
# the evidence.  At 6 the backstop was deciding outcomes — three repositories
# retired six *distinct* defect signatures each, spent not one unit of stall
# budget, and were cut off mid-convergence
# (incident-selfcheck-hard-cap-stops-progress-*).  A runnable workspace has four
# control files and routinely surfaces more independent defects than a
# single-file task, so the backstop sits well above that count; a draft that
# genuinely cannot converge is still ended by the stall budget after four
# sightings of one signature.
MAX_TOTAL_REPAIR_ROUNDS = 12
# Marker appended to the round the backstop truncated, so "still converging,
# budget spent" is never read as "this failure has nowhere to be repaired".
REPAIR_BUDGET_EXHAUSTED = "SELF_CHECK_REPAIR_BUDGET_EXHAUSTED"

RepairTarget = Literal["builder", "reference", "verifier", "contract"]
RepairOutcome = Literal["APPLIED", "NO_PROGRESS", "ROLLED_BACK", "UNAVAILABLE"]
SelfCheckStatus = Literal["NOT_APPLICABLE", "MISSING", "STALE", "FAILED", "PASSED"]

_DISAGREEMENT_CODE = "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"
# Reference/verifier disagreement is symmetric evidence across *all four*
# controls, not two: the judge answers first (it has no producer to lean on),
# the producer second, and when neither moves the failure the contract's file
# rules and the fixture builder — the two owners the sub-diagnostic keeps
# naming — get their turn before the producer is asked again.
_DISAGREEMENT_OWNERS: tuple[RepairTarget, ...] = (
    "verifier",
    "verifier",
    "reference",
    "reference",
    "contract",
    "builder",
    "reference",
)
# Builder codes that are the frozen asset's own doing (repairable) versus the
# environment's (systemic; never handed to a model).
_BUILDER_SYSTEMIC_CODES = frozenset(
    {
        "FIXTURE_BUILDER_ISOLATION_UNAVAILABLE",
        "FIXTURE_BUILDER_PYTHON_MISSING",
        "FIXTURE_BUILDER_EXECUTION_FAILED",
        "FIXTURE_BUILDER_UNREADABLE",
        "FIXTURE_BUILDER_UNSAFE",
        "FIXTURE_BUILDER_CHANGED_DURING_READ",
        "FIXTURE_ROOT_UNSAFE",
        "FIXTURE_DESTINATION_EXISTS",
    }
)
# Runtime-closure codes that are a contract-vs-producer disagreement, unlike the
# environment-side WORKSPACE_RUNTIME_* codes (wheelhouse/lock/wheel set), which
# no model can repair and which stay unrouted.
_RUNTIME_CLOSURE_DISAGREEMENT_CODES = frozenset(
    {
        "WORKSPACE_RUNTIME_APPLICATION_MISSING",
        "WORKSPACE_RUNTIME_ENTRYPOINT_MISSING",
        "WORKSPACE_RUNTIME_OWNED_PATH_COLLISION",
        # The contract's smoke command failing on the reference workspace is
        # the same disagreement: producer first, then the command/contract.
        "WORKSPACE_REFERENCE_SMOKE_FAILED",
    }
)
# Validation codes that implicate the contract's own structure (rule overlap,
# resource limits) rather than what the reference produced.
_CONTRACT_STRUCTURAL_DIAGNOSTICS = frozenset(
    {
        "WORKSPACE_RULE_OVERLAP",
        "WORKSPACE_PATH_TOO_DEEP",
        "WORKSPACE_PATH_TOO_LONG",
        "WORKSPACE_FILE_COUNT_EXCEEDED",
        "WORKSPACE_TOTAL_BYTES_EXCEEDED",
        "WORKSPACE_FILE_TOO_LARGE",
    }
)
_REFERENCE_CODES = frozenset(
    {
        "WORKSPACE_REFERENCE_EXECUTION_FAILED",
        "WORKSPACE_REFERENCE_NOT_REPRODUCIBLE",
        "WORKSPACE_REFERENCE_PROTOCOL_INVALID",
        "WORKSPACE_REFERENCE_CONTRACT_FAILED",
        "WORKSPACE_REFERENCE_PROCESS_FAILED",
    }
)
_VERIFIER_CODES = frozenset(
    {
        "WORKSPACE_SEMANTIC_SCREEN_EXECUTION_FAILED",
        "VERIFIER_DISCRIMINATION_GAP",
    }
)


class DraftControlBindingV1(BaseModel):
    """Exact identities the self-check proved; None means the file was absent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    semantics_sha256: str | None = None
    fixture_builder_sha256: str | None = None
    fixture_blueprints_sha256: str | None = None
    reference_sha256: str | None = None
    semantic_verifier_sha256: str | None = None


class DraftSelfCheckRepairV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target: RepairTarget
    attempts: int = Field(ge=0, le=2)
    before_sha256: str | None = None
    after_sha256: str | None = None
    outcome: RepairOutcome
    reason_code: str | None = None
    # Public rows ("loc: msg") explaining a non-applied outcome; never model output.
    diagnostics: tuple[str, ...] = ()


class DraftSelfCheckRoundV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    round: int = Field(ge=1)
    check_ok: bool
    reason_codes: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    generation_id: str | None = None
    candidate_count: int = Field(default=0, ge=0)
    discrimination_probed: int = Field(default=0, ge=0)
    discrimination_gaps: tuple[str, ...] = ()
    repair: DraftSelfCheckRepairV1 | None = None


class DraftSelfCheckReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    ok: bool
    drafter: str
    rounds: tuple[DraftSelfCheckRoundV1, ...] = Field(min_length=1)
    bound: DraftControlBindingV1
    final_reason_codes: tuple[str, ...] = ()
    recommended_action: str = ""
    created_at: str


def _sha256_file(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def draft_semantics_binding_sha256(draft: dict) -> str | None:
    """Hash the public semantics a self-check proved against.

    Confirmation state is excluded on purpose: confirming does not change what
    the controls were checked against, while editing commitments, the artifact
    protocol, delivery requirements or the workspace contract does.
    """

    intent = draft.get("_intent_contract")
    raw_tool = draft.get("tool")
    tool: dict[str, object] = raw_tool if isinstance(raw_tool, dict) else {}
    if not isinstance(intent, dict):
        return None
    public = {key: value for key, value in intent.items() if key != "confirmation"}
    basis = {
        "intent": public,
        "workspace_contract": tool.get("workspace_contract"),
    }
    try:
        encoded = json.dumps(
            basis, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(encoded).hexdigest()


def draft_control_binding(draft: dict, draft_dir: Path) -> DraftControlBindingV1:
    draft_dir = Path(draft_dir)
    return DraftControlBindingV1(
        semantics_sha256=draft_semantics_binding_sha256(draft),
        fixture_builder_sha256=_sha256_file(draft_dir / "fixture_builder.py"),
        fixture_blueprints_sha256=_sha256_file(draft_dir / "fixture_blueprints.json"),
        reference_sha256=_sha256_file(draft_dir / "reference_impl.py"),
        semantic_verifier_sha256=_sha256_file(draft_dir / "semantic_verifier.py"),
    )


def is_workspace_draft(draft: dict) -> bool:
    delivery = draft.get("_delivery_profile")
    tool = draft.get("tool")
    profile = None
    if isinstance(delivery, dict):
        profile = delivery.get("profile_id")
    if profile is None and isinstance(tool, dict):
        profile = tool.get("delivery_profile_id")
    return profile == WORKSPACE_PROFILE_ID


def is_machine_drafted(draft_dir: Path) -> bool:
    meta = Path(draft_dir) / DRAFT_META_FILENAME
    return not meta.is_symlink() and meta.is_file()


def read_draft_self_check(draft_dir: Path) -> DraftSelfCheckReportV1 | None:
    path = Path(draft_dir) / SELF_CHECK_FILENAME
    if path.is_symlink() or not path.is_file():
        return None
    try:
        if path.stat().st_size > 1024 * 1024:
            return None
        return DraftSelfCheckReportV1.model_validate_json(path.read_bytes())
    except (OSError, ValueError):
        return None


def write_draft_self_check(draft_dir: Path, report: DraftSelfCheckReportV1) -> Path:
    path = Path(draft_dir) / SELF_CHECK_FILENAME
    atomic_write_json(path, report.model_dump(mode="json"))
    return path


def self_check_status(draft: dict, draft_dir: Path) -> SelfCheckStatus:
    """Classify the durable proof against the draft's current bytes."""

    draft_dir = Path(draft_dir)
    if not is_workspace_draft(draft) or not is_machine_drafted(draft_dir):
        return "NOT_APPLICABLE"
    report = read_draft_self_check(draft_dir)
    if report is None:
        return "MISSING"
    if report.bound != draft_control_binding(draft, draft_dir):
        return "STALE"
    return "PASSED" if report.ok else "FAILED"


def _names_the_verifier_by_construction(diagnostics: tuple[str, ...] | list[str]) -> bool:
    """Sub-diagnostics only the judge can own, whoever else is in the rotation."""

    return any(
        marker in str(item).upper()
        for item in diagnostics
        for marker in ("_BINDING_CONTROL_FAILED", "VERIFIER_INFORMATIONAL_")
    )


def repair_target_for(
    reason_code: str, *, round_index: int, diagnostics: tuple[str, ...] | list[str] = ()
) -> RepairTarget | None:
    """Route one public self-check failure to the control it implicates.

    Reference/verifier disagreement is symmetric evidence; the independent
    judge is repaired first and second (it has no producer to lean on), the
    producer third.  ``round_index`` counts prior repairs of *this* code, never the
    global repair count: a builder repair must not spend the verifier's turn.
    Environment and Harness failures never reach a model.
    """

    code = str(reason_code or "")
    if not code:
        return None
    if code == _DISAGREEMENT_CODE and _names_the_verifier_by_construction(diagnostics):
        # A Harness-run binding control proves the verdict ignored the input or
        # the pinned upstream's returned values, and an informational verdict is
        # the judge contradicting its own protocol: both are verifier-side by
        # construction, whatever the same-code counter says.  Spending the
        # judge's turns on unrelated content sub-failures first sent these to
        # owners who could not possibly fix them
        # (incident-binding-control-failure-routed-to-producer-*).  The stall
        # budget still ends an unfixable one.
        return "verifier"
    if code == _DISAGREEMENT_CODE:
        # Two evidence-based attempts on the judge (the second one knows the
        # first did not change the outcome), then the producer.  When neither
        # moves the failure, the remaining two controls get their turn: the
        # disagreement's sub-diagnostic routinely names a *third* owner — the
        # contract's file rules (the judge demands a file the contract just
        # rejected as extra) or the fixture builder (the judge cannot read the
        # input it was handed) — and spending every repair on the two obvious
        # owners fixes neither
        # (incident-disagreement-subdiagnostic-owner-ignored-*).
        index = min(max(int(round_index), 1), len(_DISAGREEMENT_OWNERS)) - 1
        return _DISAGREEMENT_OWNERS[index]
    if code in _VERIFIER_CODES:
        return "verifier"
    if code in _RUNTIME_CLOSURE_DISAGREEMENT_CODES:
        # The Core closure step found the producer not honouring its own
        # contract (declared entrypoint never written).  The producer answers
        # first; the same code again means the contract's runtime shape is
        # the noise (runnable/entrypoint) and gets the representation repair.
        return "reference" if round_index <= 1 else "contract"
    if code == "WORKSPACE_REFERENCE_CONTRACT_FAILED":
        observed = {
            part.strip() for item in diagnostics for part in str(item).split(",") if part.strip()
        }
        if observed & _CONTRACT_STRUCTURAL_DIAGNOSTICS:
            # Structure is symmetric evidence too: the contract answers first,
            # the producer (which writes the colliding paths) second, and so on.
            # The same code again means the other side was the noise
            # (incident-structural-contract-failure-never-alternates-*).
            return "contract" if round_index % 2 == 1 else "reference"
        return "reference"
    if code in _REFERENCE_CODES:
        return "reference"
    if code in _BUILDER_SYSTEMIC_CODES:
        return None
    if code == "WORKSPACE_REFERENCE_FIXTURE_REJECTED":
        return "builder"
    if code.startswith("FIXTURE_") or code.startswith("WORKSPACE_FIXTURE_BLUEPRINT"):
        return "builder"
    return None
