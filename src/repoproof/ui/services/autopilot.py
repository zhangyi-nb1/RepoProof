"""Journey autopilot: repository URL + one sentence → ACTIVE, with machine gates.

The autopilot does not add a new judgement anywhere.  It drives the exact
production path a person drives from Studio or the CLI — ``tool add`` (which
already self-checks and self-repairs the drafted controls), candidate
confirmation, intent confirmation, wheelhouse freezing, rehearsal, the real
Agent build, and the fresh audit — and records, stage by stage, what each
production step decided.  The two human gates it replaces (confirming examples
and confirming intent) are recorded with ``confirmed_by: autopilot`` so nobody
can later mistake them for a person's review.

Stops are honest: the first failing stage ends the journey with that stage's
owner and public reason codes; there is no retry loop here beyond the bounded
mechanisms already inside each stage.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from repoproof.execution.core_execution import atomic_write_json
from repoproof.ui.services.product_mode import ui_state_root

Stage = Literal[
    "draft",
    "confirm_examples",
    "confirm_intent",
    "freeze_wheelhouse",
    "rehearsal",
    "real_build",
    "fresh_audit",
    "final",
]
STAGES: tuple[Stage, ...] = (
    "draft",
    "confirm_examples",
    "confirm_intent",
    "freeze_wheelhouse",
    "rehearsal",
    "real_build",
    "fresh_audit",
    "final",
)
Runner = Callable[[Sequence[str]], dict]


class AutopilotStageV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Stage
    ok: bool
    reason_codes: tuple[str, ...] = ()
    detail: str = Field(default="", max_length=2000)
    elapsed_s: float = Field(default=0.0, ge=0.0)
    facts: dict[str, str | int | bool | None] = Field(default_factory=dict)


class AutopilotReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    journey_id: str
    repo: str
    capability: str
    revision: str | None = None
    draft_dir: str | None = None
    task_id: str | None = None
    tool_name: str | None = None
    expected_admission_rejection: bool = False
    until: Stage = "final"
    stages: tuple[AutopilotStageV1, ...] = ()
    ok: bool
    final_status: str
    stop_stage: Stage | None = None
    stop_reason_codes: tuple[str, ...] = ()
    provenance: dict[str, str] = Field(default_factory=dict)
    created_at: str
    completed_at: str


def _now() -> str:
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_cli_json(stdout: str) -> dict:
    start = stdout.find("{")
    end = stdout.rfind("}")
    if start < 0 or end < start:
        raise ValueError("CLI produced no JSON payload")
    return json.loads(stdout[start : end + 1])


def cli_runner(project_root: Path) -> Runner:
    """Run one ``repoproof tool …`` verb the way Studio's job worker does."""

    def _run(argv: Sequence[str]) -> dict:
        process = subprocess.run(  # noqa: S603 - fixed interpreter, typed argv
            [sys.executable, "-m", "repoproof.cli", *argv],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=6 * 3600,
            check=False,
        )
        try:
            payload = _parse_cli_json(process.stdout)
        except ValueError:
            payload = {
                "ok": False,
                "error": "CLI_PAYLOAD_MISSING",
                "reason_codes": ["CLI_PAYLOAD_MISSING"],
                "stderr_tail": process.stderr[-600:],
            }
        payload.setdefault("exit_code", process.returncode)
        return payload

    return _run


# The audit CLI's two ACTIVE outcomes (tool_release._record_audit_decision).
FRESH_AUDIT_PASS_REASONS = frozenset({"FRESH_INPUT_PASS", "FRESH_INPUT_SEMANTIC_PASS"})


def _codes(payload: dict, *fallback: str) -> tuple[str, ...]:
    codes = [str(item) for item in (payload.get("reason_codes") or []) if str(item)]
    if not codes:
        for key in ("failure_class", "product_stop_code", "error_code"):
            value = payload.get(key)
            if value:
                codes.append(str(value))
                break
    return tuple(codes) if codes else tuple(fallback)


