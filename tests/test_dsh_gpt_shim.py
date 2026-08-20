"""DSH→OpenAI 协议适配层(dsh_gpt_shim)的钉死。

分两层:
- G1-G6:shim 单体 —— 假 openai 上游(非流式 JSON),验证换名/剥流式/
  key 只上不下/SSE 线格式与假端点同构/错误透传/记录不携密。
- GS1-GS2(needs_runtime):全栈 —— 真封存 runtime → shim → 假 openai
  上游,证明 runtime 吃得下 shim 合成的 SSE(文本回合 + 工具环真执行)。
  真 GPT 端点的在线探针不在套件里(scripts/dsh_gpt_line_probe.py,出网)。

上游假件与 dsh_fake_provider 的边界同款:只绑 127.0.0.1、只配假 key
字面量、产生的发次不计模型表现。
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from repoproof.agents.dsh_gpt_shim import DshGptShim, synthesize_sse

REPO = Path(__file__).resolve().parents[1]
RT_ROOT = Path.home() / "RepoProofRuntimes" / "rt-dsh-minimal-0.1.0rc6-v1"
SEALED_PY = RT_ROOT / ".venv" / "bin" / "python"

needs_runtime = pytest.mark.skipif(
    not SEALED_PY.exists(),
    reason="封存 runtime 不在本机(scripts/provision_dsh_runtime.py --go)")

_FAKE_DSH_KEY = "sk-canary-invalid-0000"        # runtime 侧假 key(字面量)
_FAKE_UPSTREAM_KEY = "sk-upstream-invalid-9999"  # shim→上游侧假 key(字面量)
_USAGE = {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17,
          "completion_tokens_details": {"reasoning_tokens": 3}}  # 扩展键须被投影掉


class _FakeOpenAI:
    """脚本化**非流式** openai 上游(第 i 次 POST 回 scripts[i])。

    script:{"text": 终答} / {"tool": 名, "args": 参数} / {"status": 500}。
    记录完整请求体与 Authorization 头 —— 这是测试私产,专为断言 key 与
    形状;真上游没有这份记录。"""

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
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                i = len(outer.requests)
                outer.requests.append({"path": self.path, "body": body,
                                       "auth": self.headers.get("Authorization")})
                s = (outer.scripts[i] if i < len(outer.scripts)
                     else {"text": "(脚本尽,兜底终答)"})
                if "status" in s:
                    err = json.dumps({"error": {"message": "上游拒答",
                                                "type": "server_error"}}).encode()
                    self.send_response(int(s["status"]))
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(err)))
                    self.end_headers()
                    self.wfile.write(err)
                    return
                if "tool" in s:
                    msg = {"role": "assistant", "content": None, "tool_calls": [
                        {"id": f"call_up_{i}", "type": "function",
                         "function": {"name": s["tool"],
                                      "arguments": json.dumps(s["args"],
                                                              ensure_ascii=False)}}]}
                    finish = "tool_calls"
                else:
                    msg = {"role": "assistant", "content": s["text"]}
                    finish = "stop"
                resp = json.dumps({
                    "id": "cmpl-up", "object": "chat.completion", "created": 1,
                    "model": body.get("model"),
                    "choices": [{"index": 0, "message": msg,
                                 "finish_reason": finish}],
                    "usage": dict(_USAGE)}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.srv.server_port}/v1"

    def __enter__(self) -> "_FakeOpenAI":
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def _post_like_runtime(shim_base: str, body: dict) -> tuple[int, str]:
    """模拟 runtime 的入站请求:deepseek 路径(无 /v1)+ 假 key + stream:true。"""
    req = urllib.request.Request(
        f"{shim_base}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_FAKE_DSH_KEY}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:  # 非 200 也要读体
        return e.code, e.read().decode("utf-8")


def _sse_chunks(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            out.append(json.loads(line[len("data: "):]))
    return out


_BODY = {"model": "deepseek-v4-flash", "stream": True,
         "stream_options": {"include_usage": True},
         "messages": [{"role": "user", "content": "打个招呼。"}]}


def test_g1_model_swapped_stream_stripped_key_only_upstream():
    """G1:上游看到的是换过名、剥了流式旗标、带上游 key 的非流式请求;
    runtime 侧的假 key 不透传。"""
    with _FakeOpenAI([{"text": "hi"}]) as up, \
         DshGptShim(up.base_url, _FAKE_UPSTREAM_KEY, "gpt-test") as shim:
        status, _ = _post_like_runtime(shim.base_url, dict(_BODY))

    assert status == 200
    (req,) = up.requests
    assert req["path"] == "/v1/chat/completions"
    assert req["body"]["model"] == "gpt-test"
    assert "stream" not in req["body"] and "stream_options" not in req["body"]
    assert req["auth"] == f"Bearer {_FAKE_UPSTREAM_KEY}"
    assert _FAKE_DSH_KEY not in json.dumps(req), "runtime 侧 key 透传到了上游"


def test_g2_text_turn_sse_shape_matches_the_pinned_wire_format():
    """G2:合成 SSE 与假端点线格式同构 —— 首块 role+content,终块空 delta
    + finish + 三键 usage(扩展键投影掉),[DONE] 收尾,model 回填上游真名。"""
    with _FakeOpenAI([{"text": "你好,收到。"}]) as up, \
         DshGptShim(up.base_url, _FAKE_UPSTREAM_KEY, "gpt-test") as shim:
        status, text = _post_like_runtime(shim.base_url, dict(_BODY))

    assert status == 200 and text.rstrip().endswith("data: [DONE]")
    first, last = _sse_chunks(text)
    assert first["object"] == "chat.completion.chunk"
    assert first["model"] == "gpt-test", "model 字段必须是上游真名,不许扮 deepseek"
    assert first["choices"][0]["delta"] == {"role": "assistant", "content": "你好,收到。"}
    assert last["choices"][0] == {"index": 0, "delta": {}, "finish_reason": "stop"}
    assert last["usage"] == {"prompt_tokens": 12, "completion_tokens": 5,
                             "total_tokens": 17}, "usage 必须恰为三键 snake_case"


def test_g3_tool_calls_mapped_with_index():
    """G3:tool_calls 带 index 映射(runtime 按 index/step 归组累加参数)。"""
    with _FakeOpenAI([{"tool": "bash", "args": {"command": "echo hi"}}]) as up, \
         DshGptShim(up.base_url, _FAKE_UPSTREAM_KEY, "gpt-test") as shim:
        _, text = _post_like_runtime(shim.base_url, dict(_BODY))

    first, last = _sse_chunks(text)
    (call,) = first["choices"][0]["delta"]["tool_calls"]
    assert call["index"] == 0 and call["type"] == "function"
    assert call["function"]["name"] == "bash"
    assert json.loads(call["function"]["arguments"]) == {"command": "echo hi"}
    assert last["choices"][0]["finish_reason"] == "tool_calls"


def test_g4_upstream_error_passes_through_with_status():
    """G4:上游 500 原状态码透传 —— 重试形状归 runtime 既有逻辑。"""
    with _FakeOpenAI([{"status": 500}]) as up, \
         DshGptShim(up.base_url, _FAKE_UPSTREAM_KEY, "gpt-test") as shim:
        status, text = _post_like_runtime(shim.base_url, dict(_BODY))

    assert status == 500 and "error" in json.loads(text)


def test_g5_synthesize_sse_edge_shapes():
    """G5(纯函数):空终答也有 content 位;缺 finish 回落 stop;usage 缺键补 0。"""
    payload = synthesize_sse({"choices": [{"message": {}}]}, model="gpt-test")
    first, last = _sse_chunks(payload.decode())
    assert first["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    assert last["choices"][0]["finish_reason"] == "stop"
    assert last["usage"] == {"prompt_tokens": 0, "completion_tokens": 0,
                             "total_tokens": 0}


def test_g6_shim_records_carry_no_secrets_no_bodies():
    """G6:shim 的 requests 记录只有形状 —— 无消息正文、无任何 key 值。"""
    with _FakeOpenAI([{"text": "hi"}]) as up, \
         DshGptShim(up.base_url, _FAKE_UPSTREAM_KEY, "gpt-test") as shim:
        _post_like_runtime(shim.base_url, dict(_BODY))
        blob = json.dumps(shim.requests, ensure_ascii=False)

    assert _FAKE_UPSTREAM_KEY not in blob and _FAKE_DSH_KEY not in blob
    assert "打个招呼" not in blob, "记录携带了消息正文"
    (rec,) = shim.requests
    assert rec == {"path": "/chat/completions", "model_in": "deepseek-v4-flash",
                   "stream_in": True, "n_messages": 1, "upstream_status": 200}


# ---------------------------------------------------------------- 全栈(封存 runtime)
def _run_full_stack(tmp: Path, scripts: list[dict], prompt: str):
    from repoproof.agents.dsh_backend import DshBudget, run_dsh_worker

    ws = tmp / "ws"
    ws.mkdir(exist_ok=True)
    job = {"prompt": prompt, "workspace": str(ws),
           "events_path": str(tmp / "ev" / "events.jsonl"),
           "session_root": str(tmp / "sess"),
           "cordis": str(RT_ROOT / "config" / "minimal.upstream.0.1.0rc6.cordis.yml"),
           "request_timeout_seconds": 60.0}
    with _FakeOpenAI(scripts) as up, \
         DshGptShim(up.base_url, _FAKE_UPSTREAM_KEY, "gpt-test") as shim:
        job["env"] = {"DEEPSEEK_BASE_URL": shim.base_url}
        r = run_dsh_worker(job, worker_python=str(SEALED_PY),
                           budget=DshBudget(max_wall_seconds=180,
                                            max_logical_requests=20),
                           extra_env={"DEEPSEEK_API_KEY": _FAKE_DSH_KEY})
    return r, up, shim


@needs_runtime
def test_gs1_text_turn_through_real_runtime(tmp_path: Path) -> None:
    """GS1:真 runtime 吃得下 shim 合成的 SSE —— 文本回合全栈干净,
    usage 与上游读数逐字可对账。"""
    r, up, shim = _run_full_stack(tmp_path, [{"text": "你好,收到。"}], "打个招呼。")

    assert (r.attribution, r.killed, r.orphan_count) == ("ok", False, 0), \
        (r.attribution, r.stderr_tail[-300:])
    assert r.result["ok"] is True
    assert r.result["finish_reason"] == "completed"
    assert r.result["final_response"] == "你好,收到。"
    assert r.trace.ok, r.trace.problems
    assert r.trace.usage_totals == {"input_tokens": 12, "output_tokens": 5}
    assert up.requests[0]["body"]["model"] == "gpt-test"


@needs_runtime
def test_gs2_tool_loop_really_executes_through_shim(tmp_path: Path) -> None:
    """GS2:工具环全栈 —— bash 真执行,观察回传给上游第二问。"""
    r, up, shim = _run_full_stack(tmp_path, [
        {"tool": "bash", "args": {"command": "echo RP_SHIM_$((6*7))"}},
        {"text": "跑完了。"},
    ], "跑一条命令。")

    assert (r.attribution, r.killed, r.orphan_count) == ("ok", False, 0), \
        (r.attribution, r.stderr_tail[-300:])
    assert r.result["ok"] is True and r.trace.ok, r.trace.problems
    assert len(up.requests) == 2
    obs = [m for m in up.requests[1]["body"]["messages"] if m.get("role") == "tool"]
    assert obs and "RP_SHIM_42" in obs[0]["content"], \
        f"必须是真执行不是回显:{obs and obs[0]['content']!r}"
    assert r.trace.counters["logical_requests"] == 2
    assert r.trace.usage_totals == {"input_tokens": 24, "output_tokens": 10}
