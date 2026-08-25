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
                usage = dict(s.get("usage") or _USAGE)   # 脚本可注入自定义 usage(R5)
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
                    "usage": usage}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.base_url = f"http://127.0.0.1:{self.srv.server_port}/v1"

    def __enter__(self) -> _FakeOpenAI:
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
    """G6:shim 的 requests 记录只有形状与用量 —— 无消息正文、无任何 key 值。
    记录键闭集逐键枚举(R5 后含 usage 投影;usage 是计量不是内容)。"""
    with _FakeOpenAI([{"text": "hi"}]) as up, \
         DshGptShim(up.base_url, _FAKE_UPSTREAM_KEY, "gpt-test") as shim:
        _post_like_runtime(shim.base_url, dict(_BODY))
        blob = json.dumps(shim.requests, ensure_ascii=False)

    assert _FAKE_UPSTREAM_KEY not in blob and _FAKE_DSH_KEY not in blob
    assert "打个招呼" not in blob, "记录携带了消息正文"
    (rec,) = shim.requests
    assert rec == {"path": "/chat/completions", "model_in": "deepseek-v4-flash",
                   "stream_in": True, "n_messages": 1, "upstream_status": 200,
                   "usage": {"prompt_tokens": 12, "completion_tokens": 5,
                             "total_tokens": 17, "reasoning_tokens": 3}}


def test_g7_usage_details_recorded_only_what_endpoint_said():
    """G7(R5 仪器):端点报什么记什么 —— reasoning 细目入记录;没报缓存
    就**没有键**(不造零:这份记录的用途正是区分"端点没报"与"命中为 0")。
    回程线格式不动(G2 的三键钉照旧管着模型可见面)。"""
    rich = {"prompt_tokens": 1347, "completion_tokens": 18, "total_tokens": 1365,
            "completion_tokens_details": {"reasoning_tokens": 11}}
    bare = {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11}
    with _FakeOpenAI([{"text": "ok", "usage": rich},
                      {"text": "ok", "usage": bare}]) as up, \
            DshGptShim(up.base_url, _FAKE_UPSTREAM_KEY, "gpt-test") as shim:
        _post_like_runtime(shim.base_url, dict(_BODY))
        _post_like_runtime(shim.base_url, dict(_BODY))

    u0, u1 = (r["usage"] for r in shim.requests)
    assert u0["prompt_tokens"] == 1347 and u0["reasoning_tokens"] == 11
    assert "cached_tokens" not in u0 and "prompt_cache_hit_tokens" not in u0
    assert u1 == {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11}


def test_g7b_usage_detail_projection_pure_shapes():
    """G7b(纯函数):openai 嵌套细目与 deepseek 平铺缓存键都认;空细目
    不产键;非数值不入账。"""
    from repoproof.agents.dsh_gpt_shim import usage_detail_projection

    assert usage_detail_projection({}) == {}
    got = usage_detail_projection({
        "prompt_tokens": 10,
        "prompt_tokens_details": {"cached_tokens": 7},
        "prompt_cache_hit_tokens": 5, "prompt_cache_miss_tokens": 5})
    assert got["cached_tokens"] == 7 and got["prompt_cache_hit_tokens"] == 5
    assert got["prompt_cache_miss_tokens"] == 5 and got["prompt_tokens"] == 10
    assert usage_detail_projection({"prompt_tokens_details": {}}) == {}
    assert usage_detail_projection({"prompt_tokens": "many"}) == {}


def test_g8_pre_dispatch_budget_gate_refuses_before_upstream():
    """G8(R6 前置预算闸):已耗(上游报的真值)+ 估计 超上限 → 429
    type=budget_refused,**超额调用不出门**(上游看不到第二发);记录携
    refused_pre_budget/estimate_tokens/cum_prompt_tokens、无 upstream_status。
    动机:DQ-GPT-SHIM-1 两发 gpt-5.5 把 1.8M 的最后一发打完才被 watchdog
    事后杀 —— 溢出那次上游调用是白花的真钱。缺省 max_input_tokens=None
    闸关,既有行为不变(G1-G7 全在 None 下跑)。"""
    big = {"prompt_tokens": 900, "completion_tokens": 5, "total_tokens": 905}
    with _FakeOpenAI([{"text": "ok", "usage": big}]) as up, \
            DshGptShim(up.base_url, _FAKE_UPSTREAM_KEY, "gpt-test",
                       max_input_tokens=1000) as shim:
        s1, _ = _post_like_runtime(shim.base_url, dict(_BODY))
        s2, body2 = _post_like_runtime(shim.base_url, dict(_BODY))

    assert s1 == 200 and s2 == 429
    assert json.loads(body2)["error"]["type"] == "budget_refused"
    assert len(up.requests) == 1, "被拒的调用不许打到上游"
    r1, r2 = shim.requests
    assert "refused_pre_budget" not in r1 and r1["upstream_status"] == 200
    assert r2["refused_pre_budget"] is True
    assert r2["cum_prompt_tokens"] == 900
    assert r2["estimate_tokens"] >= 900, "估计须不低于上次真值(全史重发朝紧)"
    assert "upstream_status" not in r2 and "usage" not in r2
    assert shim.refused_pre_budget == 1


