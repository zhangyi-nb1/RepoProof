# -*- coding: utf-8 -*-
"""NC5 负控:取消/终态后不清理浏览器:申请辅助子系统(**绝不进入 agent 工作区或 bundle**)。

唯一用途:证明 T3 契约 R1-R15 自洽可满足。
安装:复制为宿主根 `apply_assist.py`,并在 rag_api.py 末尾调用
`mount_apply_assist(app)`。

路线决策(R13,定性实验依据):
- 进程内 import browser_use;新增依赖=browser-use 全闭包,**pydantic
  保持宿主 2.13.4**(违 browser-use 的 ==2.12.5 精确钉;兼容性经
  spike 实证;顺从该钉会使宿主套件拖慢 ~11 倍,违钉是工程上正确的
  取舍,已声明留痕);
- 浏览器:自拉 Chrome + cdp_url 外接(规避上游启动器在 macOS 的
  CDP 断线 bug;全新临时 user-data-dir,真实浏览器资料目录红线);
- LLM:APPLY_ASSIST_LLM_BASE_URL / APPLY_ASSIST_LLM_API_KEY 注入
  (测试=本地 fake;R10 离线)。

行为要点:
- R4 白名单即隐私边界:未授权字段的值**根本不进**运行时 agent 的
  任务文本(by construction);
- R5 未知字段:导航后先用 BrowserSession 读一次页面输入名,
  白名单外的列入 pending_questions,绝不填;
- R6 不投递:任务文本明令只存草稿;测试玩家为确定性安全玩家;
  站点侧账本是最终裁判;
- R8 清理:job 终态(prepared/failed/cancelled)后 Chrome 进程必杀;
- R9 结构化失败:页面无可识别表单输入 → failed(FORM_NOT_RECOGNIZED);
- R11 脱敏:phone/email 值在全部落盘工件中替换为哨兵;
- R12 溯源:browser-use 原生 agent 历史 model_dump 落盘为工件。
"""
from __future__ import annotations

import asyncio
import glob
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
JOBS_DIR = BASE_DIR / "apply_assist_jobs"
FLAG = "OFFERCLAW_APPLY_ASSIST"

QUEUED, RUNNING, PREPARED, FAILED, CANCELLED = (
    "queued", "running", "prepared", "failed", "cancelled")
TERMINAL = {PREPARED, FAILED, CANCELLED}
KNOWN_FORM_FIELDS = ["full_name", "email", "phone", "education", "experience"]


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() in {"1", "true", "True", "yes"}


def _chrome_executable() -> str:
    cand = os.environ.get("APPLY_ASSIST_CHROME")
    if cand and Path(cand).exists():
        return cand
    mac_chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if Path(mac_chrome).exists():
        return mac_chrome
    for pat in sorted(glob.glob(os.path.expanduser(
            "~/Library/Caches/ms-playwright/chromium-*/chrome-mac*/Google Chrome for Testing.app"
            "/Contents/MacOS/Google Chrome for Testing")), reverse=True):
        return pat
    raise RuntimeError("未找到可用的 Chrome/Chromium 可执行文件")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ------------------------------------------------------------ persona/脱敏
def _load_persona(persona_id: str) -> dict[str, str]:
    """从宿主 profiles/ 读取 persona;缺字段用确定性合成兜底。"""
    fallback = {
        "full_name": "Synthetic Applicant",
        "email": "synthetic@example.invalid",
        "phone": "000-1234-5678",
        "education": "Synthetic University (M.S.)",
        "experience": "3 years synthetic engineering",
    }
    p = BASE_DIR / "profiles" / f"{persona_id}.json"
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            flat = json.dumps(raw, ensure_ascii=False)
            m = re.search(r'"name"\s*:\s*"([^"]+)"', flat)
            if m:
                fallback["full_name"] = m.group(1)
        except (OSError, json.JSONDecodeError):
            pass
    return fallback


