"""脚本化 SSE 假 DeepSeek 端点(DSH 阶段 8 —— F0-经-dsh 与 AR 彩排的载具)。

从 C 系金丝雀的测试夹具晋级为可复用件:B-dsh 臂的 F0 四形电池与端到端
彩排都要"真 worker 环 + 脚本化 provider",这不再只是测试的私产。

**边界(与金丝雀同款,一字不松)**:
- 只绑 127.0.0.1 端口 0(本机回环,不出网 —— 这不是 egress);
- 只配假 key 字面量(如 "sk-canary-invalid-0000")使用,真 key 永不进它;
- 它产生的发次一律不计模型表现(fake/AR 语义,SMOKE_MODEL_PREFIX 扣除)。

script 形态(第 i 次 POST 回 scripts[i]):
    {"text": 终答}                     assistant 文本 + finish=stop
    {"tool": 工具名, "args": 参数}      tool_call + finish=tool_calls
    {"status": 500}                    HTTP 错误(重试形状的靶子)
    {"garbage": True}                  畸形 SSE(快败形状的靶子)
    {"hang": 秒}                       收下请求不回话(墙钟刀的靶子)
脚本用尽后兜底回终答 —— 宁可让断言红,不让 runtime 空转。
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 每次计费的固定读数 —— **SSE 线格式**(OpenAI 风 snake_case;runtime 收进
# 事件后才转 camelCase inputTokens/outputTokens)。这一格式是打崩点:搬移时
# 凭记忆写成事件侧 camelCase,runtime 的 chunk 解析当场崩(2026-08-17 单变量
# 实测:turn/end error "assistant/chunk carries non-JSON-serializable data",
# 零重试零后续请求)。线格式一字不许改。
_USAGE = {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}


def _chunk(delta: dict, finish: str | None = None, usage: dict | None = None) -> str:
    # "created" 保持与金丝雀线上原样(单变量实测:缺它 runtime 容忍,
    # 不是打崩点 —— 留着是忠实线格式,不是执法项)。
    c = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "created": 1,
         "model": "deepseek-v4-flash",
         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        c["usage"] = usage
    return "data: " + json.dumps(c, ensure_ascii=False) + "\n\n"


class FakeDeepSeekProvider:
    """脚本化 SSE 假端点。Threading 版:挂死的 handler 不得堵住 shutdown。"""

    def __init__(self, scripts: list[dict]) -> None:
        self.scripts = list(scripts)
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # noqa: N802
                pass

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n).decode("utf-8", "replace")
                i = len(outer.requests)
                outer.requests.append(
                    {"path": self.path, "body": json.loads(body or "{}")})
                s = (outer.scripts[i] if i < len(outer.scripts)
                     else {"text": "（脚本尽,兜底终答）"})
                if "hang" in s:
                    time.sleep(float(s["hang"]))
                    return          # 不写任何响应,连接就地掐断
                if "status" in s:
                    err = json.dumps({"error": {"message": "canary 拒答",
                                                "type": "server_error"}}).encode()
                    self.send_response(int(s["status"]))
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
                    return
                if s.get("garbage"):
                    payload = b"data: {\xff\xfe broken json !!\n\ndata: [DONE]\n\n"
                elif "tool" in s:
                    first = _chunk({"role": "assistant", "tool_calls": [
                        {"index": 0, "id": f"call_fake_{i}", "type": "function",
                         "function": {"name": s["tool"],
                                      "arguments": json.dumps(s["args"],
                                                              ensure_ascii=False)}}]})
                    last = _chunk({}, finish="tool_calls", usage=_USAGE)
                    payload = (first + last + "data: [DONE]\n\n").encode()
                else:
                    first = _chunk({"role": "assistant", "content": s["text"]})
                    last = _chunk({}, finish="stop", usage=_USAGE)
                    payload = (first + last + "data: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.srv.server_port}"

    def __enter__(self) -> "FakeDeepSeekProvider":
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a) -> None:
        self.srv.shutdown()
        self.srv.server_close()
