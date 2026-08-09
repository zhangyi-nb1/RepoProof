"""正控参考实现(**绝不进入 agent 工作区或 bundle**)。

唯一用途:证明 T1 的公开测试 + 隐藏 oracle 自洽可满足(源方案 §14-6)。
安装:复制为宿主根目录 `sdk_mcp.py`,并在 rag_api.py 末尾调用
`mount_sdk_mcp(app)`。
"""

from __future__ import annotations

import os

FLAG = "OFFERCLAW_SDK_MCP"
MOUNT_PATH = "/mcp-sdk"

# 白名单(deny-by-default):只读能力的 FastAPI operationId。
# OfferClaw 路由未显式声明 operation_id,FastAPI 自动生成
# `<func>_<path>_<method>` 形式;此处按实测值登记。
ALLOWED_OPERATIONS = [
    "health_health_get",                       # 健康检查
    "get_profile_api_profile_get",             # 读档案
    "rag_search_api_search_post",              # 检索(只读)
    "job_match_api_match_post",                # 匹配计算(只读)
    "get_applications_api_applications_get",   # 读投递记录
]


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip() in {"1", "true", "True", "yes"}


def mount_sdk_mcp(app) -> object | None:
    """Flag 关闭时完全惰性;幂等挂载(防 DUPLICATE_MOUNT)。"""
    if not enabled():
        return None
    if getattr(app.state, "sdk_mcp", None) is not None:
        return app.state.sdk_mcp
    from fastapi_mcp import FastApiMCP

    mcp = FastApiMCP(
        app,
        name="OfferClaw SDK MCP (experimental)",
        description="只读能力的 SDK 驱动 MCP 接口;schema 由 FastAPI/Pydantic 派生",
        include_operations=list(ALLOWED_OPERATIONS),
    )
    mcp.mount_http(mount_path=MOUNT_PATH)
    app.state.sdk_mcp = mcp
    return mcp