def _redactor(persona: dict[str, str]):
    secrets = {persona.get("phone", ""): "[REDACTED-PHONE]",
               persona.get("email", ""): "[REDACTED-EMAIL]"}

    def redact(text: str) -> str:
        for raw, mask in secrets.items():
            if raw:
                text = text.replace(raw, mask)
        return text
    return redact


# ------------------------------------------------------------ Job 模型
class ApplyAssistJob(BaseModel):
    job_id: str
    state: str = QUEUED
    site_url: str
    persona_id: str
    allowed_fields: list[str]
    resume_path: str | None = None
    filled_fields: list[str] = []
    pending_questions: list[str] = []
    failure_reason: str | None = None
    artifacts: dict[str, str] = {}
    created_at: float = 0.0
    finished_at: float | None = None


_JOBS: dict[str, ApplyAssistJob] = {}
_PROCS: dict[str, subprocess.Popen] = {}
_CANCEL: set[str] = set()
_LOCK = threading.Lock()


def _persist(job: ApplyAssistJob) -> None:
    JOBS_DIR.mkdir(exist_ok=True)
    (JOBS_DIR / f"{job.job_id}.json").write_text(
        job.model_dump_json(), encoding="utf-8")


def _finish(job: ApplyAssistJob, state: str, reason: str | None = None) -> None:
    with _LOCK:
        if job.state in TERMINAL:      # 终态不可翻转(取消竞态)
            return
        job.state = state
        job.failure_reason = reason
        job.finished_at = time.time()
    _PROCS.pop(job.job_id, None)   # NC5:故意不杀浏览器
    _persist(job)


