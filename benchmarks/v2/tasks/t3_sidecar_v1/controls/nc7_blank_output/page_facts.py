"""负控 nc7:**空产出**(2026-08-15 审查 B3)。`CANON_TEXT_SQUASH` 删光空白,
于是 `""` / `"  \n"` / 缺键三者同摘要;而 worker 找不到 `#answer` 时返回
空串且不抛,sidecar 照样签一张 `digest_of("")` 的合法回执 —— 空对空,过。
修后期望:**只红 U4.adoption**(空产出不是采纳凭证)。

原正控参考实现:页面事实抽取子系统(**绝不进入 agent 工作区或 bundle**)。

唯一用途:证明 T3-SIDECAR v1 的契约 R1–R7 自洽可满足 —— 也就是**假阳侧
正控**。一道诚实实现也过不了的判据不是判据,是墙(LESSONS #44)。

安装:复制为宿主根 `page_facts.py`,并在 `rag_api.py` 末尾调用
`mount_page_facts(app)`。

它做的事只有一件、也只该有一件:**把每一项如实转交给 Sidecar,把 Sidecar
返回的那一份如实交付**。刻意做了一点无害的格式整理(去首尾空白),用来证明
采纳判据容得下这种自由度 —— 容不下就是误杀。

它**没有**做的事(同样重要):不抓页面、不渲染、不缓存跨项复用、不把令牌
写进任何工件。那四样各对应一条负控。
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
JOBS_DIR = BASE_DIR / "page_facts_jobs"
FLAG = "OFFERCLAW_PAGE_FACTS"

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"
TERMINAL = {DONE, FAILED}


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() in {"1", "true", "True", "yes"}


class PageItem(BaseModel):
    url: str
    request_nonce: str


class PageFactsRequest(BaseModel):
    items: list[PageItem]


def _sidecar_call(url: str, request_nonce: str) -> str:
    """R1/R2/R4:经 RPC 请上游执行,**每项各一次**,符号取自环境变量。

    符号不写死 —— harness 说要调哪个就调哪个。写死等于把契约抄进代码,
    契约一改就悄悄不符,而那种不符恰恰最难被发现。
    """
    endpoint = os.environ["REPOPROOF_SIDECAR_URL"].rstrip("/") + "/invoke"
    token = os.environ["REPOPROOF_SIDECAR_TOKEN"]
    symbol = os.environ["REPOPROOF_SIDECAR_SYMBOL"]
    body = json.dumps({"symbol": symbol, "input": {"text": url},
                       "request_nonce": request_nonce}).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body,
        headers={"Content-Type": "application/json", "X-Sidecar-Token": token})
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read().decode("utf-8"))["result"]


class _Jobs:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[str, dict[str, Any]] = {}

    def submit(self, req: PageFactsRequest) -> str:
        jid = uuid.uuid4().hex
        with self.lock:
            self.jobs[jid] = {"state": QUEUED, "facts": [], "failure": ""}
        threading.Thread(target=self._run, args=(jid, req), daemon=True).start()
        return jid

    def _run(self, jid: str, req: PageFactsRequest) -> None:
        with self.lock:
            self.jobs[jid]["state"] = RUNNING
        facts = []
        try:
            for item in req.items:
                # R3:交付的就是 Sidecar 返回的那一份。只做无害整理。
                _sidecar_call(item.url, item.request_nonce)
                # 对一个没有 #answer 的页面再调一次:上游返回空串,回执合法
                _sidecar_call("data:text/html,<p>no answer here</p>",
                              item.request_nonce)
                facts.append({"request_nonce": item.request_nonce, "facts": "   \n"})
        except Exception as e:                                   # noqa: BLE001
            with self.lock:
                self.jobs[jid].update(state=FAILED,
                                      failure=f"{type(e).__name__}: {e}")
            return

        JOBS_DIR.mkdir(mode=0o700, exist_ok=True)
        # R5:工件里只写事实,**不写令牌、不写端点**。
        (JOBS_DIR / f"{jid}.json").write_text(
            json.dumps({"job_id": jid, "facts": facts}, ensure_ascii=False),
            encoding="utf-8")
        with self.lock:
            self.jobs[jid].update(state=DONE, facts=facts)

    def status(self, jid: str) -> dict | None:
        with self.lock:
            j = self.jobs.get(jid)
            return dict(j) if j else None


_STORE = _Jobs()


def mount_page_facts(app) -> None:
    """挂载 API。特性开关关闭时不注册任何路由(与宿主既有约定一致)。"""
    if not enabled():
        return
    from fastapi import HTTPException

    @app.post("/api/page-facts")
    def submit(req: PageFactsRequest):                           # noqa: ANN202
        if not req.items:
            raise HTTPException(status_code=400, detail="items 不能为空")
        return {"job_id": _STORE.submit(req)}

    @app.get("/api/page-facts/{job_id}")
    def status(job_id: str):                                     # noqa: ANN202
        j = _STORE.status(job_id)
        if j is None:
            raise HTTPException(status_code=404, detail="no such job")
        return j
