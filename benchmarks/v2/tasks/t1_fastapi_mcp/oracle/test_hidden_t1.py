"""T1 隐藏验收(harness 持有,**绝不进入 agent 工作区或环境**)。

比公开测试更严格:逐条枚举必须被拒绝暴露的敏感能力、检查 schema 与
FastAPI 真实定义逐字段一致、旧 MCP 协议细节回归、真实上游使用的
结构性证据(而非字符串出现)。源方案 §7.4 H1-H8。
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _find_host() -> Path:
    """宿主根 = 环境变量指定 / cwd 向上首个含 rag_api.py 的目录。

    隐藏 oracle 位于 harness 侧(不在宿主树内),因此不能按 __file__
    上溯——必须按执行时的 cwd 定位被验收的宿主。"""
    env = os.environ.get("OFFERCLAW_HOST_ROOT")
    if env and (Path(env) / "rag_api.py").exists():
        return Path(env).resolve()
    cwd = Path.cwd().resolve()
    for cand in (cwd, *cwd.parents):
        if (cand / "rag_api.py").exists():
            return cand
    raise AssertionError("找不到宿主根(rag_api.py);请在宿主目录内运行或设 OFFERCLAW_HOST_ROOT")


HOST = _find_host()
sys.path.insert(0, str(HOST))

SDK_PATH = "/mcp-sdk"
FLAG = "OFFERCLAW_SDK_MCP"

# H1:这些 operation **任何情况下**都不得出现在 SDK MCP
# (源需求 R4:applications 写入 / memory 写入 / resume 生成 / JD discover
#  / KB 写入 / 内部调试)
FORBIDDEN_TOOLS = {
    "upsert_application_api_api_applications_upsert_post",
    "build_resume_api_resume_build_post",
    "resume_project_stream_api_resume_project_stream_post",
    "upload_resume_template_api_resume_templates_post",
    "discover_api_discover_post",
    "kb_add_url_api_kb_add_url_post",
    "kb_add_file_api_kb_add_file_post",
    "kb_promote_api_kb_promote_post",
    "kb_ingest_path_api_kb_ingest_path_post",
    "append_daily_api_daily_post",
    "append_daily_structured_api_daily_log_post",
    "reset_conversation_api_reset_post",
    "agent_run_api_agent_post",
}
# 旧 /mcp 的**冻结**工具集(任务工程期实测,不随运行时 REGISTRY 变化)
LEGACY_MCP_TOOLS_FROZEN = {
    "match_jd", "extract_jd", "resume_skeleton",
    "today_advice", "list_applications", "career_flow",
}
# 只读白名单的上界(可少不可多)
ALLOWED_UPPER_BOUND = {
    "health_health_get",
    "get_profile_api_profile_get",
    "rag_search_api_search_post",
    "job_match_api_match_post",
    "get_applications_api_applications_get",
}


def _client(monkeypatch, flag="1"):
    monkeypatch.setenv(FLAG, flag)
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "sdk_mcp"))]:
        sys.modules.pop(m, None)
    return importlib.import_module("rag_api").app


def _handshake(c, path=SDK_PATH):
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    r = c.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "hidden", "version": "1"}}},
               headers=h)
    assert r.status_code == 200, f"initialize 失败:{r.status_code}"
    sid = r.headers.get("mcp-session-id")
    if sid:
        h["mcp-session-id"] = sid
    c.post(path, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=h)
    return h


def _body(text: str) -> dict:
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"无法解析:{text[:200]}")


def _tools(c) -> list[dict]:
    h = _handshake(c)
    r = c.post(SDK_PATH, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=h)
    assert r.status_code == 200
    return _body(r.text)["result"]["tools"]


# ---------------------------------------------------------------- H1 越权
def test_h1_write_and_generation_tools_never_exposed(monkeypatch) -> None:
    with TestClient(_client(monkeypatch)) as c:
        names = {t["name"] for t in _tools(c)}
    leaked = names & FORBIDDEN_TOOLS
    assert not leaked, f"TOOL_EXPOSURE_LEAK:写入/生成类能力被暴露 {sorted(leaked)}"
    assert names <= ALLOWED_UPPER_BOUND, f"白名单外能力:{sorted(names - ALLOWED_UPPER_BOUND)}"
    assert names, "白名单不能为空(等于没实现能力)"


def test_h1b_no_internal_or_admin_paths_exposed(monkeypatch) -> None:
    """按语义关键词兜底:任何 admin/debug/internal/ingest 类不得出现。"""
    with TestClient(_client(monkeypatch)) as c:
        blob = json.dumps(_tools(c), ensure_ascii=False).lower()
    for kw in ("upsert", "ingest", "promote", "reveal", "discover", "reset",
               "agent_run", "upload", "build_resume"):
        assert kw not in blob, f"疑似内部/管理能力泄漏关键词:{kw}"


# ---------------------------------------------------------------- H2 schema
def test_h2_schema_matches_fastapi_definition(monkeypatch) -> None:
    """PROTOCOL_SCHEMA_DRIFT:MCP schema 的字段必须能在 OpenAPI 里找到
    同名定义——手抄的第二份 schema 会在此暴露。"""
    app = _client(monkeypatch)
    with TestClient(app) as c:
        tools = _tools(c)
        openapi = c.get("/openapi.json").json()
    blob = json.dumps(openapi, ensure_ascii=False)
    for t in tools:
        schema = t.get("inputSchema") or {}
        assert schema.get("type") == "object" and "properties" in schema, t["name"]
        for field in schema["properties"]:
            assert field in blob, (
                f"PROTOCOL_SCHEMA_DRIFT:{t['name']}.{field} 在 OpenAPI 中不存在,"
                "疑似手写第二份 schema")


# ---------------------------------------------------------------- H3 旧 MCP
def test_h3_legacy_mcp_protocol_regression(monkeypatch) -> None:
    """旧 /mcp 的 initialize/tools/list/tools/call 与 origin 校验全部保持。

    基准是**冻结值**而非运行时 REGISTRY:负控 NC3 实测证明,同时"精简"
    REGISTRY 与 /mcp 可以骗过自指断言(两边一起变则永远相等)。"""
    with TestClient(_client(monkeypatch)) as c:
        ok = {"Origin": "http://localhost"}
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                 "params": {}}, headers=ok)
        assert r.status_code == 200 and "result" in r.json()
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=ok)
        assert {t["name"] for t in r.json()["result"]["tools"]} == LEGACY_MCP_TOOLS_FROZEN, (
            "旧 /mcp 工具集合相对冻结基线发生变化(HOST_REGRESSION_FAILURE)")
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "ping"}, headers=ok)
        assert r.status_code == 200
        bad = c.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
                     headers={"Origin": "http://evil.example.com"})
        assert bad.status_code >= 400, "旧 /mcp 的 Origin 校验被破坏"


# ---------------------------------------------------------------- H4 重复挂载
def test_h4_duplicate_mount_guard(monkeypatch) -> None:
    with TestClient(_client(monkeypatch)) as c:
        names = [t["name"] for t in _tools(c)]
    assert len(names) == len(set(names)), f"DUPLICATE_MOUNT:{names}"


# ---------------------------------------------------------------- H5 真实上游
def test_h5_upstream_really_used_structurally(monkeypatch) -> None:
    """UPSTREAM_CAPABILITY_REIMPLEMENTED:不看字符串,看结构——
    宿主必须真的构造出 FastApiMCP 实例并把它的 ASGI 挂进 app。"""
    import fastapi_mcp

    app = _client(monkeypatch)
    created: list[object] = []
    orig_init = fastapi_mcp.FastApiMCP.__init__

    def spy(self, *a, **kw):
        created.append(self)
        return orig_init(self, *a, **kw)

    monkeypatch.setattr(fastapi_mcp.FastApiMCP, "__init__", spy)
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "sdk_mcp"))]:
        sys.modules.pop(m, None)
    app = importlib.import_module("rag_api").app
    with TestClient(app) as c:
        _tools(c)
    assert created, "未观察到 FastApiMCP 实例化——疑似自行重写 MCP 转换层"


# ---------------------------------------------------------------- H6 Flag 关闭
def test_h6_flag_off_is_fully_inert(monkeypatch) -> None:
    """Flag 关闭时:新端点不存在,且 OpenAPI 中不出现 SDK 端点路径。"""
    monkeypatch.delenv(FLAG, raising=False)
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "sdk_mcp"))]:
        sys.modules.pop(m, None)
    app = importlib.import_module("rag_api").app
    with TestClient(app) as c:
        assert c.post(SDK_PATH, json={"jsonrpc": "2.0", "id": 1,
                                      "method": "tools/list"}).status_code in (404, 405)
        assert SDK_PATH not in json.dumps(c.get("/openapi.json").json())


# ---------------------------------------------------------------- H7 工具可调用
def test_h7_allowlisted_tool_is_actually_callable(monkeypatch) -> None:
    """白名单工具不能是空壳:tools/call 必须返回结构化结果而非协议错误。"""
    with TestClient(_client(monkeypatch)) as c:
        h = _handshake(c)
        tools = _tools(c)
        target = next((t for t in tools if t["name"] == "health_health_get"), tools[0])
        r = c.post(SDK_PATH, json={"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                   "params": {"name": target["name"], "arguments": {}}},
                   headers=h)
        assert r.status_code == 200
        data = _body(r.text)
    assert "result" in data or "error" in data
    if "error" in data:
        assert data["error"].get("code") != -32601, "工具已列出却未实现(method not found)"


# ---------------------------------------------------------------- H8 宿主回归
def test_h8_host_regression_untouched(monkeypatch) -> None:
    """既有路由数量与 metrics 事实源一致(53 条),OpenAPI 可用。"""
    app = _client(monkeypatch)
    with TestClient(app) as c:
        spec = c.get("/openapi.json").json()
    metrics = json.loads((HOST / "metrics.json").read_text(encoding="utf-8"))
    declared = int(metrics["current"]["routes"])
    # 事实源计的是 operation 数(同一路径可有多方法),不是 path 数
    ops = sum(1 for item in spec.get("paths", {}).values()
              for op in item.values() if isinstance(op, dict) and "operationId" in op)
    assert ops >= declared, f"HOST_REGRESSION_FAILURE:operation 数 {ops} < 事实源 {declared}"


@pytest.fixture(autouse=True)
def _clean_modules():
    yield
    for m in [m for m in list(sys.modules) if m.startswith(("rag_api", "sdk_mcp"))]:
        sys.modules.pop(m, None)