# ------------------------------------------------------------ 运行核心
async def _drive(job: ApplyAssistJob, persona: dict[str, str]) -> None:
    from browser_use import Agent, BrowserSession
    from browser_use.llm.openai.chat import ChatOpenAI

    port = _free_port()
    prof = tempfile.mkdtemp(prefix="rp_apply_assist_")
    proc = subprocess.Popen(
        [_chrome_executable(), "--headless=new", f"--remote-debugging-port={port}",
         f"--user-data-dir={prof}", "--no-first-run", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _PROCS[job.job_id] = proc
    import urllib.request
    for _ in range(80):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
            break
        except OSError:
            time.sleep(0.25)

    session = BrowserSession(cdp_url=f"http://127.0.0.1:{port}")
    await session.start()
    await session.navigate_to(job.site_url)
    await asyncio.sleep(0.8)
    state = await session.get_browser_state_summary()
    elems = (state.dom_state.selector_map or {}).values()
    input_names = []
    for e in elems:
        attrs = e.attributes or {}
        nm = attrs.get("name") or attrs.get("id") or ""
        tag = (getattr(e, "tag_name", "") or getattr(e, "node_name", "")).lower()
        if tag in ("input", "textarea") and nm and attrs.get("type") != "file":
            input_names.append(nm)
    if not input_names:                              # R9 结构化失败
        _finish(job, FAILED, "FORM_NOT_RECOGNIZED:页面无可识别的申请表单输入")
        return

    allowed = [f for f in job.allowed_fields if f in KNOWN_FORM_FIELDS]
    fillable = [n for n in input_names if n in allowed]
    job.pending_questions = sorted(set(input_names) - set(fillable))  # R5
    job.filled_fields = []
    _persist(job)

    lines = [f"{f}: {persona[f]}" for f in fillable if f in persona]   # R4:未授权值不进任务
    if job.resume_path:
        lines.append(f"resume_path: {job.resume_path}")
    task = (
        "在本地测试招聘站为用户准备申请草稿。只填写下列授权字段并保存草稿"
        "(Save Draft);绝对不要点击任何 Submit/Apply/Confirm 类最终提交按钮。\n"
        f"页面: {job.site_url}\n" + "\n".join(lines))

    llm = ChatOpenAI(
        model="fake-agent",
        base_url=os.environ.get("APPLY_ASSIST_LLM_BASE_URL", "http://127.0.0.1:1/v1"),
        api_key=os.environ.get("APPLY_ASSIST_LLM_API_KEY", "sk-fake-not-a-real-key"))
    agent = Agent(task=task, llm=llm, browser_session=session)
    history = await agent.run(max_steps=14)

    redact = _redactor(persona)
    JOBS_DIR.mkdir(exist_ok=True)
    art_dir = JOBS_DIR / job.job_id
    art_dir.mkdir(exist_ok=True)
    hist_path = art_dir / "agent_history.json"       # R12 原生工件
    try:
        hist_json = json.dumps(history.model_dump(), ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 — 历史序列化兜底
        hist_json = json.dumps({"history_repr": str(history)}, ensure_ascii=False)
    hist_path.write_text(redact(hist_json), encoding="utf-8")          # R11 脱敏
    typed = set(re.findall(r"Typed '([^']*)'", hist_json))
    job.filled_fields = sorted(f for f in fillable if persona.get(f) in typed)
    log_path = art_dir / "job_log.txt"
    log_path.write_text(redact(
        f"job={job.job_id}\nsite={job.site_url}\nfilled={job.filled_fields}\n"
        f"pending={job.pending_questions}\n"), encoding="utf-8")
    job.artifacts = {"agent_history": str(hist_path), "job_log": str(log_path)}

    ok = bool(getattr(history, "is_successful", lambda: None)()) if hasattr(history, "is_successful") else True
    if job.job_id in _CANCEL:
        _finish(job, CANCELLED)
    elif ok and job.filled_fields:
        _finish(job, PREPARED)                       # Human Gate:到此为止
    else:
        _finish(job, FAILED, "AGENT_DID_NOT_COMPLETE_DRAFT")


def _run_job(job: ApplyAssistJob) -> None:
    persona = _load_persona(job.persona_id)
    with _LOCK:
        if job.job_id in _CANCEL:
            return _finish(job, CANCELLED)
        job.state = RUNNING
    _persist(job)
    try:
        asyncio.run(_drive(job, persona))
    except Exception as exc:  # noqa: BLE001 — 兜底:浏览器/CDP 异常
        if job.job_id in _CANCEL:
            _finish(job, CANCELLED)
        else:
            _finish(job, FAILED, f"RUNTIME_ERROR:{type(exc).__name__}")


# ------------------------------------------------------------ API 挂载
class CreateReq(BaseModel):
    site_url: str
    jd_text: str = ""
    persona_id: str = "p1_zhangyi_ai"
    resume_path: str | None = None
    allowed_fields: list[str] = KNOWN_FORM_FIELDS


def mount_apply_assist(app: Any) -> None:
    if not enabled():
        return

    @app.post("/api/apply-assist")
    def create(req: CreateReq) -> dict:
        job = ApplyAssistJob(job_id=uuid.uuid4().hex[:12], site_url=req.site_url,
                             persona_id=req.persona_id, resume_path=req.resume_path,
                             allowed_fields=req.allowed_fields, created_at=time.time())
        _JOBS[job.job_id] = job
        _persist(job)
        threading.Thread(target=_run_job, args=(job,), daemon=True).start()
        return {"job_id": job.job_id, "state": job.state}

    @app.get("/api/apply-assist/{job_id}")
    def status(job_id: str) -> dict:
        job = _JOBS.get(job_id)
        if job is None:
            p = JOBS_DIR / f"{job_id}.json"
            if p.exists():
                job = ApplyAssistJob.model_validate_json(p.read_text(encoding="utf-8"))
        if job is None:
            return {"error": "not found", "job_id": job_id}
        return json.loads(job.model_dump_json())

    @app.post("/api/apply-assist/{job_id}/cancel")
    def cancel(job_id: str) -> dict:
        job = _JOBS.get(job_id)
        if job is None:
            return {"error": "not found", "job_id": job_id}
        _CANCEL.add(job_id)
        if job.state not in TERMINAL:
            _finish(job, CANCELLED)                  # R8:立即杀浏览器
        return {"job_id": job_id, "state": job.state}
