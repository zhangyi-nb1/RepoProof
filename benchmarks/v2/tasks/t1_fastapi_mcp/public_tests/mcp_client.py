"""MCP Streamable HTTP 最小客户端(公开:agent 可见可复用)。

任务工程期实测:必须 `with TestClient(app)` 触发 lifespan(否则
session manager 报 "Task group is not initialized");握手序列为
initialize(取 mcp-session-id 响应头)→ notifications/initialized →
业务方法(带 session 头)。
"""

from __future__ import annotations

import json

HEADERS = {"Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}


def parse_body(text: str) -> dict:
    """兼容纯 JSON 与 SSE(`data: {...}`)两种响应形态。"""
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"无法解析 MCP 响应: {text[:200]}")


def handshake(client, path: str) -> dict:
    """→ 带 mcp-session-id 的请求头;client 必须处于 lifespan 上下文中。"""
    r = client.post(path, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "repoproof-public-test", "version": "1"}},
    }, headers=HEADERS)
    assert r.status_code == 200, f"initialize 失败 {r.status_code}: {r.text[:200]}"
    sid = r.headers.get("mcp-session-id")
    h = dict(HEADERS)
    if sid:
        h["mcp-session-id"] = sid
    client.post(path, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=h)
    return h


def call(client, path: str, headers: dict, method: str, msg_id: int = 2,
         params: dict | None = None) -> dict:
    payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
    r = client.post(path, json=payload, headers=headers)
    assert r.status_code == 200, f"{method} 失败 {r.status_code}: {r.text[:200]}"
    return parse_body(r.text)


def list_tool_names(client, path: str) -> list[str]:
    h = handshake(client, path)
    data = call(client, path, h, "tools/list")
    return [t["name"] for t in data.get("result", {}).get("tools", [])]