def test_g8b_refusal_attribution_pure_shapes():
    """G8b(纯函数):归因覆写只吃 ok / worker_error:*;watchdog 杀发与
    协议破裂是更硬的事实,不许被拒绝数遮住;零拒绝不覆写。"""
    from repoproof.runner.host_guided import refusal_attribution as ra

    assert ra("ok", 3) == "budget_refused:input_tokens"
    assert ra("worker_error:llm", 1) == "budget_refused:input_tokens"
    assert ra("budget_overrun:input_tokens", 5) == "budget_overrun:input_tokens"
    assert ra("wall_overrun", 2) == "wall_overrun"
    assert ra("worker_protocol_breach", 2) == "worker_protocol_breach"
    assert ra("worker_unexpected", 2) == "worker_unexpected"
    assert ra("ok", 0) == "ok"


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


# ------------------------------------------- GS3:host-run 接线(run_dsh_round)


class _HB:
    """HostBudgets 鸭型替身(与 test_dsh_bridge 同款,total 语义)。"""
    semantics = "total"
    max_rounds = 2
    max_model_calls = 40
    max_commands = 120
    max_patch_files = 8
    max_patch_lines = 800
    max_wall_time_minutes = 3
    max_input_tokens_total = 900_000
    max_output_tokens_total = 120_000


@needs_runtime
def test_gs3_run_dsh_round_with_gpt_shim_end_to_end(tmp_path: Path) -> None:
    """GS3(接线钉,2026-08-20):模块级 run_dsh_round × UPSTREAM_GPT_SHIM。

    证四件事:①shim 生命周期在轮内,编辑器写盘可收割、回执适配纪律不变;
    ②指纹换脸 —— upstream_protocol 与 model=gpt-5.5 都进指纹(M92a 面);
    ③key 纪律 —— 上游只见上游 key,worker 只见 RUNTIME_FAKE_KEY(shim 的
    inbound_fake_key 布尔见证,M92b 面),上游 key 不落回执两件;
    ④job.model=gpt-5.5(非 deepseek 名)走通封存 runtime 到线上。"""
    from repoproof.agents.dsh_bridge import UPSTREAM_GPT_SHIM, treatment_fidelity
    from repoproof.runner.host_guided import run_dsh_round

    ws = tmp_path / "ws"
    ws.mkdir()
    out_file = str(ws / "out.txt")
    with _FakeOpenAI([
        {"tool": "str_replace_editor",
         "args": {"command": "create", "path": out_file, "file_text": "hola\n"}},
        {"text": "done"},
    ]) as up:
        result, info = run_dsh_round(
            workspace=ws, side_dir=tmp_path / "side", prompt="写 out.txt。",
            budgets=_HB(), model_name="gpt-5.5",
            api_base=up.base_url, api_key=_FAKE_UPSTREAM_KEY,
            runtime_root=RT_ROOT, request_timeout_s=60.0,
            upstream_protocol=UPSTREAM_GPT_SHIM)

    # ① 判决面回执与适配纪律
    assert (ws / "out.txt").read_text(encoding="utf-8") == "hola\n"
    assert result.exit_status == "submitted" and result.cost == "UNKNOWN"
    assert info["attribution"] == "ok" and info["session_id"]
    assert info["trace_problems"] == [] and info["selfcheck_problems"] == []
    # ② 指纹换脸:上游真身入指纹,不许扮 deepseek
    assert info["upstream_protocol"] == UPSTREAM_GPT_SHIM
    assert info["fingerprint"]["upstream_protocol"] == UPSTREAM_GPT_SHIM
    assert info["fingerprint"]["model"] == "gpt-5.5"
    # ③ key 纪律:上游只见上游 key;worker 只见假字面量(布尔见证);
    #    上游 key 不落 events 回执
    assert up.requests and all(
        q["auth"] == f"Bearer {_FAKE_UPSTREAM_KEY}" for q in up.requests)
    assert info["shim_requests"] and all(
        s["inbound_fake_key"] for s in info["shim_requests"]), \
        "worker 侧 Authorization 不是假字面量 —— 真 key 漏进了不可信 worker"
    assert _FAKE_UPSTREAM_KEY.encode() not in Path(info["events_path"]).read_bytes()
    # ④ 非 deepseek 模型名全程走通:job.model → runtime → 线上 model_in
    assert all(s["model_in"] == "gpt-5.5" for s in info["shim_requests"])
    assert all(q["body"]["model"] == "gpt-5.5" for q in up.requests)
    # fidelity 九项对着 shim 组合全绿(预注册冻结值 = 同指纹时)
    missing = treatment_fidelity(
        report=info["report"], fingerprint=info["fingerprint"],
        expected_fingerprint=dict(info["fingerprint"]),
        budget=info["budget"], host_budgets=_HB(),
        seen_session_ids=set(), job=info["job"], expected_workspace=ws)
    assert missing == []


