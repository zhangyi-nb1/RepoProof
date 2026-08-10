"""T2 公开验收(agent 可见可自测)。

覆盖公开需求的可公开部分;隐藏验收另有更严格的并发/取消竞态/重启/
密钥出口/KB 污染用例。约定:Feature Flag `OFFERCLAW_DEEP_RESEARCH=1`
开启;作业 API 挂在 `/api/research`。测试全程离线:Fake LLM 由
`fixtures/fake_llm_server.py` 提供,搜索走上游自带的 `search_api=none`。
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))
from fake_llm_server import start as start_fake_llm  # noqa: E402

FLAG = "OFFERCLAW_DEEP_RESEARCH"
API = "/api/research"
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
# 会话 nonce:**每轮修复都会重跑本套件**,而作业子系统有幂等/去重策略
# ——沿用同一主题会让第二轮的"创建"直接返回上一轮的终态作业,用例随
# 之误挂。每个会话用新主题;去重策略由专门用例在内部重复提交来验证。
NONCE = uuid.uuid4().hex[:8]
TOPIC = f"研究合成公司 ACME-Synthetic-{NONCE} 的岗位速览"


@pytest.fixture(scope="module")
def fake_llm():
    srv, port = start_fake_llm()
    yield f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


def _load_app(monkeypatch, fake_base: str | None, flag: str | None = "1"):
    if flag is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, flag)
    if fake_base:
        monkeypatch.setenv("OPENAI_BASE_URL", fake_base)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-not-a-real-key")
        monkeypatch.setenv("GET_API_KEYS_FROM_CONFIG", "false")
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "research_jobs"))]:
        sys.modules.pop(m, None)
    return importlib.import_module("rag_api").app


def _wait(client, job_id: str, timeout_s: float = 90.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = client.get(f"{API}/{job_id}").json()
        if st.get("state") in TERMINAL:
            return st
        time.sleep(0.3)
    raise AssertionError(f"作业 {job_id} 在 {timeout_s}s 内未进入终态")


def test_flag_off_by_default_no_research_api(monkeypatch) -> None:
    """默认关闭:作业接口不存在,现有行为零变化。"""
    app = _load_app(monkeypatch, None, flag=None)
    with TestClient(app) as c:
        assert c.post(API, json={"input_text": TOPIC}).status_code in (404, 405)


def test_create_is_non_blocking_and_returns_job_id(monkeypatch, fake_llm) -> None:
    """创建请求必须快速返回 job_id,不等待完整研究结束。"""
    app = _load_app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        t0 = time.time()
        r = c.post(API, json={"input_text": TOPIC})
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("job_id")
        # 结构判据(不依赖时序:测试模式下整段研究可能只要 1 秒,时间阈值
        # 抓不到阻塞实现)——创建响应必须是**未完成态**
        assert body.get("state") not in TERMINAL, (
            f"创建即返回终态 {body.get('state')}:请求同步等待了整段研究")
        assert elapsed < 10, f"创建请求耗时 {elapsed:.1f}s,疑似同步阻塞到研究结束"
        st = _wait(c, body["job_id"])
        assert st["state"] == "succeeded", st.get("failure_reason", "")


def test_status_lifecycle_and_result_fields(monkeypatch, fake_llm) -> None:
    """状态机 + 结果必须含报告/引用来源/研究问题/时间/ID。"""
    app = _load_app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": TOPIC}).json()["job_id"]
        st = _wait(c, jid)
    assert st["state"] == "succeeded"
    assert st["report"].strip(), "缺最终报告"
    assert st["source_urls"], "缺引用来源"
    assert st["research_brief"].strip(), "缺研究问题/简报"
    assert st["created_at"] and st["finished_at"]
    assert st["job_id"] == jid


def test_cancel_moves_job_out_of_running(monkeypatch, fake_llm) -> None:
    """用户可取消未完成任务;取消后状态明确且为终态。"""
    app = _load_app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": TOPIC + " 取消用例"}).json()["job_id"]
        c.post(f"{API}/{jid}/cancel")
        st = _wait(c, jid, timeout_s=60)
    assert st["state"] in TERMINAL
    assert st["state"] != "running"


def test_duplicate_submission_has_explicit_policy(monkeypatch, fake_llm) -> None:
    """相同输入+相同配置重复提交必须有明确的幂等/去重策略。"""
    app = _load_app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        a = c.post(API, json={"input_text": TOPIC + " 幂等"}).json()
        _wait(c, a["job_id"])
        b = c.post(API, json={"input_text": TOPIC + " 幂等"}).json()
    assert b.get("duplicate") is True or b["job_id"] == a["job_id"], (
        "重复提交既未复用也未标记,缺少去重策略")


def test_failure_is_persisted_with_reason(monkeypatch, fake_llm) -> None:
    """失败任务必须保存明确 failure 状态和原因(不静默丢失)。"""
    app = _load_app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": TOPIC + " 失败用例",
                                "model": "openai:fake",
                                "search_api": "bogus-search-api"}).json()["job_id"]
        st = _wait(c, jid, timeout_s=60)
    assert st["state"] in ("failed", "interrupted"), st["state"]
    assert st["failure_reason"].strip(), "失败必须带原因"


def test_no_promote_means_no_kb_contamination(monkeypatch, fake_llm) -> None:
    """未确认 Promote 前,知识库不得出现**本作业**的内容。

    判据按作业范围(不是"KB 里一条 research_report 都不能有"):同一环境
    先前合法 Promote 过的内容不应让本用例误挂。"""
    app = _load_app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": TOPIC + " 不入库"}).json()["job_id"]
        _wait(c, jid)
        assert jid not in _kb_research_ids(), "未 Promote 却已污染知识库"


def test_promote_writes_isolated_source_type(monkeypatch, fake_llm) -> None:
    """Promote 后必须以独立 source_type=research_report 入库并带溯源。"""
    app = _load_app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": TOPIC + " 入库"}).json()["job_id"]
        _wait(c, jid)
        r = c.post(f"{API}/{jid}/promote")
        assert r.status_code == 200, r.text
        assert r.json().get("source_type") == "research_report"
    assert jid in _kb_research_ids(), "Promote 后 KB 未见该作业内容"


@pytest.mark.parametrize("route", ["/health", "/openapi.json"])
def test_existing_routes_still_work(monkeypatch, fake_llm, route: str) -> None:
    """开启新能力后既有路由与 OpenAPI 仍正常(宿主回归)。"""
    app = _load_app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        assert c.get(route).status_code == 200


# ------------------------------------------------------------------ 辅助
def _kb_research_ids() -> set[str]:
    """当前 collection 中 source_type=research_report 的 job_id 集合。"""
    import chromadb
    from rag_tools import get_collection_name

    host = Path(os.environ.get("OFFERCLAW_HOST_ROOT", Path.cwd()))
    client = chromadb.PersistentClient(path=str(host / "chroma_db"))
    try:
        col = client.get_collection(get_collection_name())
    except Exception:  # noqa: BLE001 — 集合不存在即视为无污染
        return set()
    got = col.get(include=["metadatas"], limit=10000)
    out = set()
    for m in got.get("metadatas") or []:
        if (m or {}).get("source_type") == "research_report":
            out.add(str((m or {}).get("research_job_id", "")))
    return out


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "research_jobs"))]:
        sys.modules.pop(m, None)
