"""Regression coverage for the opt-in, SDK-backed MCP endpoint."""
from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def _reload(monkeypatch, enabled: bool):
    if enabled:
        monkeypatch.setenv("OFFERCLAW_SDK_MCP", "1")
    else:
        monkeypatch.delenv("OFFERCLAW_SDK_MCP", raising=False)
    for name in tuple(sys.modules):
        if name == "rag_api" or name.startswith("sdk_mcp"):
            sys.modules.pop(name, None)
    return importlib.import_module("rag_api").app


def test_sdk_mcp_disabled_does_not_add_a_route(monkeypatch):
    app = _reload(monkeypatch, False)
    assert not any(getattr(route, "path", None) == "/mcp-sdk" for route in app.routes)


def test_sdk_allowlist_and_schema_are_from_openapi(monkeypatch):
    app = _reload(monkeypatch, True)
    from sdk_mcp import SDK_MCP_READ_ONLY_OPERATIONS

    sdk = app.state.offerclaw_sdk_mcp
    tools = sdk.tools
    assert {tool.name for tool in tools} == set(SDK_MCP_READ_ONLY_OPERATIONS)
    assert len(tools) == len({tool.name for tool in tools})

    openapi = app.openapi()
    by_id = {
        operation["operationId"]: operation
        for path in openapi["paths"].values()
        for operation in path.values()
        if isinstance(operation, dict) and "operationId" in operation
    }
    # Request-body models remain referenced from FastAPI's components; no
    # separately maintained MCP parameter schema exists in host code.
    match_schema = next(t.inputSchema for t in tools if t.name == "job_match_api_match_post")
    body_schema = by_id["job_match_api_match_post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    model_name = body_schema["$ref"].rsplit("/", 1)[-1]
    model_properties = openapi["components"]["schemas"][model_name]["properties"]
    assert set(match_schema["properties"]) == set(model_properties)
    assert {
        name: value.get("type") for name, value in match_schema["properties"].items()
    } == {name: value.get("type") for name, value in model_properties.items()}


def test_sdk_mount_is_idempotent_and_legacy_registry_unchanged(monkeypatch):
    app = _reload(monkeypatch, True)
    from sdk_mcp import mount_sdk_mcp
    from tools_registry import REGISTRY

    before = len([r for r in app.routes if getattr(r, "path", None) == "/mcp-sdk"])
    first = mount_sdk_mcp(app)
    second = mount_sdk_mcp(app)
    after = len([r for r in app.routes if getattr(r, "path", None) == "/mcp-sdk"])
    assert first is second and before == after == 1

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Origin": "http://localhost"},
        )
    assert response.status_code == 200
    assert {t["name"] for t in response.json()["result"]["tools"]} == set(REGISTRY.tools)
