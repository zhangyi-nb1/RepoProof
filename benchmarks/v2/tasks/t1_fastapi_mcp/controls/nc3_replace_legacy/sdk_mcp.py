"""NC3:直接替换现有 /mcp 的工具集(只暴露白名单)—— 必须挂 H3(旧 MCP 回归)。"""
from __future__ import annotations

import os

FLAG = "OFFERCLAW_SDK_MCP"
MOUNT_PATH = "/mcp-sdk"
ALLOWED = ["health_health_get", "get_profile_api_profile_get",
           "rag_search_api_search_post", "job_match_api_match_post",
           "get_applications_api_applications_get"]


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() in {"1", "true", "True", "yes"}


def mount_sdk_mcp(app):
    if not enabled():
        return None
    from fastapi_mcp import FastApiMCP
    if getattr(app.state, "sdk_mcp", None) is None:
        mcp = FastApiMCP(app, name="replacer", include_operations=list(ALLOWED))
        mcp.mount_http(mount_path=MOUNT_PATH)
        app.state.sdk_mcp = mcp
    # 破坏点:顺手"精简"旧 REGISTRY(以为新接口已覆盖)
    import tools_registry
    for name in list(tools_registry.REGISTRY.tools):
        if name not in {"match_jd", "extract_jd"}:
            tools_registry.REGISTRY.tools.pop(name, None)
    return app.state.sdk_mcp
