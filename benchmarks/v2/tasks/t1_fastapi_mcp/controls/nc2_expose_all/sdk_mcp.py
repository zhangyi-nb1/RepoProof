"""NC2:自动暴露全部路由(无白名单)—— 必须挂 H1(TOOL_EXPOSURE_LEAK)。"""
from __future__ import annotations

import os

FLAG = "OFFERCLAW_SDK_MCP"
MOUNT_PATH = "/mcp-sdk"


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() in {"1", "true", "True", "yes"}


def mount_sdk_mcp(app):
    if not enabled():
        return None
    if getattr(app.state, "sdk_mcp", None) is not None:
        return app.state.sdk_mcp
    from fastapi_mcp import FastApiMCP
    mcp = FastApiMCP(app, name="leaky")          # 无 include_operations
    mcp.mount_http(mount_path=MOUNT_PATH)
    app.state.sdk_mcp = mcp
    return mcp
