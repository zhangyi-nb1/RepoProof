"""Recoverable Product Studio journey navigation.

Journey files are UI navigation state, never verification or release facts.
All verdicts and current operational status remain owned by RepoProof Core.
"""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from repoproof.execution.core_execution import atomic_write_json
from repoproof.ui.services.product_mode import ui_state_root

JOURNEY_SCHEMA_VERSION = 1
MAX_JOURNEY_BYTES = 64 * 1024
_ID_RE = re.compile(r"[0-9a-f]{32}")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ProductJourneyRefV1(BaseModel):
    """Mutable UI pointer set; deliberately contains no verdict or status."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    journey_id: str = Field(min_length=32, max_length=32)
    tool_name: str = Field(default="", max_length=128)
    source_repo_url: str = Field(default="", max_length=2048)
    draft_dir: str = Field(default="", max_length=4096)
    task_id: str | None = Field(default=None, max_length=256)
    dest_root: str = Field(default="", max_length=4096)
    last_job_id: str | None = Field(default=None, max_length=128)
    agent_backend: Literal["codex-cli", "mini-swe"] = "mini-swe"
    created_at: str = Field(default_factory=_utc_now)
    updated_at: str = Field(default_factory=_utc_now)


def journeys_root() -> Path:
    return ui_state_root() / "journeys"


def _path_for(journey_id: str) -> Path:
    if _ID_RE.fullmatch(str(journey_id)) is None:
        raise ValueError("journey_id 必须是 32 位小写十六进制标识")
    return journeys_root() / f"{journey_id}.json"


def _safe_read(path: Path) -> dict:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("journey 记录不是普通文件")
        if opened.st_size > MAX_JOURNEY_BYTES:
            raise OSError("journey 记录过大")
        with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
            value = json.load(stream)
    finally:
        os.close(fd)
    if not isinstance(value, dict):
        raise ValueError("journey 记录根节点必须是 object")
    return value


def write_journey(journey: ProductJourneyRefV1) -> ProductJourneyRefV1:
    path = _path_for(journey.journey_id)
    root = path.parent
    if root.exists() and (not root.is_dir() or root.is_symlink()):
        raise OSError(f"journey 目录不安全：{root}")
    atomic_write_json(path, journey.model_dump(mode="json"))
    return journey


def create_journey(
    *,
    source_repo_url: str,
    draft_dir: Path,
    dest_root: Path,
    tool_name: str = "",
    agent_backend: Literal["codex-cli", "mini-swe"] = "mini-swe",
    journey_id: str | None = None,
) -> ProductJourneyRefV1:
    now = _utc_now()
    journey = ProductJourneyRefV1(
        journey_id=journey_id or uuid.uuid4().hex,
        tool_name=tool_name,
        source_repo_url=source_repo_url.strip(),
        draft_dir=str(Path(draft_dir).expanduser()),
        dest_root=str(Path(dest_root).expanduser()),
        agent_backend=agent_backend,
        created_at=now,
        updated_at=now,
    )
    return write_journey(journey)


def read_journey(journey_id: str) -> ProductJourneyRefV1:
    path = _path_for(journey_id)
    try:
        return ProductJourneyRefV1.model_validate(_safe_read(path))
    except ValidationError as exc:
        raise ValueError(f"journey 记录无效：{exc}") from exc


def update_journey(journey_id: str, **changes: object) -> ProductJourneyRefV1:
    current = read_journey(journey_id)
    forbidden = {"schema_version", "journey_id", "created_at"}.intersection(changes)
    if forbidden:
        raise ValueError(f"journey 不可改写字段：{', '.join(sorted(forbidden))}")
    payload = current.model_dump()
    payload.update(changes)
    payload["updated_at"] = _utc_now()
    return write_journey(ProductJourneyRefV1.model_validate(payload))


def list_journeys() -> list[ProductJourneyRefV1]:
    root = journeys_root()
    if not root.exists():
        return []
    if not root.is_dir() or root.is_symlink():
        raise OSError(f"journey 目录不安全：{root}")
    rows: list[ProductJourneyRefV1] = []
    for path in root.glob("*.json"):
        if path.is_symlink():
            continue
        try:
            rows.append(ProductJourneyRefV1.model_validate(_safe_read(path)))
        except (OSError, ValueError, ValidationError, json.JSONDecodeError):
            continue
    return sorted(rows, key=lambda row: row.updated_at, reverse=True)


def journey_snapshot(journey: ProductJourneyRefV1) -> dict:
    """Compute the current phase from Core facts without persisting verdicts."""

    from repoproof.execution.product_action import read_product_action_result
    from repoproof.ui.services import product_jobs, product_mode

    worker = product_jobs.product_job_state()
    if not worker or worker.get("job_id") != journey.last_job_id:
        worker = None
    action_result = None
    semantic_error = None
    if journey.last_job_id:
        result_path = ui_state_root() / "job-results" / f"{journey.last_job_id}.json"
        try:
            parsed = read_product_action_result(result_path)
        except FileNotFoundError:
            parsed = None
            if not (worker and worker.get("status") == "RUNNING"):
                semantic_error = "ACTION_RESULT_MISSING"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parsed = None
            semantic_error = f"ACTION_RESULT_INVALID: {exc}"
        if parsed is not None:
            if parsed.job_id != journey.last_job_id or (
                parsed.journey_id and parsed.journey_id != journey.journey_id
            ):
                semantic_error = "ACTION_RESULT_JOB_MISMATCH"
            else:
                action_result = parsed.model_dump(mode="json")

    task_id = journey.task_id or str((action_result or {}).get("task_id") or "") or None
    tool_name = journey.tool_name or str((action_result or {}).get("tool_name") or "")
    draft_review = None
    draft_readiness: dict = {}
    if journey.draft_dir:
        draft_review = product_jobs.read_managed_draft_review(Path(journey.draft_dir))
        if draft_review.get("ok"):
            draft_readiness = draft_review.get("draft_readiness") or {}
            tool_name = tool_name or str(
                ((draft_review.get("draft") or {}).get("tool") or {}).get("name") or ""
            )

    library = product_mode.list_tools(Path(journey.dest_root))
    # A tool name spans task versions.  Matching a new, still-unfrozen
    # Journey by name would leak an older package's ACTIVE/REVOKED state into
    # the new draft and skip contract review entirely.  Only the frozen task
    # identity may join navigation state to Core release facts.
    tool_row = next(
        (
            row
            for row in library.get("tools", [])
            if task_id and row.get("task_id") == task_id
        ),
        None,
    )
    if library.get("registry_error") or library.get("release_error"):
        semantic_error = semantic_error or "CORE_STATUS_UNAVAILABLE"

    contract_exists = bool(
        task_id
        and (product_mode.project_root() / "contracts" / f"{task_id}.yaml").is_file()
    )
    running = bool(worker and worker.get("status") == "RUNNING")
    operational = str((tool_row or {}).get("operational_status") or "UNVERIFIED")
    if semantic_error:
        phase = "SEMANTIC_UNKNOWN"
    elif running:
        phase = "RUNNING"
    elif operational == "ACTIVE":
        phase = "ACTIVE"
    elif tool_row is not None:
        phase = "EXPORTED"
    elif action_result is not None and not action_result.get("ok"):
        phase = "FAILED"
    elif (action_result or {}).get("pipeline_verdict") == "REHEARSAL_PASS_ONLY":
        phase = "REHEARSED"
    elif contract_exists:
        phase = "FROZEN"
    elif (
        draft_review
        and draft_review.get("ok")
        and (
            not draft_readiness.get("compatible")
            or not draft_readiness.get("current")
        )
    ):
        phase = "DRAFT_INCOMPATIBLE"
    elif draft_review and draft_review.get("ok"):
        phase = "DRAFT"
    else:
        phase = "NEW"
    return {
        "journey": journey.model_dump(mode="json"),
        "phase": phase,
        "worker": worker,
        "action_result": action_result,
        "semantic_error": semantic_error,
        "task_id": task_id,
        "tool_name": tool_name,
        "draft_review": draft_review,
        "tool": tool_row,
        "library_errors": library.get("projection_errors") or [],
        "historical_verdict": (tool_row or {}).get("historical_verdict"),
        "operational_status": operational,
        "package_health": (tool_row or {}).get("health") or "NOT_EXPORTED",
    }


def new_task_version_seed(snapshot: dict) -> dict[str, object]:
    """Seed an editable new version from facts already admitted by Core.

    This is navigation convenience, not a verdict copy.  The old goal and
    source pin remain visible for explicit human confirmation.  Delivery
    requirements are reused only when the old intent contract records Core's
    ``SUPPORTED`` admission, preventing a second model pass from silently
    changing file-vs-directory, offline, browser, or side-effect boundaries.
    """

    journey = snapshot.get("journey") if isinstance(snapshot, dict) else None
    journey = journey if isinstance(journey, dict) else {}
    review = snapshot.get("draft_review") if isinstance(snapshot, dict) else None
    review = review if isinstance(review, dict) and review.get("ok") else {}
    draft = review.get("draft")
    draft = draft if isinstance(draft, dict) else {}
    source_repo = draft.get("source_repo")
    source_repo = source_repo if isinstance(source_repo, dict) else {}
    intent = draft.get("_intent_contract")
    intent = intent if isinstance(intent, dict) else {}
    delivery = intent.get("delivery")
    delivery = delivery if isinstance(delivery, dict) else {}
    raw_requirements = delivery.get("requirements")
    admitted_requirements = (
        deepcopy(raw_requirements)
        if delivery.get("support_status") == "SUPPORTED"
        and isinstance(raw_requirements, dict)
        else None
    )
    revision = str(
        source_repo.get("resolved_commit") or source_repo.get("revision") or ""
    ).strip()
    return {
        "source_repo_url": str(
            source_repo.get("url") or journey.get("source_repo_url") or ""
        ).strip(),
        "revision": revision,
        "capability": str(intent.get("user_goal") or "").strip(),
        "agent_backend": str(journey.get("agent_backend") or "mini-swe"),
        "authoritative_delivery_requirements": admitted_requirements,
    }


def synthesized_read_only_cards() -> list[dict]:
    """Expose pre-Journey frozen/exported facts without backfilling files."""

    from repoproof.ui.services import product_jobs, product_mode

    cards: list[dict] = []
    seen: set[str] = set()
    for row in product_mode.list_tools().get("tools", []):
        task_id = str(row.get("task_id") or "")
        cards.append({
            "read_only": True,
            "task_id": task_id,
            "tool_name": row.get("name"),
            "phase": "ACTIVE" if row.get("operational_status") == "ACTIVE" else "EXPORTED",
            "historical_verdict": row.get("historical_verdict"),
            "operational_status": row.get("operational_status"),
        })
        seen.add(task_id)
    for row in product_jobs.list_rehearsed_tasks():
        task_id = str(row.get("task_id") or "")
        if task_id and task_id not in seen:
            cards.append({
                "read_only": True,
                "task_id": task_id,
                "tool_name": "",
                "phase": "REHEARSED",
                "historical_verdict": row.get("verdict"),
                "operational_status": "UNVERIFIED",
            })
    return cards
