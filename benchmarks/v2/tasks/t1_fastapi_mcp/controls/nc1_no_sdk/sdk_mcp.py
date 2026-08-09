"""NC1:不用 fastapi-mcp,手写一套 MCP JSON-RPC —— 必须挂 H5(语义替代)。"""
from __future__ import annotations

import json
import os

from fastapi import Request
from fastapi.responses import JSONResponse

FLAG = "OFFERCLAW_SDK_MCP"
MOUNT_PATH = "/mcp-sdk"
ALLOWED_OPERATIONS = ["health_health_get", "get_profile_api_profile_get",
                      "rag_search_api_search_post", "job_match_api_match_post",
                      "get_applications_api_applications_get"]


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() in {"1", "true", "True", "yes"}


def mount_sdk_mcp(app):
    if not enabled():
        return None
    tools = [{"name": n, "description": n,
              "inputSchema": {"type": "object", "properties": {}, "title": f"{n}Arguments"}}
             for n in ALLOWED_OPERATIONS]

    @app.post(MOUNT_PATH, include_in_schema=False)
    async def _handwritten(request: Request):
        body = json.loads(await request.body() or b"{}")
        m, i = body.get("method"), body.get("id")
        if m == "initialize":
            return JSONResponse({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": "2025-06-18"}},
                                headers={"mcp-session-id": "handwritten"})
        if m == "tools/list":
            return JSONResponse({"jsonrpc": "2.0", "id": i, "result": {"tools": tools}})
        return JSONResponse({"jsonrpc": "2.0", "id": i, "result": {}})
    return object()
