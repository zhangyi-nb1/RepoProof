"""OpenAI 兼容 Fake LLM 服务器(T2 公开 fixture,agent 可见可用;stdlib-only)。

任务工程期实测结论(写给使用者):真实 ODR Graph 可被本 stub +
`search_api="none"` 完整驱动(简报→supervisor→researcher→压缩→终稿),
零公网零真钥;langchain-openai 1.x 的 with_structured_output 走
`response_format.json_schema` 而非 function-calling,两条路径都已适配;
ODR 用 get_buffer_string 把对话嵌进提示,故主题指纹从 "Human:" 行
提取,并经"简报回流"在下游节点闭环——并发任务据此可验证零互串。

用途:以本地 HTTP 端点扮演 chat.completions,按请求携带的 tools 集合
启发式路由到脚本化响应,驱动**真实 ODR Graph** 跑通全程(Fake Model,
零公网、零真钥)。并发任务用 topic 指纹分桶计数,响应内容回写 topic
片段——上层测试可借此验证结果不串(H2)。
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_LOCK = threading.Lock()
_COUNTS: dict[tuple[str, str], int] = {}


def _all_text(messages: list[dict]) -> str:
    out = []
    for m in messages:
        c = m.get("content") or ""
        if isinstance(c, list):  # 多模态形态兜底
            c = " ".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
        out.append(str(c))
    return re.sub(r"\s+", " ", " ".join(out))


def _topic_of(messages: list[dict]) -> str:
    """主题指纹(并发分桶 + 回显闭环)。

    优先捕获 stub 自己写入简报的回流文本(简报随 ODR 提示流动到
    supervisor/终稿节点,形成确定性闭环);否则取**首条** human 消息
    (即适配层传入的原始主题)。"""
    joined = _all_text(messages)
    m = re.search(r"研究简报\(合成\):([^\"<]{1,80})", joined)
    if m:  # 下游节点:简报回流(stub 自身写入,确定性闭环)
        return m.group(1).strip()[:80]
    # 上游节点:ODR 用 get_buffer_string 把对话嵌进提示 → 抓首个 "Human:"
    m = re.search(r"Human:\s*([^\n<]{1,80})", joined)
    if m:
        return m.group(1).strip()[:80]
    for msg in messages:
        if msg.get("role") in ("user", "human"):
            c = _all_text([msg]).strip()
            if c:
                return c[:80]
    return "unknown-topic"


def _bump(topic: str, kind: str) -> int:
    with _LOCK:
        k = (topic, kind)
        _COUNTS[k] = _COUNTS.get(k, 0) + 1
        return _COUNTS[k]


def _tool_call(name: str, args: dict) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": f"call_{name}_{_bump('_ids', name)}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
        }],
    }


def _text(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _fill_schema(schema: dict, topic: str) -> object:
    """通用 JSON-Schema 最小填充器(structured output 的兜底应答)。"""
    t = schema.get("type")
    if t == "object":
        return {k: _fill_schema(v, topic)
                for k, v in (schema.get("properties") or {}).items()}
    if t == "string":
        return f"合成:{topic}"
    if t == "boolean":
        return False
    if t in ("integer", "number"):
        return 1
    if t == "array":
        return []
    return None


def route(body: dict) -> tuple[dict, str]:
    """→ (message, finish_reason)。优先 response_format(json_schema 结构化
    输出,langchain-openai 1.x 的 with_structured_output 默认路径),
    其次按 tools 名集合判断所处节点。"""
    tools = {t.get("function", {}).get("name", "") for t in body.get("tools") or []}
    topic = _topic_of(body.get("messages") or [])

    rf = body.get("response_format") or {}
    js = rf.get("json_schema") or {} if isinstance(rf, dict) else {}
    rf_name = js.get("name", "")
    if rf_name:
        schema = js.get("schema") or {}
        if rf_name == "ClarifyWithUser":
            obj = {"need_clarification": False, "question": "",
                   "verification": f"开始研究:{topic}(合成)"}
        elif rf_name == "ResearchQuestion":
            obj = {"research_brief": f"研究简报(合成):{topic}"}
        else:
            obj = _fill_schema(schema, topic)
        return _text(json.dumps(obj, ensure_ascii=False)), "stop"

    if "ClarifyWithUser" in tools:
        return _tool_call("ClarifyWithUser", {
            "need_clarification": False, "question": "",
            "verification": f"开始研究:{topic}(合成)"}), "tool_calls"
    if "ResearchQuestion" in tools:
        return _tool_call("ResearchQuestion", {
            "research_brief": f"研究简报(合成):{topic}"}), "tool_calls"
    if "ConductResearch" in tools:
        n = _bump(topic, "supervisor")
        if n == 1:
            return _tool_call("ConductResearch", {
                "research_topic": f"{topic} 的公开信息与岗位相关要点(合成子题)"}), "tool_calls"
        return _tool_call("ResearchComplete", {}), "tool_calls"
    if "think_tool" in tools:  # researcher(无 ConductResearch)
        n = _bump(topic, "researcher")
        if n == 1:
            return _tool_call("think_tool", {
                "reflection": f"计划(合成):围绕 {topic} 归纳要点"}), "tool_calls"
        return _tool_call("ResearchComplete", {}), "tool_calls"
    # 无工具:压缩或终稿
    sys_text = " ".join(str(m.get("content", "")) for m in (body.get("messages") or [])
                        if m.get("role") == "system")[:2000]
    if "clean" in sys_text.lower() or "compress" in sys_text.lower() or "整理" in sys_text:
        return _text(f"压缩后的研究发现(合成):关于 {topic} 的三条要点。"), "stop"
    return _text(
        f"# 研究报告(合成)\n\n主题:{topic}\n\n## 发现\n- 要点一(合成)\n- 要点二(合成)\n\n"
        f"## 引用\n- https://example.invalid/source-a\n- https://example.invalid/source-b\n"), "stop"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        if "/chat/completions" not in self.path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"unsupported path {self.path}"}).encode())
            return
        message, finish = route(body)
        payload = {
            "id": "chatcmpl-fake", "object": "chat.completion", "created": 1,
            "model": body.get("model", "fake"),
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # 静默
        pass


def start(port: int = 0) -> tuple[ThreadingHTTPServer, int]:
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


if __name__ == "__main__":
    srv, p = start(8899)
    print("fake llm stub on", p)
    import time
    while True:
        time.sleep(60)
