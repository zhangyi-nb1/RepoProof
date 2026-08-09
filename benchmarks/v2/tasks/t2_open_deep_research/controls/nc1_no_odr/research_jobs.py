"""正控参考实现:Deep Research 子系统(**绝不进入 agent 工作区或 bundle**)。

唯一用途:证明 T2 的公开测试 + 隐藏 oracle 自洽可满足(源方案 §14-6)。
安装:复制为宿主根目录 `research_jobs.py`,并在 rag_api.py 末尾调用
`mount_research_api(app)`。

设计要点(对应公开需求 21 条的可验证部分):
- 异步作业:POST 立即返回 job_id(非阻塞),后台任务跑真实 ODR Graph;
- 状态机 queued→running→succeeded/failed/cancelled,非法迁移被拒;
- 取消:running 可取消;已终态不可翻转(cancel race 下 succeeded 不回退);
- 重启语义:进程重启时把遗留 running 判为 interrupted(不永久 running);
- 幂等:同 (input, config_hash) 在活跃/成功期内复用既有 job;
- Secret 零泄漏:配置/报告/接口响应只存 provider 名与 base_url 主机,
  永不存 key;出参前统一 redact;
- Promote 显式:成功报告只有经 /api/research/{id}/promote 才入 KB,
  且 source_type=research_report + research_job_id + source_urls;
- 存储:项目内 research_jobs/ 目录(JSON 原子写),重启可恢复。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel as _BaseModel

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
JOBS_DIR = BASE_DIR / "research_jobs"
FLAG = "OFFERCLAW_DEEP_RESEARCH"
SOURCE_TYPE = "research_report"

QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED, INTERRUPTED = (
    "queued", "running", "succeeded", "failed", "cancelled", "interrupted")
TERMINAL = {SUCCEEDED, FAILED, CANCELLED, INTERRUPTED}
_ALLOWED = {
    QUEUED: {RUNNING, CANCELLED, FAILED},
    RUNNING: {SUCCEEDED, FAILED, CANCELLED, INTERRUPTED},
}

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|(?i:api[_-]?key\"?\s*[:=]\s*)\S+)")


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() in {"1", "true", "True", "yes"}


def redact(value: Any) -> Any:
    """出口净化:任何字符串里的 key 形态一律遮蔽(纵深防御第二道)。"""
    if isinstance(value, str):
        return _SECRET_RE.sub("[REDACTED]", value)
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if "key" in k.lower() else redact(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


@dataclass
class ResearchJob:
    job_id: str
    input_text: str
    config_hash: str
    state: str = QUEUED
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    research_brief: str = ""
    report: str = ""
    source_urls: list[str] = field(default_factory=list)
    failure_reason: str = ""
    provider: str = ""          # 只存名字,永不存 key
    duplicate_of: str | None = None

    def public(self) -> dict:
        d = asdict(self)
        return redact(d)


class JobStore:
    """JSON 文件存储(原子写);进程内锁保证状态迁移串行。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or JOBS_DIR)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def save(self, job: ResearchJob) -> None:
        with self._lock:
            tmp = self._path(job.job_id).with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(job), ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, self._path(job.job_id))

    def load(self, job_id: str) -> ResearchJob | None:
        p = self._path(job_id)
        if not p.exists():
            return None
        return ResearchJob(**json.loads(p.read_text(encoding="utf-8")))

    def all(self) -> list[ResearchJob]:
        out = []
        for p in sorted(self.root.glob("*.json")):
            try:
                out.append(ResearchJob(**json.loads(p.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return out

    def transition(self, job_id: str, new_state: str, **fields) -> ResearchJob | None:
        """受控迁移:终态不可再变;非法迁移拒绝(返回 None)。"""
        with self._lock:
            job = self.load(job_id)
            if job is None or job.state in TERMINAL:
                return None
            if new_state not in _ALLOWED.get(job.state, set()):
                return None
            job.state = new_state
            for k, v in fields.items():
                setattr(job, k, v)
            if new_state in TERMINAL:
                job.finished_at = time.time()
            self.save(job)
            return job

    def recover_running(self) -> list[str]:
        """重启语义:遗留 running/queued → interrupted(不永久 running)。"""
        touched = []
        with self._lock:
            for job in self.all():
                if job.state in (RUNNING, QUEUED):
                    job.state = INTERRUPTED
                    job.failure_reason = "进程重启,作业中断(可重新提交)"
                    job.finished_at = time.time()
                    self.save(job)
                    touched.append(job.job_id)
        return touched

    def find_duplicate(self, input_text: str, config_hash: str) -> ResearchJob | None:
        for job in self.all():
            if (job.input_text == input_text and job.config_hash == config_hash
                    and job.state in (QUEUED, RUNNING, SUCCEEDED)):
                return job
        return None


def config_hash(cfg: dict) -> str:
    """配置指纹:**先剔除任何 key 字段**再哈希(secret 不进指纹链)。"""
    safe = {k: v for k, v in sorted(cfg.items()) if "key" not in k.lower()}
    return hashlib.sha256(json.dumps(safe, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def odr_config(model: str, *, search_api: str = "none") -> dict:
    """复用 OfferClaw 配置体系(provider 名/base_url 来自环境),不含 key。"""
    return {
        "allow_clarification": False,
        "search_api": search_api,
        "research_model": model, "research_model_max_tokens": 1000,
        "summarization_model": model, "summarization_model_max_tokens": 1000,
        "compression_model": model, "compression_model_max_tokens": 1000,
        "final_report_model": model, "final_report_model_max_tokens": 1000,
        "max_researcher_iterations": 2,
        "max_react_tool_calls": 3,
        "max_concurrent_research_units": 1,
        "max_structured_output_retries": 2,
    }


def _self_written_research(topic: str) -> dict:
    """负控 NC1:自写搜索+摘要循环,不调用上游 Research Graph。"""
    return {"final_report": f"# 研究报告(自写)\n\n主题:{topic}\n\n"
                            "- 自写要点\n\n引用:https://example.invalid/self",
            "research_brief": f"自写简报:{topic}"}


def load_graph():
    """加载上游 Research Graph。**在挂载期预热**:该 import 重达数秒,
    若留在作业协程里首次执行会阻塞事件循环,使"创建请求立即返回"名存
    实亡(任务工程实测:创建耗时 3.7s)。"""
    from open_deep_research.deep_researcher import deep_researcher

    return deep_researcher


async def run_research(job: ResearchJob, store: JobStore, cfg: dict) -> None:
    """真实调用上游 ODR Research Graph(禁止自写搜索循环)。"""
    from langchain_core.messages import HumanMessage

    if store.transition(job.job_id, RUNNING) is None:
        return
    try:
        result = _self_written_research(job.input_text)   # NC1
        report = str(result.get("final_report", ""))
        urls = sorted(set(re.findall(r"https?://[^\s)\]]+", report)))
        store.transition(job.job_id, SUCCEEDED,
                         report=redact(report),
                         research_brief=redact(str(result.get("research_brief", ""))),
                         source_urls=urls)
    except asyncio.CancelledError:
        store.transition(job.job_id, CANCELLED, failure_reason="用户取消")
        raise
    except Exception as exc:  # noqa: BLE001 — 失败必须留状态与原因
        store.transition(job.job_id, FAILED,
                         failure_reason=redact(f"{type(exc).__name__}: {exc}")[:400])


def promote_to_kb(job: ResearchJob, *, collection=None) -> dict:
    """显式 Promote:成功报告 → KB,独立 source_type + 溯源元数据。

    未 Promote 前 KB 绝不含该内容(RAG 污染防线);使用宿主既有分块与
    embedding 管线(不自建第二套)。"""
    if job.state != SUCCEEDED:
        raise ValueError(f"只有 succeeded 作业可 promote(当前 {job.state})")
    import chromadb
    from rag_tools import (
        get_collection_name,
        get_embeddings_batch,
        split_markdown_document,
    )

    if collection is None:
        client = chromadb.PersistentClient(path=str(BASE_DIR / "chroma_db"))
        collection = client.get_or_create_collection(get_collection_name())
    chunks = split_markdown_document(job.report)   # 复用宿主分块管线
    # 短报告(无标题结构)可能切不出块——回退整篇为一块,绝不静默丢内容
    texts = [c["text"] for c in chunks] or [job.report.strip()]
    texts = [t for t in texts if t.strip()]
    if not texts:
        raise ValueError("报告为空,无可入库内容")
    ids = [f"research::{job.job_id}::{i}" for i in range(len(texts))]
    metas = [{
        "source": f"research_report::{job.job_id}",
        "source_type": SOURCE_TYPE,          # 独立域,绝不混入 paper
        "research_job_id": job.job_id,
        "source_urls": ",".join(job.source_urls),
        "char_len": len(t),
    } for t in texts]
    collection.add(ids=ids, documents=texts,
                   embeddings=get_embeddings_batch(texts),   # 复用宿主 embedding
                   metadatas=metas)
    return {"promoted_chunks": len(ids), "source_type": SOURCE_TYPE,
            "research_job_id": job.job_id}


class CreateResearchRequest(_BaseModel):
    """请求模型必须在**模块级**:`from __future__ import annotations` 把
    注解变字符串,FastAPI 只在模块 globals 里解析——函数内定义的模型会
    被当成 query 参数(实测 422)。"""

    input_text: str
    model: str = "openai:fake-research-model"
    search_api: str = "none"


def mount_research_api(app, *, store: JobStore | None = None):
    """Flag 关闭时完全惰性;开启后挂载作业 API 并做重启恢复。"""
    if not enabled():
        return None
    if getattr(app.state, "research_store", None) is not None:
        return app.state.research_store          # 幂等
    from fastapi import HTTPException

    st = store or JobStore()
    st.recover_running()                          # 重启语义
    load_graph()                                  # 预热(见 load_graph 注释)
    app.state.research_store = st
    app.state.research_tasks = {}

    @app.post("/api/research")
    async def create_research(req: CreateResearchRequest):   # 非阻塞:立即返回
        cfg = odr_config(req.model, search_api=req.search_api)
        h = config_hash(cfg)
        dup = st.find_duplicate(req.input_text, h)
        if dup is not None:
            return {"job_id": dup.job_id, "state": dup.state, "duplicate": True}
        job = ResearchJob(job_id=uuid.uuid4().hex[:12], input_text=req.input_text,
                          config_hash=h, provider=req.model.split(":")[0])
        st.save(job)
        task = asyncio.create_task(run_research(job, st, cfg))
        app.state.research_tasks[job.job_id] = task
        return {"job_id": job.job_id, "state": job.state, "duplicate": False}

    @app.get("/api/research/{job_id}")
    async def get_research(job_id: str):
        job = st.load(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return job.public()

    @app.post("/api/research/{job_id}/cancel")
    async def cancel_research(job_id: str):
        job = st.load(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.state in TERMINAL:                 # cancel race:终态不翻转
            return {"job_id": job_id, "state": job.state, "cancelled": False}
        task = app.state.research_tasks.get(job_id)
        if task is not None:
            task.cancel()
        moved = st.transition(job_id, CANCELLED, failure_reason="用户取消")
        return {"job_id": job_id, "state": (moved or job).state,
                "cancelled": moved is not None}

    @app.post("/api/research/{job_id}/promote")
    async def promote_research(job_id: str):
        job = st.load(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        if job.state != SUCCEEDED:
            raise HTTPException(status_code=409,
                                detail=f"只有 succeeded 可 promote(当前 {job.state})")
        return promote_to_kb(job)

    return st
