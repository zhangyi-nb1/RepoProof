"""T1 公开验收(agent 可见可自测)。

覆盖公开需求 R1-R8 的可公开部分;隐藏验收另有更严格的越权/漂移用例。
约定:Feature Flag 环境变量 `OFFERCLAW_SDK_MCP=1` 开启,新端点默认
挂在 `/mcp-sdk`;白名单只允许只读能力。
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mcp_client import handshake, list_tool_names  # noqa: E402

SDK_PATH = "/mcp-sdk"
FLAG = "OFFERCLAW_SDK_MCP"

# 白名单上界:只读能力(FastAPI operationId;OfferClaw 未显式声明
# operation_id,框架自动生成 `<func>_<path>_<method>`)
ALLOWED = {
    "health_health_get",
    "get_profile_api_profile_get",
    "rag_search_api_search_post",
    "job_match_api_match_post",
    "get_applications_api_applications_get",
}
# 绝不允许出现的写入/生成/发现类语义(源需求 R4 逐条列出)
FORBIDDEN_HINTS = ("upsert", "resume", "discover", "ingest", "add_url", "add_file",
                   "promote", "reveal", "append_daily", "upload", "reset", "agent_run")


def _load_app(monkeypatch, flag: str | None):
    """按 Flag 重载宿主 app(Flag 必须在 import 期生效)。"""
    if flag is None:
        monkeypatch.delenv(FLAG, raising=False)
    else:
        monkeypatch.setenv(FLAG, flag)
    for mod in [m for m in list(sys.modules) if m.startswith(("rag_api", "sdk_mcp"))]:
        sys.modules.pop(mod, None)
    return importlib.import_module("rag_api").app


def test_flag_off_by_default_no_new_endpoint(monkeypatch) -> None:
    """R1:默认关闭——新端点不存在,现有行为零变化。"""
    app = _load_app(monkeypatch, None)
    with TestClient(app) as c:
        r = c.post(SDK_PATH, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code in (404, 405), f"Flag 关闭时新端点不应可用:{r.status_code}"


def test_legacy_mcp_unchanged_with_flag_on(monkeypatch) -> None:
    """R2:开启新能力后,旧 /mcp 的 tools/list 结果不变。"""
    from tools_registry import REGISTRY

    app = _load_app(monkeypatch, "1")
    with TestClient(app) as c:
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                   headers={"Origin": "http://localhost"})
        assert r.status_code == 200
        names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == set(REGISTRY.tools), "旧 /mcp 暴露的工具集合必须与 REGISTRY 完全一致"


def test_sdk_endpoint_lists_only_allowlisted_tools(monkeypatch) -> None:
    """R3+R4:新端点可用,且只暴露白名单内的只读能力。"""
    app = _load_app(monkeypatch, "1")
    with TestClient(app) as c:
        names = set(list_tool_names(c, SDK_PATH))
    assert names, "开启 Flag 后 SDK MCP 应至少暴露一个工具"
    assert names <= ALLOWED, f"暴露了白名单外的能力:{sorted(names - ALLOWED)}"
    for n in names:
        low = n.lower()
        assert not any(h in low for h in FORBIDDEN_HINTS), f"疑似写入/生成类能力泄漏:{n}"


def test_tool_input_schema_is_generated_not_handwritten(monkeypatch) -> None:
    """R5:inputSchema 必须由框架派生(带 title/properties 结构),
    而不是手写的空壳或固定字典。"""
    from mcp_client import call

    app = _load_app(monkeypatch, "1")
    with TestClient(app) as c:
        h = handshake(c, SDK_PATH)
        data = call(c, SDK_PATH, h, "tools/list")
    tools = data["result"]["tools"]
    for t in tools:
        schema = t.get("inputSchema")
        assert isinstance(schema, dict) and schema.get("type") == "object", t["name"]
        assert "properties" in schema, f"{t['name']} 缺 properties(疑似手写空壳)"


def test_repeated_mount_yields_no_duplicate_tools(monkeypatch) -> None:
    """R6:重复初始化/挂载不得产生重复 Tool。"""
    app = _load_app(monkeypatch, "1")
    with TestClient(app) as c:
        names = list_tool_names(c, SDK_PATH)
    assert len(names) == len(set(names)), f"存在重复工具:{names}"
    app2 = _load_app(monkeypatch, "1")          # 二次装载
    with TestClient(app2) as c:
        names2 = list_tool_names(c, SDK_PATH)
    assert len(names2) == len(set(names2)) and set(names2) == set(names)


def test_real_upstream_is_used(monkeypatch) -> None:
    """R8:必须真实使用 fastapi_mcp(可导入且被宿主引用)。"""
    import fastapi_mcp  # 未安装即失败

    assert hasattr(fastapi_mcp, "FastApiMCP")
    root = Path(__file__).resolve().parents[1]
    host = Path(os.environ.get("OFFERCLAW_HOST_ROOT", root))
    hits = [p for p in host.rglob("*.py")
            if ".venv" not in p.parts and "fastapi_mcp" in p.read_text(
                encoding="utf-8", errors="replace")]
    assert hits, "宿主代码中未见对 fastapi_mcp 的引用"


@pytest.mark.parametrize("route", ["/health", "/openapi.json"])
def test_existing_routes_still_work(monkeypatch, route: str) -> None:
    """R7:开启新能力后既有路由与 OpenAPI 仍正常。"""
    app = _load_app(monkeypatch, "1")
    with TestClient(app) as c:
        assert c.get(route).status_code == 200