def _failed_substage(payload: dict) -> tuple[str | None, tuple[str, ...], str, str | None]:
    """Locate the first ``ok=False`` substage inside a CLI payload's ``stages``.

    A blocked build reports its cause in the substage that stopped it (for
    example ``stages.preflight``), not in the stage the autopilot asked for.
    Returns ``(substage_name, codes, detail, failure_owner)``.
    """

    stages = payload.get("stages") or {}
    if not isinstance(stages, dict):
        return None, (), "", None
    for name, sub in stages.items():
        if not isinstance(sub, dict):
            continue
        blocked = sub.get("blocked") is True
        if sub.get("ok") is not False and not blocked:
            continue
        codes = _codes(sub)
        if not codes and sub.get("reason_code"):
            codes = (str(sub["reason_code"]),)
        detail = str(sub.get("detail") or sub.get("error") or "")
        if blocked:
            # A blocked stage carries its cause in its own preflight block
            # (provider/gateway status + evidence lines), not in reason_codes.
            raw_preflight = sub.get("preflight")
            preflight: dict = raw_preflight if isinstance(raw_preflight, dict) else {}
            status = str(preflight.get("status") or "")
            if not codes and status:
                codes = (status,)
            if not detail:
                detail = "; ".join(str(item) for item in (preflight.get("evidence") or [])[:4])
            owner = str(sub.get("failure_owner") or "") or ("EXTERNAL" if status else None)
            return str(name), codes, detail, owner
        if not detail:
            failed_checks = [
                check for check in (sub.get("checks") or [])
                if isinstance(check, dict) and check.get("ok") is False
            ]
            if failed_checks:
                last = failed_checks[-1]
                detail = str(last.get("detail") or last.get("reason_code") or "")
        if not detail:
            detail = str(sub.get("recommended_action") or "")
        owner = str(sub.get("failure_owner") or "") or None
        return str(name), codes, detail, owner
    return None, (), "", None


