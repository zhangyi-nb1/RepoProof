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
片段——上层测试可借此验证结果不串。

v5 新增:**报告溯源的三条判据**(对应公开需求 R16)。

1. `srv.canary` —— 每台服务器现摇一枚随机金丝雀,写进"压缩后的研究发现"
   与终稿正文(开头结尾各一次)。凡是真的把响应正文接进报告的实现,报告
   里必然带着它;调 `init_chat_model` 却在进程内自答的本地回显桩带不出来。
2. `srv.session.final_reports` —— 本服务器发出过的终稿正文。报告里必须
   找得到其中某一份的开头一段。**这条比金丝雀强**:金丝雀是一个可搬运
   的常量,任何人发一发请求都能从响应里抠走再贴进自写模板(负控 nc8 实测
   过,当时全绿);正文同源搬不动。比对折叠空白后进行,重排版与截断存储
   不误伤。
3. `srv.session.requests` —— 已收到的 chat/completions 次数。走完一次
   研究不止一次调用,装饰性接线在此暴露。

诚实边界:金丝雀写在**响应正文**里,所以"无查询端点"不等于"拿不到"。
判据一从来不单独成立,它和判据二一起用。隐藏验收对判据二有更强的同源
变体(比对的是本次上游图调用的返回值),诚实实现两边都过。

    srv, port = start()
    srv.canary                    # 本次会话的随机金丝雀
    srv.session.final_reports     # 本服务器发出过的终稿正文
    srv.session.requests          # 已收到的 chat/completions 次数
"""

from __future__ import annotations

import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Session:
    """一台 stub 服务器的全部可观测状态。

    **金丝雀只活在这个实例里**:模块级不留任何持有它的名字,也不提供
    任何"查金丝雀"的 HTTP 端点。机制公开(这段文档就是全部机制)、
    取值随机(每次 `start()` 现摇)。

    但要说清楚:**没有查询端点 ≠ 拿不到**。金丝雀写在响应正文里,发一发
    不带 tools 的请求就命中终稿路由、就能把它抠走。所以它只是判据之一,
    必须和 `final_reports`(正文同源)一起用 —— 常量可以搬运,正文不行。

    计数与终稿记录同样按服务器分桶,不再是模块全局:两台 stub 并存时
    互不干扰,跨测试也不会串。
    """

    def __init__(self, canary: str) -> None:
        self.canary = canary
        self.requests = 0                        # 收到的 /chat/completions 次数
        self.final_reports: list[str] = []       # 本服务器发出过的终稿正文
        self._counts: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def hit(self) -> int:
        with self._lock:
            self.requests += 1
            return self.requests

    def bump(self, topic: str, kind: str) -> int:
        with self._lock:
            k = (topic, kind)
            self._counts[k] = self._counts.get(k, 0) + 1
            return self._counts[k]

    def record_final(self, body: str) -> None:
        with self._lock:
            self.final_reports.append(body)


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


def _tool_call(session: _Session, name: str, args: dict) -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": f"call_{name}_{session.bump('_ids', name)}",
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


def route(body: dict, session: _Session) -> tuple[dict, str]:
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
        return _tool_call(session, "ClarifyWithUser", {
            "need_clarification": False, "question": "",
            "verification": f"开始研究:{topic}(合成)"}), "tool_calls"
    if "ResearchQuestion" in tools:
        return _tool_call(session, "ResearchQuestion", {
            "research_brief": f"研究简报(合成):{topic}"}), "tool_calls"
    if "ConductResearch" in tools:
        n = session.bump(topic, "supervisor")
        if n == 1:
            return _tool_call(session, "ConductResearch", {
                "research_topic": f"{topic} 的公开信息与岗位相关要点(合成子题)"}), "tool_calls"
        return _tool_call(session, "ResearchComplete", {}), "tool_calls"
    if "think_tool" in tools:  # researcher(无 ConductResearch)
        n = session.bump(topic, "researcher")
        if n == 1:
            return _tool_call(session, "think_tool", {
                "reflection": f"计划(合成):围绕 {topic} 归纳要点"}), "tool_calls"
        return _tool_call(session, "ResearchComplete", {}), "tool_calls"
    # 无工具:压缩或终稿。两处都带金丝雀——不论实现把哪一段接成报告,
    # 只要正文真的来自本服务器,金丝雀就会到达报告。
    sys_text = " ".join(str(m.get("content", "")) for m in (body.get("messages") or [])
                        if m.get("role") == "system")[:2000]
    if "clean" in sys_text.lower() or "compress" in sys_text.lower() or "整理" in sys_text:
        return _text(
            f"压缩后的研究发现(合成):关于 {topic} 的三条要点。\n"
            f"[engine-canary {session.canary}]"), "stop"
    # 金丝雀在**开头和结尾各写一次**:诚实实现常会对报告做点后处理(截断
    # 存储、只取首段、加个抬头),只写在末尾会把这些人误杀成"报告是伪造的"。
    # 误杀比漏杀更贵 —— 漏杀只是这一发没抓住,误杀是判据本身作废。
    body = (
        f"# 研究报告(合成)\n\n主题:{topic}\n\nengine-canary: {session.canary}\n\n"
        f"## 发现\n- 要点一(合成)\n- 要点二(合成)\n\n"
        f"## 引用\n- https://example.invalid/source-a\n- https://example.invalid/source-b\n\n"
        f"## 溯源\n- engine-canary: {session.canary}\n")
    session.record_final(body)
    return _text(body), "stop"


class Handler(BaseHTTPRequestHandler):
    session: _Session   # 由 start() 生成的子类绑定;基类不持有任何金丝雀

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
        self.session.hit()
        message, finish = route(body, self.session)
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
    """起一台 stub。返回 (srv, port);`srv.canary` 与 `srv.session` 见模块文档。

    金丝雀每次现摇,没有"指定取值"的入口——留了那个入口,金丝雀就成了
    可预测的常量,也就不再证明任何因果。
    """
    session = _Session(f"ODR-CANARY-{secrets.token_hex(8).upper()}")
    handler = type("_BoundHandler", (Handler,), {"session": session})
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    srv.session = session
    srv.canary = session.canary
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


if __name__ == "__main__":
    srv, p = start(8899)
    print("fake llm stub on", p, "canary", srv.canary)
    import time
    while True:
        time.sleep(60)
