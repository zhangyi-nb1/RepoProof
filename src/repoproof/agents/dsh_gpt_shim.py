"""DSH→OpenAI 兼容端点的协议适配层(GPT×DSH,2026-08-20)。

DSH runtime 只说 DeepSeek 线协议:`POST {base}/chat/completions`(无 /v1)、
请求体带 `"stream": true`(C2 钉死)、应答须为 SSE、usage 在终块
snake_case。本地 GPT 端点说 OpenAI 兼容协议(base 自带 /v1,支持非流式)。
本模块起一个 127.0.0.1 回环 shim 居中转译:

    DSH runtime ──deepseek 线(SSE)──▶ shim ──openai 非流式──▶ GPT 端点
                ◀──合成 SSE(金丝雀钉死的线格式)──┘

设计决定:
- **上游走非流式**,回程由 shim 合成 SSE。线格式是打崩点(2026-08-17
  单变量实测:usage 位置错一格 runtime 当场崩)——合成让输出形状与
  `dsh_fake_provider` 被 C 系金丝雀验证过的格式**同构**,不赌上游 SSE 方言。
- **模型名映射**:runtime 发 deepseek-v4-*(cordis 视角),shim 替换成
  上游真模型;回程 chunk 的 model 字段回填上游真名 —— 不许把 GPT 的输出
  记成 deepseek 的脸。
- **key 纪律**:上游 key 只经构造参数→请求头;不落日志、不进 requests
  记录、不回显。runtime 侧的入站 Authorization(假 key 字面量)**不透传**。
- **错误透传**:上游非 200 → 原状态码 + JSON error 回给 runtime(重试/
  快败形状归 runtime 既有逻辑,shim 不自作主张)。
- 只绑 127.0.0.1 端口 0 —— 回环不出网;出网的是 shim 对 GPT 端点的
  上游请求(provisioning/推理属正常通道)。

边界:这是**协议适配件**(model_profile 面,与 deepseek_native 同类),
不触裁决面。GPT×DSH 组合未经 DQ 资格批 —— qualified 只背书 deepseek
组合;任何计分批之前须走自己的资格流程与预注册。
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 回程 usage 只投影这三键 —— 与假端点线格式一致;上游的扩展键
# (completion_tokens_details 等)不透传,runtime 没为它们验证过。
_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def usage_detail_projection(usage: dict) -> dict:
    """上游 usage → host 侧记录投影(R5 仪器,2026-08-21)。

    只记端点**实际报告**的键,缺席即缺席、不造零 —— 这份记录的用途正是
    区分"端点没报缓存"与"缓存命中为 0"(DQ-GPT-SHIM-1 附录二的跨端点
    usage 语义警示要靠它前向收口)。认三类形状:扁平标准键、openai 嵌套
    细目(prompt_tokens_details.cached_tokens / completion_tokens_details
    .reasoning_tokens)、deepseek 平铺缓存键。2026-08-21 线上探针实测:
    本地 GPT 端点报 reasoning_tokens(18 个补全里 11 个是推理),同前缀
    重打第二发也**不报任何 prompt 缓存细目** —— 该端点输入是全价输入。
    仅记录,不改回程线格式(模型可见面零变动)。
    """
    out: dict = {}
    for k in ("prompt_tokens", "completion_tokens", "total_tokens",
              "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        if isinstance(usage.get(k), (int, float)):
            out[k] = int(usage[k])
    pd = usage.get("prompt_tokens_details")
    if isinstance(pd, dict) and isinstance(pd.get("cached_tokens"), (int, float)):
        out["cached_tokens"] = int(pd["cached_tokens"])
    cd = usage.get("completion_tokens_details")
    if isinstance(cd, dict) and isinstance(cd.get("reasoning_tokens"), (int, float)):
        out["reasoning_tokens"] = int(cd["reasoning_tokens"])
    return out

# shim 在链路里时,runtime(不可信 worker)只拿这个假字面量当 DEEPSEEK_API_KEY
# —— 真 key 永不进 worker 进程环境(M92b 面)。host_guided.run_dsh_round 与
# 全栈测试同源引用,不各写各的字面量。
RUNTIME_FAKE_KEY = "sk-dsh-shim-loopback-0000"


def _sse_chunk(model: str, delta: dict, finish: str | None = None,
               usage: dict | None = None) -> str:
    c = {"id": "chatcmpl-shim", "object": "chat.completion.chunk", "created": 1,
         "model": model,
         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        c["usage"] = usage
    return "data: " + json.dumps(c, ensure_ascii=False) + "\n\n"


def synthesize_sse(upstream: dict, *, model: str) -> bytes:
    """OpenAI 非流式应答 → deepseek 线 SSE(与 dsh_fake_provider 同构)。

    纯函数,离线可测。首块带 role+content(和/或 tool_calls,含 index),
    终块空 delta + finish + 三键 usage,`data: [DONE]` 收尾。"""
    choice = (upstream.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    finish = choice.get("finish_reason") or "stop"
    usage_in = upstream.get("usage") or {}
    usage = {k: int(usage_in.get(k, 0) or 0) for k in _USAGE_KEYS}

    delta: dict = {"role": "assistant"}
    if msg.get("content"):
        delta["content"] = msg["content"]
    calls = msg.get("tool_calls") or []
    if calls:
        delta["tool_calls"] = [
            {"index": i,
             "id": c.get("id") or f"call_shim_{i}",
             "type": c.get("type") or "function",
             "function": {"name": (c.get("function") or {}).get("name"),
                          "arguments": (c.get("function") or {}).get("arguments", "")}}
            for i, c in enumerate(calls)]
    elif "content" not in delta:
        delta["content"] = ""      # 空终答也要有内容位,不让 runtime 读到裸 role

    first = _sse_chunk(model, delta)
    last = _sse_chunk(model, {}, finish=finish, usage=usage)
    return (first + last + "data: [DONE]\n\n").encode("utf-8")


class DshGptShim:
    """回环协议 shim。`with DshGptShim(...) as s: job.env = {"DEEPSEEK_BASE_URL": s.base_url}`。

    requests 记录只存形状(路径/入站模型/stream 旗标/消息数/上游状态码),
    不存消息正文、不存任何请求头 —— key 与提示都不落在这份记录里。"""

    def __init__(self, upstream_base: str, upstream_key: str, upstream_model: str,
                 *, timeout_s: float = 240.0,
                 expected_inbound_key: str | None = None) -> None:
        self.upstream_base = upstream_base.rstrip("/")
        self._key = upstream_key
        self.upstream_model = upstream_model
        self.timeout_s = timeout_s
        # 入站 key 见证(值级无害):给定期望假字面量时,每条记录多一个布尔
        # `inbound_fake_key` —— False 意味着 runtime 拿到的不是假 key,真 key
        # 漏进了不可信 worker(M92b 面)。只记布尔,不存任何 key 值。
        self._expected_inbound = expected_inbound_key
        self.requests: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # noqa: N802 —— 不落访问日志
                pass

            def _reply(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n).decode("utf-8", "replace") or "{}")
                except json.JSONDecodeError:
                    self._reply(400, b'{"error":{"message":"shim: bad json"}}',
                                "application/json")
                    return
                rec = {"path": self.path,
                       "model_in": body.get("model"),
                       "stream_in": body.get("stream"),
                       "n_messages": len(body.get("messages") or [])}
                if outer._expected_inbound is not None:
                    auth = self.headers.get("Authorization") or ""
                    rec["inbound_fake_key"] = (
                        auth == f"Bearer {outer._expected_inbound}")
                outer.requests.append(rec)
                # deepseek 线 → openai 非流式:剥流式旗标、换模型名。
                body.pop("stream", None)
                body.pop("stream_options", None)
                body["model"] = outer.upstream_model
                status, payload, ctype, urec = outer._call_upstream(body)
                rec["upstream_status"] = status
                if urec:
                    rec["usage"] = urec
                self._reply(status, payload, ctype)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.srv.server_port}"

    # ---- 上游调用(唯一持 key 的路径;key 不出这个函数)----
    def _call_upstream(self, body: dict) -> tuple[int, bytes, str, dict | None]:
        req = urllib.request.Request(
            f"{self.upstream_base}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                upstream = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                json.loads(raw.decode("utf-8"))
                return e.code, raw, "application/json", None
            except Exception:
                err = json.dumps({"error": {"message": f"shim upstream http {e.code}",
                                            "type": "upstream_error"}}).encode()
                return e.code, err, "application/json", None
        except Exception as e:  # 超时/连接失败 —— 502,消息不带任何值内容
            err = json.dumps({"error": {"message": f"shim upstream unreachable: "
                                                   f"{type(e).__name__}",
                                        "type": "upstream_unreachable"}}).encode()
            return 502, err, "application/json", None
        return 200, synthesize_sse(upstream, model=self.upstream_model), \
            "text/event-stream", usage_detail_projection(upstream.get("usage") or {})

    def __enter__(self) -> "DshGptShim":
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a) -> None:
        self.srv.shutdown()
        self.srv.server_close()
