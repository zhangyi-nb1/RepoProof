"""NC4:白名单正确但 schema 手写固定字典 —— 必须挂 H2(SCHEMA_DRIFT)。"""
from __future__ import annotations

import json
import os

from fastapi import Request
from fastapi.responses import JSONResponse

FLAG = "OFFERCLAW_SDK_MCP"
MOUNT_PATH = "/mcp-sdk"
ALLOWED = ["health_health_get", "get_profile_api_profile_get"]


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() in {"1", "true", "True", "yes"}


def mount_sdk_mcp(app):
    if not enabled():
        return None
    from fastapi_mcp import FastApiMCP  # 真实 import(骗过 provenance)
    _ = FastApiMCP(app, name="static", include_operations=list(ALLOWED))
    tools = [{"name": n, "description": n,
              "inputSchema": {"type": "object",
                              "properties": {"rp_ghost_field": {"type": "string"}},
                              "title": f"{n}Arguments"}} for n in ALLOWED]

    @app.post(MOUNT_PATH, include_in_schema=False)
    async def _static(request: Request):
        body = json.loads(await request.body() or b"{}")
        m, i = body.get("method"), body.get("id")
        if m == "initialize":
            return JSONResponse({"jsonrpc": "2.0", "id": i, "result": {}},
                                headers={"mcp-session-id": "static"})
        if m == "tools/list":
            return JSONResponse({"jsonrpc": "2.0", "id": i, "result": {"tools": tools}})
        return JSONResponse({"jsonrpc": "2.0", "id": i, "result": {}})
    return object()
