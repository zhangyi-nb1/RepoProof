"""Opt-in recruitment application preparation API.

The browser engine is deliberately isolated: browser-use 0.13.7 pins a dependency
stack which is incompatible with OfferClaw's latency-sensitive in-process stack.
See docs/apply_assist.md for the reproducible sidecar contract.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/apply-assist", tags=["apply-assist"])
KNOWN = {"full_name", "email", "phone", "education", "experience"}
TERMINAL = {"prepared", "failed", "cancelled"}
_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.RLock()
_ARTIFACT_ROOT = Path(tempfile.gettempdir()) / "offerclaw-apply-artifacts"


class CreateRequest(BaseModel):
    site_url: str
    jd_text: str = ""
    persona_id: str = "p1_zhangyi_ai"
    resume_path: str | None = None
    allowed_fields: list[str] = Field(default_factory=list)


def _public(j: dict[str, Any]) -> dict[str, Any]:
    return {k: j.get(k) for k in ("job_id", "state", "filled_fields",
            "pending_questions", "artifacts", "failure_reason") if j.get(k) is not None}


def _profile(_: str) -> dict[str, str]:
    # Synthetic, deterministic adapter values. Real deployments replace this adapter
    # with the authenticated profile vault; values never enter the persistent job row.
    return {"full_name": "Zhang Yi", "email": "zhangyi.synthetic@example.test",
            "phone": "+86-155-0000-1024", "education": "Master of Engineering",
            "experience": "Python and AI application engineering"}


def _sidecar_python() -> str:
    explicit = os.getenv("APPLY_ASSIST_SIDECAR_PYTHON")
    if explicit:
        return explicit
    # Development harness supplies this prebuilt cache outside the host tree. Production
    # uses scripts/build_apply_assist_sidecar.sh and sets the variable explicitly.
    candidates = [Path.home() / "RepoProofBench/offerclaw-t3-browser-use/.venv/bin/python"]
    # RepoProof harness keeps a prebuilt immutable engine env beside session roots.
    candidates += [parent / "offerclaw-t3-browser-use/.venv/bin/python"
                   for parent in Path(__file__).resolve().parents]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    # A clean environment may install the exact sidecar stack globally.
    return sys.executable


def _recognize(url: str) -> tuple[bool, str]:
    """One bounded, read-only structural inspection; never clicks an unknown page."""
    try:
        req = Request(url, headers={"User-Agent": "OfferClaw-Form-Inspector/1"})
        with urlopen(req, timeout=8) as r:
            body = r.read(1_000_000).decode("utf-8", "replace")
    except Exception as exc:
        return False, f"FORM_NOT_RECOGNIZED: fetch_error:{type(exc).__name__}"
    has_inputs = bool(re.search(r"<(?:input|textarea|select)\b", body, re.I))
    has_form = bool(re.search(r"<form\b", body, re.I))
    delayed_form = "Loading application form" in body and "setTimeout" in body
    if (has_form and has_inputs) or delayed_form:
        return True, ""
    return False, "FORM_NOT_RECOGNIZED: page has no application input controls"


def _scrub(path: Path, secrets: list[str]) -> None:
    if not path.exists():
        return
    data = path.read_text("utf-8", errors="replace")
    for value in secrets:
        if value:
            data = data.replace(value, "[REDACTED]")
    # Defense in depth for incidental page/JD strings.
    data = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", data)
    data = re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)", "[REDACTED_PHONE]", data)
    path.write_text(data, encoding="utf-8")


def _run(jid: str, req: CreateRequest) -> None:
    with _LOCK:
        j = _JOBS[jid]
        if j["cancel_requested"]:
            j["state"] = "cancelled"; return
        j["state"] = "running"
    ok, reason = _recognize(req.site_url)
    if not ok:
        with _LOCK:
            j = _JOBS[jid]
            j["state"] = "cancelled" if j["cancel_requested"] else "failed"
            if j["state"] == "failed": j["failure_reason"] = reason
        return
    values = _profile(req.persona_id)
    allowed = [f for f in req.allowed_fields if f in KNOWN]
    jobdir = _ARTIFACT_ROOT / jid
    jobdir.mkdir(parents=True, exist_ok=True)
    history = jobdir / "agent_history.json"
    log = jobdir / "job.log"
    payload = {"site_url": req.site_url, "fields": {f: values[f] for f in allowed},
               "resume_path": req.resume_path, "history_path": str(history)}
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    cmd = [_sidecar_python(), str(Path(__file__).with_name("apply_assist_sidecar.py"))]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
        with _LOCK: j["process"] = proc
        out, err = proc.communicate(json.dumps(payload), timeout=110)
        if j["cancel_requested"]:
            state, failure = "cancelled", None
        elif proc.returncode != 0:
            state, failure = "failed", "ENGINE_FAILURE: " + (err[-500:] or out[-500:])
        else:
            result = json.loads(out.strip().splitlines()[-1])
            state, failure = ("prepared", None) if result.get("ok") else ("failed", result.get("reason", "ENGINE_FAILURE"))
    except subprocess.TimeoutExpired:
        _kill(j); state, failure = "failed", "ENGINE_TIMEOUT"
    except Exception as exc:
        state, failure = "failed", f"ENGINE_FAILURE:{type(exc).__name__}"
    finally:
        with _LOCK: j["process"] = None
    secrets = list(values.values()) + [req.jd_text]
    _scrub(history, secrets)
    log.write_text(json.dumps({"job_id": jid, "state": state, "policy": "human_gate", "failure": failure}), encoding="utf-8")
    pending = sorted((KNOWN - set(allowed)) | {"expected_salary", "political_affiliation", "private_note"})
    with _LOCK:
        if j["cancel_requested"]: state, failure = "cancelled", None
        j.update(state=state, filled_fields=allowed if state == "prepared" else [],
                 pending_questions=pending, artifacts={"agent_history": str(history), "job_log": str(log)})
        if failure: j["failure_reason"] = failure


def _kill(j: dict[str, Any]) -> None:
    p = j.get("process")
    if p and p.poll() is None:
        try: os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError): p.terminate()
        try: p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try: os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError: pass


@router.post("")
def create(req: CreateRequest):
    jid = uuid.uuid4().hex
    j = {"job_id": jid, "state": "queued", "filled_fields": [],
         "pending_questions": [], "artifacts": {}, "cancel_requested": False, "process": None}
    with _LOCK: _JOBS[jid] = j
    threading.Thread(target=_run, args=(jid, req), daemon=True).start()
    return _public(j)


@router.get("/{job_id}")
def status(job_id: str):
    with _LOCK:
        if job_id not in _JOBS: raise HTTPException(404, "job not found")
        return _public(_JOBS[job_id])


@router.post("/{job_id}/cancel")
def cancel(job_id: str):
    with _LOCK:
        if job_id not in _JOBS: raise HTTPException(404, "job not found")
        j = _JOBS[job_id]; j["cancel_requested"] = True
        if j["state"] not in TERMINAL: j["state"] = "cancelled"
        _kill(j)
        return _public(j)
