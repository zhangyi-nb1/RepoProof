"""Experimental, allowlisted MCP view of OfferClaw's FastAPI API.

This module deliberately does not adapt endpoints itself.  ``FastApiMCP`` reads
FastAPI's generated OpenAPI document, so tool argument schemas continue to come
from the route's Pydantic models.  The legacy ``/mcp`` implementation remains
separate and continues to expose ``tools_registry.REGISTRY``.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi_mcp import FastApiMCP

SDK_MCP_PATH = "/mcp-sdk"

# This is an include-only security boundary, rather than a denylist.  Every
# operation here was reviewed as read-only.  Adding a FastAPI route can never
# expose it implicitly.
SDK_MCP_READ_ONLY_OPERATIONS = (
    "health_health_get",
    "get_profile_api_profile_get",
    "rag_search_api_search_post",
    "job_match_api_match_post",
    "get_applications_api_applications_get",
)

_STATE_KEY = "offerclaw_sdk_mcp"


def mount_sdk_mcp(app: FastAPI) -> FastApiMCP:
    """Mount the upstream SDK once and return the app's SDK instance.

    Keeping the instance on ``app.state`` makes repeated startup/setup calls
    idempotent and retains the transport for the lifetime of the application.
    """
    existing = getattr(app.state, _STATE_KEY, None)
    if existing is not None:
        return existing

    mcp = FastApiMCP(
        app,
        name="OfferClaw Read-only API",
        description="Experimental allowlisted read-only OfferClaw capabilities",
        include_operations=list(SDK_MCP_READ_ONLY_OPERATIONS),
    )
    mcp.mount_http(mount_path=SDK_MCP_PATH)
    setattr(app.state, _STATE_KEY, mcp)
    return mcp
