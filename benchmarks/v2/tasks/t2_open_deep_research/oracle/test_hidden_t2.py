"""T2 隐藏验收(harness 持有,**绝不进入 agent 工作区或环境**)。

源方案 §10 H1-H10。比公开测试严格:结构性 provenance(不看字符串)、
并发不串、取消竞态、重启不永久 running、密钥出口全域扫描、KB 污染
与域隔离、宿主回归。
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import uuid
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _find_host() -> Path:
    env = os.environ.get("OFFERCLAW_HOST_ROOT")
    if env and (Path(env) / "rag_api.py").exists():
        return Path(env).resolve()
    cwd = Path.cwd().resolve()
    for cand in (cwd, *cwd.parents):
        if (cand / "rag_api.py").exists():
            return cand
    raise AssertionError("找不到宿主根(rag_api.py)")


HOST = _find_host()
sys.path.insert(0, str(HOST))
for _p in (HOST / "public_tests", HOST / "fixtures"):
    if _p.is_dir():
        sys.path.insert(0, str(_p))

# 会话 nonce:隐藏 oracle 必须自带状态隔离——宿主的**幂等策略**会让
# 重复主题直接复用旧作业(任务工程实测:H1 因此观察不到图调用而误判
# "重写了搜索循环")。每次 oracle 会话用新主题,判定不受历史残留影响;
# H3 在用例内部自行重复提交来验证去重。
NONCE = uuid.uuid4().hex[:8]
FLAG = "OFFERCLAW_DEEP_RESEARCH"
API = "/api/research"
TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}
REAL_KEY_SENTINEL = "sk-hidden-oracle-sentinel-4f2a9c"


@pytest.fixture(scope="module")
def fake_llm():
    from fake_llm_server import start

    srv, port = start()
    yield f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


def _app(monkeypatch, fake_base: str, key: str = "sk-fake-not-a-real-key"):
    monkeypatch.setenv(FLAG, "1")
    monkeypatch.setenv("OPENAI_BASE_URL", fake_base)
    monkeypatch.setenv("OPENAI_API_KEY", key)
    monkeypatch.setenv("GET_API_KEYS_FROM_CONFIG", "false")
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "research_jobs"))]:
        sys.modules.pop(m, None)
    return importlib.import_module("rag_api").app


def _wait(c, jid: str, timeout_s: float = 90.0) -> dict:
    end = time.time() + timeout_s
    while time.time() < end:
        st = c.get(f"{API}/{jid}").json()
        if st.get("state") in TERMINAL:
            return st
        time.sleep(0.25)
    raise AssertionError(f"作业 {jid} 未在 {timeout_s}s 内终结")


def _kb_rows() -> list[dict]:
    import chromadb
    from rag_tools import get_collection_name

    client = chromadb.PersistentClient(path=str(HOST / "chroma_db"))
    try:
        col = client.get_collection(get_collection_name())
    except Exception:  # noqa: BLE001
        return []
    got = col.get(include=["metadatas", "documents"], limit=10000)
    metas = got.get("metadatas") or []
    docs = got.get("documents") or []
    return [{"meta": m or {}, "doc": d or ""} for m, d in zip(metas, docs)]


# ------------------------------------------------------------ H1 Provenance
def test_h1_real_odr_graph_is_invoked(monkeypatch, fake_llm) -> None:
    """UPSTREAM_CAPABILITY_REIMPLEMENTED:必须真实调用 ODR Research
    Graph——对上游图对象的 ainvoke 打桩计数,自写搜索循环无法伪造。"""
    import open_deep_research.deep_researcher as odr

    calls: list[str] = []
    graph_cls = type(odr.deep_researcher)   # 必须打**类**:该对象是 pydantic
    # 模型,实例 setattr 会落进 extra 而方法仍走类查找(实测无声失效)
    for name in ("ainvoke", "astream", "invoke", "stream"):
        original = getattr(graph_cls, name, None)
        if original is None:
            continue

        def make_spy(fn, label):
            def spy(self, *a, **kw):
                calls.append(label)
                return fn(self, *a, **kw)
            return spy

        monkeypatch.setattr(graph_cls, name, make_spy(original, name))
    app = _app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": f"H1 结构性 provenance 用例 {NONCE}"}).json()["job_id"]
        st = _wait(c, jid)
    assert st["state"] == "succeeded", st.get("failure_reason", "")
    assert calls, "未观察到上游 Research Graph 调用——疑似自行重写搜索/摘要流程"


# ------------------------------------------------------------ H2 并发不串
def test_h2_concurrent_jobs_do_not_cross(monkeypatch, fake_llm) -> None:
    app = _app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        a = c.post(API, json={"input_text": f"并发用例 ALPHA-X1-{NONCE} 的岗位速览"}).json()["job_id"]
        b = c.post(API, json={"input_text": f"并发用例 BETA-Y2-{NONCE} 的岗位速览"}).json()["job_id"]
        sa, sb = _wait(c, a), _wait(c, b)
    assert a != b, "并发任务复用了同一 job_id"
    assert sa["state"] == "succeeded" and sb["state"] == "succeeded"
    assert f"ALPHA-X1-{NONCE}" in sa["report"] and f"BETA-Y2-{NONCE}" not in sa["report"], "A 结果被污染"
    assert f"BETA-Y2-{NONCE}" in sb["report"] and f"ALPHA-X1-{NONCE}" not in sb["report"], "B 结果被污染"


# ------------------------------------------------------------ H3 重复提交
def test_h3_duplicate_submit_follows_frozen_policy(monkeypatch, fake_llm) -> None:
    """冻结策略 = 复用既有作业(不得静默产出两份重复研究)。"""
    app = _app(monkeypatch, fake_llm)
    topic = f"H3 幂等用例 GAMMA-Z3 {NONCE}"
    with TestClient(app) as c:
        first = c.post(API, json={"input_text": topic}).json()
        _wait(c, first["job_id"])
        second = c.post(API, json={"input_text": topic}).json()
    assert second["job_id"] == first["job_id"] or second.get("duplicate") is True, (
        "DUPLICATE_JOB:相同输入+配置重复提交既未复用也未标记")


# ------------------------------------------------------------ H4 取消竞态
def test_h4_cancel_race_never_yields_double_terminal(monkeypatch, fake_llm) -> None:
    """边界取消:终态唯一,不得同时 cancelled+succeeded;终态不可翻转。"""
    app = _app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": f"H4 取消竞态用例 {NONCE}"}).json()["job_id"]
        st = _wait(c, jid)                       # 先跑到终态
        before = st["state"]
        c.post(f"{API}/{jid}/cancel")            # 终态后再取消
        after = c.get(f"{API}/{jid}").json()
    assert before in TERMINAL
    assert after["state"] == before, (
        f"CANCELLATION_FAILURE:终态 {before} 被取消操作翻转为 {after['state']}")
    if before == "succeeded":
        assert after["report"].strip(), "成功报告在取消后丢失"


# ------------------------------------------------------------ H5 重启语义
def test_h5_restart_does_not_leave_permanent_running(monkeypatch, fake_llm) -> None:
    """人工制造 running 遗留 + 模拟重启 → 不得永久 running。"""
    app = _app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": f"H5 重启用例 {NONCE}"}).json()["job_id"]
        _wait(c, jid)
    # 人工把作业改回 running(模拟进程崩在半路)
    store_files = list((HOST / "research_jobs").glob(f"{jid}.json"))
    assert store_files, "JOB_STATE_LOSS:作业状态未持久化,重启后无从恢复"
    p = store_files[0]
    data = json.loads(p.read_text(encoding="utf-8"))
    data["state"] = "running"
    data["finished_at"] = None
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    app2 = _app(monkeypatch, fake_llm)            # 重新装载 = 进程重启
    with TestClient(app2) as c:
        st = c.get(f"{API}/{jid}").json()
    assert st["state"] != "running", "JOB_STATE_LOSS:重启后作业永久停在 running"
    assert st["state"] in TERMINAL, f"重启后状态不明确:{st['state']}"


# ------------------------------------------------------------ H6 密钥出口
def test_h6_api_key_never_leaks_anywhere(monkeypatch, fake_llm) -> None:
    """SECRET_LEAK:哨兵密钥不得出现在响应/报告/作业文件/日志/KB。"""
    app = _app(monkeypatch, fake_llm, key=REAL_KEY_SENTINEL)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": f"H6 密钥出口用例 {NONCE}"}).json()["job_id"]
        st = _wait(c, jid)
        blob = json.dumps(st, ensure_ascii=False)
        assert REAL_KEY_SENTINEL not in blob, "SECRET_LEAK:接口响应含 API key"
        c.post(f"{API}/{jid}/promote")
    scanned = 0
    for path in HOST.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(HOST)
        if rel.parts and rel.parts[0] in {".venv", ".git", "__pycache__", "node_modules"}:
            continue
        if path.suffix.lower() not in {".json", ".md", ".txt", ".log", ".jsonl", ".yaml", ".yml"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        assert REAL_KEY_SENTINEL not in text, f"SECRET_LEAK:{rel} 含 API key"
    assert scanned > 0, "扫描面为空,用例失效"
    for row in _kb_rows():
        assert REAL_KEY_SENTINEL not in json.dumps(row, ensure_ascii=False), (
            "SECRET_LEAK:知识库内容含 API key")


# ------------------------------------------------------------ H7 未 Promote
def test_h7_success_without_promote_leaves_kb_clean(monkeypatch, fake_llm) -> None:
    """RAG_SOURCE_CONTAMINATION:成功但未 Promote → KB 不得新增该作业内容。"""
    app = _app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": f"H7 未入库用例 DELTA-W4-{NONCE}"}).json()["job_id"]
        _wait(c, jid)
    ids = {str(r["meta"].get("research_job_id", "")) for r in _kb_rows()}
    assert jid not in ids, "未 Promote 却已写入知识库"
    assert not any(f"DELTA-W4-{NONCE}" in r["doc"] for r in _kb_rows()), "未 Promote 内容已污染 KB"


# ------------------------------------------------------------ H8 Promote 溯源
def test_h8_promote_carries_full_provenance(monkeypatch, fake_llm) -> None:
    app = _app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": f"H8 溯源用例 EPSILON-V5-{NONCE}"}).json()["job_id"]
        st = _wait(c, jid)
        r = c.post(f"{API}/{jid}/promote")
        assert r.status_code == 200, r.text
    rows = [x for x in _kb_rows() if str(x["meta"].get("research_job_id")) == jid]
    assert rows, "Promote 后 KB 无该作业记录"
    for row in rows:
        m = row["meta"]
        assert m.get("source_type") == "research_report", (
            f"SOURCE_TYPE_VIOLATION:{m.get('source_type')}")
        assert str(m.get("research_job_id")) == jid
        assert str(m.get("source_urls", "")).strip(), "缺 source_urls 溯源"
    assert st["source_urls"], "作业结果本身缺引用来源"


# ------------------------------------------------------------ H9 域隔离
def test_h9_research_reports_never_enter_paper_domain(monkeypatch, fake_llm) -> None:
    app = _app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        jid = c.post(API, json={"input_text": f"H9 域隔离用例 ZETA-U6-{NONCE}"}).json()["job_id"]
        _wait(c, jid)
        c.post(f"{API}/{jid}/promote")
    for row in _kb_rows():
        m = row["meta"]
        if str(m.get("research_job_id", "")):
            assert m.get("source_type") != "paper", "SOURCE_TYPE_VIOLATION:研究报告混入 paper 域"
        if m.get("source_type") == "paper":
            assert not str(m.get("research_job_id", "")), "paper 域出现 research_job_id"


# ------------------------------------------------------------ H10 宿主回归
def test_h10_host_capabilities_intact(monkeypatch, fake_llm) -> None:
    """既有能力面不回归:路由数不少于 metrics 事实源,核心端点可用。"""
    app = _app(monkeypatch, fake_llm)
    with TestClient(app) as c:
        spec = c.get("/openapi.json").json()
        assert c.get("/health").status_code == 200
        assert c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                      headers={"Origin": "http://localhost"}).status_code == 200
    metrics = json.loads((HOST / "metrics.json").read_text(encoding="utf-8"))
    declared = int(metrics["current"]["routes"])
    ops = sum(1 for item in spec.get("paths", {}).values()
              for op in item.values() if isinstance(op, dict) and "operationId" in op)
    assert ops >= declared, f"HOST_REGRESSION_FAILURE:operation {ops} < 事实源 {declared}"


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "research_jobs"))]:
        sys.modules.pop(m, None)
