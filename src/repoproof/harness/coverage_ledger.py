"""Public Contract Coverage Ledger (Gate 4B — the ONE behavioral measure).

A requirement checklist derived EXCLUSIVELY from the v3 PUBLIC contract
text the agent can already see. Each requirement carries id /
source_field / source_quote (a verbatim substring of the public
contract — pinned by tests). It never contains oracle test names,
held-out fixtures, baseline failure info, reference adapters,
completion-gate knowledge or expected verdicts, and it does NOT
participate in the completion gate.

The agent updates status in its scratch ledger file; the harness reads
it back and reports addressed/total + unresolved ids in every
observation. Allowed agent-reported statuses: UNASSESSED / IMPLEMENTED
/ SELF_TESTED / BLOCKED — deliberately NO "PASSED"/"VERIFIED": an agent
cannot self-report verification.
"""

from __future__ import annotations

import json

from repoproof.domain.models import TaskContract

ALLOWED_STATUSES = ("UNASSESSED", "IMPLEMENTED", "SELF_TESTED", "BLOCKED")
ADDRESSED_STATUSES = ("IMPLEMENTED", "SELF_TESTED")
LEDGER_PATH = "/tmp/coverage_ledger.json"

# (id, source_field, verbatim quote from the public contract)
_REQUIREMENT_SPECS = [
    ("strategy-selection", "capability.statement",
     'honor request-level strategy selection ("sentence" | "recursive") with the frozen parameters'),
    ("boundaries-from-chonkie", "capability.statement",
     "core chunk text/order/boundaries come from the pinned Chonkie for the requested strategy"),
    ("r1-blank-zero", "capability.statement", "R1\n    (blank documents -> zero records)"),
    ("r2-preserve-oversize", "capability.statement", "R2 (preserve indivisible\n    over-size chunks verbatim)"),
    ("stable-ids", "capability.statement", "Stable non-upstream chunk ids"),
    ("document-order-ordinals", "capability.statement", "document order, contiguous ordinals"),
    ("offsets-slice-back", "capability.statement", "offsets that slice back"),
    ("metadata-passthrough", "capability.statement", "metadata passthrough"),
    ("wrapped-errors", "capability.statement", "wrapped upstream errors"),
    ("units-equal-span", "capability.units_semantics", "MUST equal char_end - char_start for every record"),
    ("chunk-size-frozen", "capability.params", "chunk_size: 120"),
    ("offline-cpu-only", "capability.statement", "fully offline,\n    CPU-only"),
]


def contract_public_text(contract: TaskContract) -> str:
    cap = contract.capability
    parts = [cap.statement, cap.units_semantics or ""]
    if cap.params:
        parts.append(json.dumps(cap.params.model_dump(), sort_keys=True))
        parts.append(f"chunk_size: {cap.params.chunk_size}")
    return "\n".join(parts)


def build_requirements(contract: TaskContract) -> list[dict]:
    """Every quote MUST be a verbatim substring of the public contract
    text (whitespace-normalized) — enforced here and pinned by tests."""
    public = " ".join(contract_public_text(contract).split())
    out = []
    for rid, field, quote in _REQUIREMENT_SPECS:
        norm_quote = " ".join(quote.split())
        if norm_quote not in public:
            raise ValueError(f"requirement {rid}: quote is not verbatim public contract text")
        out.append(
            {"id": rid, "source_field": field, "source_quote": norm_quote, "status": "UNASSESSED"}
        )
    return out


def initial_ledger_json(contract: TaskContract) -> str:
    return json.dumps(
        {
            "note": (
                "Public Contract Coverage Ledger. Update status per requirement as you work: "
                f"{'/'.join(ALLOWED_STATUSES)}. This is YOUR self-tracking aid built only from "
                "the public contract; it grants no acceptance knowledge and no verification power."
            ),
            "requirements": build_requirements(contract),
        },
        ensure_ascii=False,
        indent=1,
    )


def summarize(ledger_raw: str | None, requirements: list[dict]) -> dict:
    """Parse the agent-updated ledger; invalid statuses (incl. any
    self-awarded PASSED/VERIFIED) count as UNASSESSED."""
    statuses = {r["id"]: "UNASSESSED" for r in requirements}
    parse_note = None
    if ledger_raw:
        try:
            data = json.loads(ledger_raw)
            for item in data.get("requirements", []):
                rid = item.get("id")
                status = str(item.get("status", "UNASSESSED")).upper()
                if rid in statuses:
                    statuses[rid] = status if status in ALLOWED_STATUSES else "UNASSESSED"
        except (json.JSONDecodeError, AttributeError, TypeError) as exc:
            parse_note = f"ledger unparseable ({type(exc).__name__}); treating all as UNASSESSED"
    unresolved = [rid for rid, s in statuses.items() if s not in ADDRESSED_STATUSES]
    return {
        "total": len(statuses),
        "addressed": len(statuses) - len(unresolved),
        "unresolved_ids": unresolved,
        "statuses": statuses,
        "parse_note": parse_note,
    }


def observation_line(summary: dict, *, low_budget: bool, requirements: list[dict]) -> str:
    line = (
        f"[LEDGER] addressed {summary['addressed']}/{summary['total']}; "
        f"unresolved: {', '.join(summary['unresolved_ids']) or '(none)'}"
    )
    if summary.get("parse_note"):
        line += f" ({summary['parse_note']})"
    if low_budget and summary["unresolved_ids"]:
        quotes = {r["id"]: r["source_quote"] for r in requirements}
        line += "\nUnresolved requirement text (public contract, verbatim):"
        for rid in summary["unresolved_ids"]:
            line += f"\n  - {rid}: {quotes[rid]}"
    return line