@needs_runtime
def test_gs4_pre_budget_gate_full_stack_refuses_and_attributes(
        tmp_path: Path) -> None:
    """GS4(R6 全栈钉):封存 runtime × 前置预算闸 —— 第一发上游调用报
    prompt_tokens=50K(上限 60K,watchdog 事后轴此刻还不会杀),第二发
    被 shim 发前拒(50K+est≥50K > 60K),**超额调用不出门**:上游恰好只
    见 1 次请求;拒绝进 info["shim_refusals"],归因覆写为
    budget_refused:input_tokens。先跑后钉的观察记录(2026-08-21):封存
    runtime 对持续 429 重试 2 次(共 3 次被拒)后自行报错退出 —— 没有
    重试风暴,logical_requests watchdog(上限 40)不会先说话。"""
    from repoproof.agents.dsh_bridge import UPSTREAM_GPT_SHIM
    from repoproof.runner.host_guided import run_dsh_round

    class _HBTiny(_HB):
        max_input_tokens_total = 60_000

    big = {"prompt_tokens": 50_000, "completion_tokens": 5,
           "total_tokens": 50_005}
    ws = tmp_path / "ws"
    ws.mkdir()
    out_file = str(ws / "out.txt")
    with _FakeOpenAI([
        {"tool": "str_replace_editor",
         "args": {"command": "create", "path": out_file, "file_text": "x\n"},
         "usage": big},
    ]) as up:
        result, info = run_dsh_round(
            workspace=ws, side_dir=tmp_path / "side", prompt="写 out.txt。",
            budgets=_HBTiny(), model_name="gpt-5.5",
            api_base=up.base_url, api_key=_FAKE_UPSTREAM_KEY,
            runtime_root=RT_ROOT, request_timeout_s=60.0,
            upstream_protocol=UPSTREAM_GPT_SHIM)

    assert len(up.requests) == 1, "被拒的调用不许打到上游"
    assert info["shim_refusals"] >= 1
    assert info["attribution"] == "budget_refused:input_tokens"
    assert result.exit_status == "dsh:budget_refused:input_tokens"


def test_gs3b_deepseek_admission_fingerprint_would_catch_shim_swap(
        tmp_path: Path) -> None:
    """GS3b(零 runtime):若准入按 deepseek 直连冻结、逐轮却走了 shim,
    fidelity ③ 必须点名指纹不一致 —— 两套真相在批层立刻可见。"""
    from repoproof.agents.dsh_bridge import (
        UPSTREAM_DEEPSEEK,
        UPSTREAM_GPT_SHIM,
        bridge_budget,
        composition_fingerprint,
        treatment_fidelity,
    )

    # 借 test_dsh_bridge 的假封存根构造两份只差 upstream_protocol 的指纹
    from tests.test_dsh_bridge import _HB as _BHB
    from tests.test_dsh_bridge import _report, _runtime_root

    root = _runtime_root(tmp_path)
    fp_shim = composition_fingerprint(root, model="gpt-5.5",
                                      upstream_protocol=UPSTREAM_GPT_SHIM)
    fp_ds = composition_fingerprint(root, model="gpt-5.5",
                                    upstream_protocol=UPSTREAM_DEEPSEEK)
    ws = tmp_path / "ws"
    ws.mkdir()
    missing = treatment_fidelity(
        report=_report(), fingerprint=fp_shim, expected_fingerprint=fp_ds,
        budget=bridge_budget(_BHB()), host_budgets=_BHB(),
        seen_session_ids=set(), job={"workspace": str(ws)},
        expected_workspace=ws)
    assert any("③" in m and "upstream_protocol" in m for m in missing)
