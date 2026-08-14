"""公开测试 —— agent 可见,用来自检。

**它存在的理由**:B8(2026-08-15 可搬运性审查)。原先 `public_tests/` 是空的,
于是 agent 三轮零反馈,而失败记录与"模型公开面全挂"逐字段同型 —— 台账里已经
有真实模型的同签名行,混进去之后没人分得开。

它**只验形状,不验采纳**:采纳要回执,而回执在 harness 侧。公开面能教的是
"接口长什么样、开关叫什么、工件写到哪",那三样正是 R8–R10 刚补进契约的。
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

API = "/api/page-facts"
HOST = Path(os.environ.get("OFFERCLAW_HOST_ROOT", ".")).resolve()


def _app(monkeypatch):
    monkeypatch.setenv("OFFERCLAW_PAGE_FACTS", "1")
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "page_facts"))]:
        sys.modules.pop(m, None)
    return importlib.import_module("rag_api").app


def test_flag_off_registers_no_routes(monkeypatch):
    """R9:开关未启用时不注册路由。"""
    monkeypatch.delenv("OFFERCLAW_PAGE_FACTS", raising=False)
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "page_facts"))]:
        sys.modules.pop(m, None)
    app = importlib.import_module("rag_api").app
    assert API not in {r.path for r in app.routes}


def test_flag_on_registers_both_routes(monkeypatch):
    """R10:两个端点都要在。"""
    paths = {r.path for r in _app(monkeypatch).routes}
    assert API in paths
    assert any(p.startswith(API + "/") for p in paths), "缺 GET /api/page-facts/{job_id}"


def test_empty_items_is_rejected(monkeypatch):
    """空 items 不该被当成一个合法作业。"""
    with TestClient(_app(monkeypatch)) as c:
        assert c.post(API, json={"items": []}).status_code >= 400


def test_submit_returns_job_id_and_status_is_queryable(monkeypatch):
    """R10:提交拿 job_id,查询拿 state。

    用一个**不可达**的地址:这里只验形状,不验能不能真渲染 —— 那要 sidecar,
    而公开面不该依赖它是否可用(依赖了就会在 harness 侧出问题时误报被测方)。
    """
    with TestClient(_app(monkeypatch)) as c:
        r = c.post(API, json={"items": [
            {"url": "http://127.0.0.1:1/unreachable", "request_nonce": "public-1"}]})
        assert r.status_code == 200, r.text
        jid = r.json()["job_id"]
        st = c.get(f"{API}/{jid}").json()
        assert "state" in st and st["state"] in {"queued", "running", "done", "failed"}


def test_unknown_job_id_is_404(monkeypatch):
    with TestClient(_app(monkeypatch)) as c:
        assert c.get(f"{API}/no-such-job").status_code == 404


@pytest.mark.parametrize("key", ["job_id", "facts"])
def test_artifact_schema_is_documented(key):
    """R8:工件 schema 的形状说明 —— 这条测试本身就是**规格的一部分**。

    它不检查你写没写(那时候还没跑过作业),只把 harness 会去读的那两个顶层键
    钉在公开面上,免得"写在别处或换键名"这件事只有 harness 知道。
    """
    assert key in {"job_id", "facts"}
    _ = json.dumps({"job_id": "x", "facts": [{"request_nonce": "n", "facts": "s"}]})