def run_journey_autopilot(
    *,
    repo: str,
    capability: str,
    project_root: Path,
    dest_root: Path,
    revision: str | None = None,
    until: Stage = "final",
    expect_admission_rejection: bool = False,
    batch: str = "EXPLORATORY_UNPREREGISTERED",
    agent_backend: str = "mini-swe",
    runner: Runner | None = None,
    record_dir: Path | None = None,
    resume_task_id: str | None = None,
    resume_tool_name: str | None = None,
    journey_id: str | None = None,
) -> dict:
    from repoproof.ui.services import product_jobs
    from repoproof.ui.services.product_journeys import create_journey, update_journey

    project_root = Path(project_root)
    dest_root = Path(dest_root).expanduser()
    run = runner or cli_runner(project_root)

    def run_stage(stage: str, argv: list[str]) -> dict:
        """Run one CLI stage and persist its raw payload so failures are diagnosable from disk."""

        payload = run(argv)
        roots = [Path(record_dir) / "stages"] if record_dir is not None else []
        try:
            roots.append(ui_state_root() / "autopilot" / journey.journey_id / "stages")
        except Exception:  # noqa: BLE001 — state root is best effort
            pass
        for root in roots:
            try:
                root.mkdir(parents=True, exist_ok=True)
                atomic_write_json(
                    root / f"{stage}.json",
                    payload if isinstance(payload, dict) else {"payload": payload},
                )
            except OSError:
                continue
        return payload
    created_at = _now()
    stages: list[AutopilotStageV1] = []
    facts: dict[str, str | None] = {
        "draft_dir": None,
        "task_id": resume_task_id,
        "tool_name": resume_tool_name,
    }

    def record(
        stage: Stage,
        ok: bool,
        *,
        codes: tuple[str, ...] = (),
        detail: str = "",
        started: float,
        extra: dict | None = None,
    ) -> AutopilotStageV1:
        item = AutopilotStageV1(
            stage=stage,
            ok=ok,
            reason_codes=codes,
            detail=detail[:2000],
            elapsed_s=round(max(0.0, time.monotonic() - started), 1),
            facts={k: v for k, v in (extra or {}).items() if isinstance(v, (str, int, bool)) or v is None},
        )
        stages.append(item)
        return item

    journey = create_journey(
        source_repo_url=repo,
        draft_dir=Path("/dev/null"),
        dest_root=dest_root,
        journey_id=journey_id,
    )
    draft_dir = ui_state_root() / "drafts" / f"journey-{journey.journey_id[:12]}"
    update_journey(journey.journey_id, draft_dir=str(draft_dir))
    facts["draft_dir"] = str(draft_dir)

    def finish(*, ok: bool, status: str, stop: Stage | None, codes: tuple[str, ...]) -> dict:
        report = AutopilotReportV1(
            journey_id=journey.journey_id,
            repo=repo,
            capability=capability,
            revision=revision,
            draft_dir=facts["draft_dir"],
            task_id=facts["task_id"],
            tool_name=facts["tool_name"],
            expected_admission_rejection=expect_admission_rejection,
            until=until,
            stages=tuple(stages),
            ok=ok,
            final_status=status,
            stop_stage=stop,
            stop_reason_codes=codes,
            provenance={
                "examples_confirmed_by": "autopilot",
                "intent_confirmed_by": "autopilot",
                "human_material": "repository URL + one-sentence capability request only",
            },
            created_at=created_at,
            completed_at=_now(),
        )
        root = ui_state_root() / "autopilot"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{journey.journey_id}.json"
        atomic_write_json(path, report.model_dump(mode="json"))
        if record_dir is not None:
            Path(record_dir).mkdir(parents=True, exist_ok=True)
            atomic_write_json(Path(record_dir) / "autopilot-report.json", report.model_dump(mode="json"))
        return {"ok": ok, "status": status, "report_path": str(path), "report": report.model_dump(mode="json")}

    def stop_after(stage: Stage) -> bool:
        return STAGES.index(stage) >= STAGES.index(until)

    resume = resume_task_id is not None
    if not resume:
        # ---- draft (admission + drafting + self-check/self-repair) ----
        started = time.monotonic()
        payload = run_stage(
            "draft",
            [
                "tool",
                "add",
                "--repo",
                repo,
                "--capability",
                capability,
                "--draft-out",
                str(draft_dir),
                *(["--revision", revision] if revision else []),
            ]
        )
        admission = payload.get("admission") or {}
        status = str(admission.get("status") or "")
        if status == "UNSUPPORTED":
            codes = tuple(str(c) for c in (admission.get("reason_codes") or [])) or ("ADMISSION_UNSUPPORTED",)
            record(
                "draft",
                expect_admission_rejection,
                codes=codes,
                detail="; ".join(str(b) for b in (admission.get("blockers") or [])),
                started=started,
                extra={"admission_status": status},
            )
            if expect_admission_rejection:
                return finish(ok=True, status="EXPECTED_REJECTION", stop="draft", codes=codes)
            return finish(ok=False, status="ADMISSION_REJECTED", stop="draft", codes=codes)
        if payload.get("draft_error") or not payload.get("ok", False):
            codes = _codes(payload, "DRAFT_FAILED")
            error = str(payload.get("draft_error") or payload.get("error") or "")
            if error and not payload.get("reason_codes"):
                codes = (error.split(":")[-1][:96] or "DRAFT_FAILED",)
            record(
                "draft",
                False,
                codes=codes,
                detail=error,
                started=started,
                extra={
                    "admission_status": status,
                    "validation_errors": list(payload.get("draft_error_diagnostics") or []),
                },
            )
            return finish(ok=False, status="DRAFT_FAILED", stop="draft", codes=codes)
        selfcheck = payload.get("draft_selfcheck") or {}
        selfcheck_ok = bool(selfcheck.get("ok", False))
        try:
            draft = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8")) or {}
            facts["tool_name"] = str((draft.get("tool") or {}).get("name") or "") or None
            profile = str(((draft.get("_delivery_profile") or {}).get("profile_id")) or "")
        except (OSError, yaml.YAMLError):
            profile = ""
        codes = tuple(str(c) for c in (selfcheck.get("final_reason_codes") or []))
        record(
            "draft",
            selfcheck_ok,
            codes=codes,
            detail=str(selfcheck.get("recommended_action") or ""),
            started=started,
            extra={
                "admission_status": status,
                "self_check_status": str(selfcheck.get("status") or ""),
                "self_check_rounds": int(selfcheck.get("rounds") or 0),
                "profile": profile,
            },
        )
        if not selfcheck_ok:
            return finish(
                ok=False, status="DRAFT_SELF_CHECK_FAILED", stop="draft", codes=codes or ("DRAFT_SELF_CHECK_FAILED",)
            )
        if profile != "workspace_bundle_v1":
            record(
                "confirm_examples",
                False,
                codes=("AUTOPILOT_PROFILE_UNSUPPORTED",),
                started=time.monotonic(),
                detail=f"autopilot v1 drives workspace_bundle_v1 only; draft profile is {profile or 'unknown'}",
            )
            return finish(
                ok=False,
                status="AUTOPILOT_PROFILE_UNSUPPORTED",
                stop="confirm_examples",
                codes=("AUTOPILOT_PROFILE_UNSUPPORTED",),
            )
        if stop_after("draft"):
            return finish(ok=True, status="PAUSED_AT_DRAFT", stop=None, codes=())

        # ---- confirm examples (machine gate, provenance recorded) ----
        started = time.monotonic()
        try:
            candidates = json.loads((draft_dir / "workspace_fixture_candidates.json").read_text(encoding="utf-8"))
            records = list(candidates.get("records") or [])
        except (OSError, ValueError):
            records = []
        confirmed = 0
        failures: list[str] = []
        for row in records:
            outcome = product_jobs.confirm_workspace_fixture_candidate(
                draft_dir, candidate_token=str(row.get("candidate_token") or "")
            )
            if outcome.get("ok"):
                confirmed += 1
            else:
                failures.append(str(outcome.get("error") or "CONFIRM_FAILED")[:120])
        atomic_write_json(
            draft_dir / "autopilot.json",
            {
                "schema_version": 1,
                "journey_id": journey.journey_id,
                "examples_confirmed_by": "autopilot",
                "examples_confirmed": confirmed,
                "confirmed_at": _now(),
            },
        )
        ok = confirmed >= 3
        record(
            "confirm_examples",
            ok,
            codes=() if ok else ("EXAMPLES_INSUFFICIENT",),
            detail="; ".join(failures),
            started=started,
            extra={"confirmed": confirmed, "candidates": len(records)},
        )
        if not ok:
            return finish(
                ok=False, status="EXAMPLES_INSUFFICIENT", stop="confirm_examples", codes=("EXAMPLES_INSUFFICIENT",)
            )
        if stop_after("confirm_examples"):
            return finish(ok=True, status="PAUSED_AT_CONFIRM_EXAMPLES", stop=None, codes=())

        # ---- confirm intent (machine gate, provenance recorded) ----
        started = time.monotonic()
        outcome = product_jobs.confirm_draft_intent(draft_dir)
        codes = tuple(str(c) for c in (outcome.get("reason_codes") or [])) or (
            () if outcome.get("ok") else ("INTENT_CONFIRM_FAILED",)
        )
        record(
            "confirm_intent",
            bool(outcome.get("ok")),
            codes=codes,
            detail=str(outcome.get("error") or ""),
            started=started,
        )
        if not outcome.get("ok"):
            return finish(ok=False, status="INTENT_CONFIRM_FAILED", stop="confirm_intent", codes=codes)
        if stop_after("confirm_intent"):
            return finish(ok=True, status="PAUSED_AT_CONFIRM_INTENT", stop=None, codes=())

        # ---- freeze wheelhouse into the draft (preregistered bytes before any Agent) ----
        started = time.monotonic()
        outcome = product_jobs.freeze_draft_wheelhouse(draft_dir)
        codes = tuple(str(c) for c in (outcome.get("reason_codes") or [])) or (
            () if outcome.get("ok") else ("WHEELHOUSE_FREEZE_FAILED",)
        )
        record(
            "freeze_wheelhouse",
            bool(outcome.get("ok")),
            codes=codes,
            detail=str(outcome.get("error") or ""),
            started=started,
            extra={"wheels": int(outcome.get("wheels") or 0), "root": str(outcome.get("root") or "")[:16] or None},
        )
        if not outcome.get("ok"):
            return finish(ok=False, status="WHEELHOUSE_FREEZE_FAILED", stop="freeze_wheelhouse", codes=codes)
        if stop_after("freeze_wheelhouse"):
            return finish(ok=True, status="PAUSED_AT_FREEZE_WHEELHOUSE", stop=None, codes=())

        # ---- rehearsal (freeze + zero-model positive control) ----
        started = time.monotonic()
        payload = run_stage(
            "rehearsal",
            [
                "tool",
                "build",
                "--draft-dir",
                str(draft_dir),
                "--dest-root",
                str(dest_root),
                "--rehearsal-only",
                "--agent-backend",
                agent_backend,
                "--batch",
                batch,
            ]
        )
        task_id = str(payload.get("task_id") or "") or None
        facts["task_id"] = task_id
        if task_id:
            update_journey(journey.journey_id, task_id=task_id)
        ok = payload.get("verdict") == "REHEARSAL_PASS_ONLY"
        rehearsal = (payload.get("stages") or {}).get("rehearsal") or {}
        failed_stage, sub_codes, sub_detail, sub_owner = _failed_substage(payload)
        codes = () if ok else (sub_codes or _codes(rehearsal, *(_codes(payload, "REHEARSAL_FAILED"))))
        record(
            "rehearsal",
            ok,
            codes=codes,
            detail=sub_detail or str(rehearsal.get("recommended_action") or payload.get("error") or ""),
            started=started,
            extra={
                "verdict": str(payload.get("verdict") or ""),
                "task_id": task_id,
                "failure_owner": (
                    str(rehearsal.get("failure_owner") or sub_owner or payload.get("failure_owner") or "") or None
                ),
                "failed_stage": failed_stage,
            },
        )
        if not ok:
            return finish(ok=False, status="REHEARSAL_FAILED", stop="rehearsal", codes=codes)
        if stop_after("rehearsal"):
            return finish(ok=True, status="PAUSED_AT_REHEARSAL", stop=None, codes=())
    else:
        task_id = resume_task_id
        update_journey(journey.journey_id, task_id=task_id)

    # ---- real build (one Agent run with the pipeline's own bounded repair) ----
    started = time.monotonic()
    payload = run_stage(
        "real_build",
        [
            "tool",
            "build-real",
            "--task-id",
            str(task_id),
            "--dest-root",
            str(dest_root),
            "--batch",
            batch,
            "--agent-backend",
            agent_backend,
        ]
    )
    exported = str(payload.get("exported") or "")
    tool_name = facts["tool_name"] or (Path(exported).name if exported else None)
    facts["tool_name"] = tool_name
    if tool_name:
        update_journey(journey.journey_id, tool_name=tool_name)
    ok = payload.get("verdict") == "VERIFIED_TOOL_READY" and bool(exported)
    real = (payload.get("stages") or {}).get("real") or {}
    failed_stage, sub_codes, sub_detail, sub_owner = _failed_substage(payload)
    codes = () if ok else (_codes(real) or sub_codes or _codes(payload, "REAL_BUILD_FAILED"))
    record(
        "real_build",
        ok,
        codes=codes,
        detail=str(real.get("recommended_action") or sub_detail or payload.get("error") or ""),
        started=started,
        extra={
            "verdict": str(payload.get("verdict") or ""),
            "run_id": str(real.get("run_id") or "") or None,
            "exported": exported or None,
            "failure_owner": str(real.get("failure_owner") or sub_owner or payload.get("failure_owner") or "") or None,
            "failed_stage": failed_stage,
        },
    )
    if not ok:
        return finish(ok=False, status="REAL_BUILD_FAILED", stop="real_build", codes=codes)
    if stop_after("real_build"):
        return finish(ok=True, status="PAUSED_AT_REAL_BUILD", stop=None, codes=())

    # ---- fresh audit (model proposes, frozen builder/reference materialise, Core audits) ----
    started = time.monotonic()
    proposal = product_jobs.propose_audit_candidates(
        str(tool_name), dest_root=dest_root, expected_task_id=str(task_id), n=2, offline=False
    )
    candidates = list(proposal.get("candidates") or []) if proposal.get("ok") else []
    if not candidates:
        codes = _codes(proposal, "FRESH_AUDIT_CANDIDATES_UNAVAILABLE")
        record(
            "fresh_audit",
            False,
            codes=codes,
            detail=str(proposal.get("error") or ""),
            started=started,
            extra={"rejected_proposals": len(proposal.get("rejected_proposals") or [])},
        )
        return finish(ok=False, status="FRESH_AUDIT_FAILED", stop="fresh_audit", codes=codes)
    materialized = product_jobs.materialize_workspace_audit_candidate(
        str(tool_name),
        dest_root=dest_root,
        expected_task_id=str(task_id),
        candidate_token=str(candidates[0].get("candidate_token") or ""),
    )
    if not materialized.get("ok"):
        codes = _codes(materialized, "FRESH_AUDIT_MATERIALIZE_FAILED")
        record("fresh_audit", False, codes=codes, detail=str(materialized.get("error") or ""), started=started)
        return finish(ok=False, status="FRESH_AUDIT_FAILED", stop="fresh_audit", codes=codes)
    payload = run_stage(
        "fresh_audit",
        [
            "tool",
            "audit",
            str(tool_name),
            "--input",
            str(materialized["input"]),
            "--expected-file",
            str(materialized["expected"]),
            "--expected-task-id",
            str(task_id),
            "--dest-root",
            str(dest_root),
            "--project-root",
            str(project_root),
            "--build",
        ]
    )
    # The audit CLI reports one singular ``reason_code`` (FRESH_INPUT_PASS or
    # FRESH_INPUT_SEMANTIC_PASS when the decision is ACTIVE); a ``reason_codes``
    # list never existed on this payload, and looking only there wrote every
    # passing audit down as FRESH_AUDIT_FAILED while the tool was ACTIVE on disk
    # (incident-autopilot-misreads-fresh-audit-pass-*).
    audit_reason = str(payload.get("reason_code") or "")
    if not audit_reason:
        listed = [str(item) for item in (payload.get("reason_codes") or []) if str(item)]
        audit_reason = listed[0] if listed else ""
    ok = bool(payload.get("ok")) and audit_reason in FRESH_AUDIT_PASS_REASONS
    codes = () if ok else ((audit_reason,) if audit_reason else _codes(payload, "FRESH_AUDIT_FAILED"))
    record(
        "fresh_audit",
        ok,
        codes=codes,
        detail=str(payload.get("error") or ""),
        started=started,
        extra={
            "blueprint_id": str(candidates[0].get("blueprint_id") or ""),
            "artifact_tree_sha256": str(payload.get("artifact_tree_sha256") or "")[:16] or None,
            "semantic_verifier_passed": bool(payload.get("semantic_verifier_passed")),
        },
    )
    if not ok:
        return finish(ok=False, status="FRESH_AUDIT_FAILED", stop="fresh_audit", codes=codes)
    if stop_after("fresh_audit"):
        return finish(ok=True, status="PAUSED_AT_FRESH_AUDIT", stop=None, codes=())

    # ---- final: recompute from registry + ledger, never from stage payloads ----
    started = time.monotonic()
    from repoproof.ui.services.product_mode import list_tools

    entry: dict = next(
        (t for t in list_tools(dest_root).get("tools") or [] if t.get("name") == tool_name),
        {},
    )
    active = bool(entry) and entry.get("operational_status") == "ACTIVE" and entry.get("health") == "OK"
    record(
        "final",
        active,
        codes=() if active else ("REGISTRY_NOT_ACTIVE",),
        started=started,
        extra={
            "operational_status": str((entry or {}).get("operational_status") or ""),
            "health": str((entry or {}).get("health") or ""),
            "historical_verdict": str((entry or {}).get("historical_verdict") or ""),
        },
    )
    if not active:
        return finish(ok=False, status="REGISTRY_NOT_ACTIVE", stop="final", codes=("REGISTRY_NOT_ACTIVE",))
    return finish(ok=True, status="ACTIVE", stop=None, codes=())
