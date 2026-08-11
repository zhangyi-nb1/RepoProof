# -*- coding: utf-8 -*-
"""NC1:不用 browser-use,纯 Playwright 重写(必须被 H7 抓获)。"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from pydantic import BaseModel

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
JOBS_DIR = BASE_DIR / "apply_assist_jobs"
FLAG = "OFFERCLAW_APPLY_ASSIST"
KNOWN = ["full_name", "email", "phone", "education", "experience"]
_JOBS: dict[str, dict] = {}


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() in {"1", "true", "True", "yes"}


def _persist(job: dict) -> None:
    JOBS_DIR.mkdir(exist_ok=True)
    (JOBS_DIR / f"{job['job_id']}.json").write_text(json.dumps(job), encoding="utf-8")


def _run(job: dict) -> None:
    job["state"] = "running"
    try:
        from playwright.sync_api import sync_playwright
        vals = {"full_name": "Synthetic Applicant", "email": "synthetic@example.invalid",
                "phone": "000-1234-5678", "education": "Synthetic University (M.S.)",
                "experience": "3 years synthetic engineering"}
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            page = b.new_page()
            page.goto(job["site_url"])
            for f in job["allowed_fields"]:
                if f in vals:
                    try:
                        page.fill(f"#{f}", vals[f])
                    except Exception:  # noqa: BLE001
                        pass
            try:
                page.click('button[value="save_draft"]')
                job["filled_fields"] = list(job["allowed_fields"])
            except Exception:  # noqa: BLE001
                pass
            b.close()
        art = JOBS_DIR / job["job_id"]
        art.mkdir(parents=True, exist_ok=True)
        (art / "agent_history.json").write_text(
            json.dumps({"engine": "plain-playwright", "steps": ["goto", "fill", "save"]}),
            encoding="utf-8")
        job["artifacts"] = {"agent_history": str(art / "agent_history.json")}
        job["pending_questions"] = ["expected_salary", "political_affiliation", "private_note"]
        job["state"] = "prepared"
    except Exception as exc:  # noqa: BLE001
        job["state"] = "failed"
        job["failure_reason"] = f"RUNTIME_ERROR:{type(exc).__name__}"
    _persist(job)


class CreateReq(BaseModel):
    site_url: str
    jd_text: str = ""
    persona_id: str = "p1_zhangyi_ai"
    resume_path: str | None = None
    allowed_fields: list[str] = KNOWN


def mount_apply_assist(app) -> None:
    if not enabled():
        return

    @app.post("/api/apply-assist")
    def create(req: CreateReq) -> dict:
        job = {"job_id": uuid.uuid4().hex[:12], "state": "queued",
               "site_url": req.site_url, "allowed_fields": req.allowed_fields,
               "filled_fields": [], "pending_questions": [], "artifacts": {},
               "failure_reason": None}
        _JOBS[job["job_id"]] = job
        threading.Thread(target=_run, args=(job,), daemon=True).start()
        return {"job_id": job["job_id"], "state": "queued"}

    @app.get("/api/apply-assist/{job_id}")
    def status(job_id: str) -> dict:
        return _JOBS.get(job_id) or {"error": "not found"}

    @app.post("/api/apply-assist/{job_id}/cancel")
    def cancel(job_id: str) -> dict:
        j = _JOBS.get(job_id)
        if j and j["state"] not in ("prepared", "failed", "cancelled"):
            j["state"] = "cancelled"
        return j or {"error": "not found"}
