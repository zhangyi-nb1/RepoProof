"""DSH 金丝雀 C1-C7(DSH 阶段 6;C8-C15 随后续窗口逐条落地)。

**冻结判据**:

- C1 **版本匹配**:封存 venv 里 SDK 与 runtime 的 importlib 版本必须都是
  钉住的 0.1.0rc6。反例:venv 被 pip 升级过一枚,行为漂移全算到模型头上。
- C2 **text-only turn 全栈**:SSE 假端点喂流式回包,整链归因 ok、
  finish=completed、final_response 逐字、trace 对账平、usage_totals 与假
  端点计费逐字相等(可对账)、零孤儿。
- C3 **单次 Bash 真执行**:tool_call 的命令必须真的跑(以 $((6*7))→42 为
  证),结果以 role=tool 回传给第 2 次调用;两次调用都被数上(request/
  header 只发首枚 —— E5 修正的活体面)。反例:观察是回显不是执行。
- C4 **多步顺序**:两条命令按序执行,第 3 次调用的消息里两个观察齐全
  且序不乱。反例:并发乱序或丢观察。
- C5 **持久 shell**:第 1 步赋的变量第 2 步还在(同一壳)。反例:每步
  新起 shell,"persistent-bash" 名不副实,多步任务的中间态全蒸发。
- C6 **editor 四命令**:create/view/str_replace/insert 逐个真落盘,终态
  文件内容逐字节可预测。反例:str_replace 匹配了却没写回。
- C7 **session 隔离**:A 发的 shell 变量与文件,B 发一概看不见;两发
  session id 互异。反例:共享守护 shell,跨发状态互渗,发次不再独立。
- C8 **provider 5xx 的形状**(实测钉):HTTP 500 重试恰 2 次(共 3 个
  POST)后 turn 报错;worker 协议面仍干净(退 0、idle、对账平),
  retries=2 / errored_turns=1 / attempts=3 —— E5 场景 b 的活体。反例:
  重试不入账,失败风暴读成"模型只调了一次"。
- C9 **畸形回包快败**(实测钉):200 但 SSE 载荷坏 → 零重试立即报错
  (协议破坏不重试)。反例:坏载荷也重试 —— 挂死在毒响应上。
- C10 **挂死吃墙钟刀**:provider 收下请求永不回话 → 外部墙钟刀在限内
  落下,killed、wall_overrun、零孤儿。SDK 无内建墙钟,这把刀是唯一的刀。
- C11 **不动手则零变更**:纯文本回合后 workspace 逐字节原样。反例:
  runtime 自己留垃圾 —— diff 采收会把非模型变更算到模型头上。
- C12 **动手则变更可采**:模型 bash 写的文件在 workspace 落盘可见。
- C13 **假 PASS 无通道**:final_response 喊"PASS"改变不了任何账面;
  result 键集恰为协议清单,没有 verdict/score/pass 形状的键可供上游误读。
- C14 **DSH 自留 JSONL 不可信也不被信**:篡改 session_root 下的会话
  JSONL,可信汇(host events)一个字节不动,读数不变。
- C15 **终态双计活体形状**:向真 trace 追加两条伪造的带 usage turn/end
  → "终态双计"点名、不累加、trace 不 ok(M84a/E3 的活体面)。

**协议事实**(2026-08-17 实测):`POST {base}/chat/completions`(无 /v1),
强制 SSE;工具回传 {"role":"tool","tool_call_id","content"};usage 在
assistant/message(camelCase);request/header 仅首次调用发射。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from repoproof.agents.dsh_backend import DshBudget, run_dsh_worker
from repoproof.agents.dsh_events import normalize

REPO = Path(__file__).resolve().parents[1]
RT_ROOT = Path.home() / "RepoProofRuntimes" / "rt-dsh-minimal-0.1.0rc6-v1"
SEALED_PY = RT_ROOT / ".venv" / "bin" / "python"

needs_runtime = pytest.mark.skipif(
    not SEALED_PY.exists(),
    reason="封存 runtime 不在本机(scripts/provision_dsh_runtime.py --go)")

_FAKE_KEY = "sk-canary-invalid-0000"   # 字面假值,非任何真实凭据
_USAGE = {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}


@needs_runtime
def test_c1_sdk_and_runtime_versions_match_pins() -> None:
    out = subprocess.run(
        [str(SEALED_PY), "-c",
         "import importlib.metadata as m;"
         "print(m.version('deepseek-harness-sdk'));"
         "print(m.version('deepseek-harness-runtime-bin'))"],
        capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.split() == ["0.1.0rc6", "0.1.0rc6"]


def _chunk(delta: dict, finish=None, usage=None) -> str:
    c = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "created": 1,
         "model": "deepseek-v4-flash",
         "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        c["usage"] = usage
    return "data: " + json.dumps(c, ensure_ascii=False) + "\n\n"


class _FakeDeepSeek:
    """脚本化 SSE 假端点:第 i 次 POST 回 scripts[i](127.0.0.1 独占,
    不出网)。script:{"text": 终答} / {"tool": 工具名, "args": 参数} /
    {"status": 500}(HTTP 错误)/ {"garbage": True}(畸形 SSE)/
    {"hang": 秒}(收下请求不回话 —— 墙钟刀的靶子)。脚本用尽后兜底回
    终答 —— 宁可让断言红,不让 runtime 空转。Threading 版:挂死的
    handler 不得堵住 shutdown(单线程版会死等)。"""

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

    def __enter__(self) -> "_FakeDeepSeek":
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def _run(tmp: Path, scripts: list[dict], prompt: str = "做点事。",
         budget: DshBudget | None = None, request_timeout: float = 60.0):
    """一发 = 新 workspace + 新 fake + 新 worker。返回 (report, fake, job)。"""
    ws = tmp / "ws"
    ws.mkdir(exist_ok=True)
    job = {"prompt": prompt, "workspace": str(ws),
           "events_path": str(tmp / "ev" / "events.jsonl"),
           "session_root": str(tmp / "sess"),
           "cordis": str(RT_ROOT / "config" / "minimal.upstream.0.1.0rc6.cordis.yml"),
           "request_timeout_seconds": request_timeout}
    with _FakeDeepSeek(scripts) as fake:
        job["env"] = {"DEEPSEEK_BASE_URL": fake.base_url}
        r = run_dsh_worker(job, worker_python=SEALED_PY,
                           budget=budget or DshBudget(max_wall_seconds=180,
                                                      max_logical_requests=20),
                           extra_env={"DEEPSEEK_API_KEY": _FAKE_KEY})
    return r, fake, job


def _tool_msgs(fake: "_FakeDeepSeek", req_index: int = -1) -> list[dict]:
    msgs = fake.requests[req_index]["body"]["messages"]
    return [m for m in msgs if m.get("role") == "tool"]


def _assert_clean(r) -> None:
    assert (r.attribution, r.killed, r.orphan_count) == ("ok", False, 0), \
        (r.attribution, r.stderr_tail[-300:])
    assert r.result["finish_reason"] == "completed"
    assert r.trace.ok, r.trace.problems
    assert r.selfcheck_problems == []


@needs_runtime
def test_c2_text_only_turn_full_stack(tmp_path: Path) -> None:
    r, fake, job = _run(tmp_path, [{"text": "你好,收到。"}], prompt="打个招呼。")
    assert fake.requests[0]["path"] == "/chat/completions"
    assert fake.requests[0]["body"]["stream"] is True
    _assert_clean(r)
    assert r.result["final_response"] == "你好,收到。"
    assert r.trace.usage_totals == {"input_tokens": 12, "output_tokens": 5}, \
        "与假端点计费必须逐字相等 —— 可对账"
    assert r.trace.counters["logical_requests"] == 1
    size = Path(job["events_path"]).stat().st_size
    time.sleep(0.6)
    assert Path(job["events_path"]).stat().st_size == size, "返回后不得再增长"


@needs_runtime
def test_c3_single_bash_really_executes(tmp_path: Path) -> None:
    r, fake, _ = _run(tmp_path, [
        {"tool": "bash", "args": {"command": "echo RP_C3_$((6*7))"}},
        {"text": "跑完了。"},
    ])
    _assert_clean(r)
    assert len(fake.requests) == 2
    (obs,) = _tool_msgs(fake)
    assert "RP_C3_42" in obs["content"], f"必须是真执行不是回显:{obs['content']!r}"
    assert obs["tool_call_id"] == "call_fake_0"
    # E5 修正的活体面:header 只发首枚,但两次调用都被数上
    assert r.trace.counters["request_headers"] == 1
    assert r.trace.counters["logical_requests"] == 2
    assert r.trace.usage_totals == {"input_tokens": 24, "output_tokens": 10}
    kinds = [rec.get("type") for rec in r.trace.records]
    assert "tool/call" in kinds and "tool/result" in kinds


@needs_runtime
def test_c4_multi_step_bash_in_order(tmp_path: Path) -> None:
    r, fake, _ = _run(tmp_path, [
        {"tool": "bash", "args": {"command": "echo STEP_A1"}},
        {"tool": "bash", "args": {"command": "echo STEP_B2"}},
        {"text": "两步跑完。"},
    ])
    _assert_clean(r)
    assert len(fake.requests) == 3
    obs = _tool_msgs(fake)          # 第 3 次调用应见两个观察,且序不乱
    assert len(obs) == 2
    assert "STEP_A1" in obs[0]["content"] and "STEP_B2" in obs[1]["content"]
    assert r.trace.counters["logical_requests"] == 3


@needs_runtime
def test_c5_persistent_shell_state(tmp_path: Path) -> None:
    r, fake, _ = _run(tmp_path, [
        {"tool": "bash", "args": {"command": "RP_CANARY=xyz42"}},
        {"tool": "bash", "args": {"command": "echo RP_CANARY=[$RP_CANARY]"}},
        {"text": "查完了。"},
    ])
    _assert_clean(r)
    obs = _tool_msgs(fake)
    assert "RP_CANARY=[xyz42]" in obs[1]["content"], \
        f"变量没活过第 2 步 —— 壳不持久:{obs[1]['content']!r}"


@needs_runtime
def test_c6_editor_view_create_replace_insert(tmp_path: Path) -> None:
    note = str(tmp_path / "ws" / "note.txt")
    r, fake, _ = _run(tmp_path, [
        {"tool": "str_replace_editor",
         "args": {"command": "create", "path": note, "file_text": "alpha\nbeta\n"}},
        {"tool": "str_replace_editor", "args": {"command": "view", "path": note}},
        {"tool": "str_replace_editor",
         "args": {"command": "str_replace", "path": note,
                  "old_str": "alpha", "new_str": "gamma"}},
        {"tool": "str_replace_editor",
         "args": {"command": "insert", "path": note,
                  "insert_line": 1, "new_str": "delta"}},
        {"text": "编辑完。"},
    ])
    _assert_clean(r)
    assert len(fake.requests) == 5
    obs = _tool_msgs(fake)
    assert "alpha" in obs[1]["content"] and "beta" in obs[1]["content"], \
        f"view 必须给出 create 后的内容:{obs[1]['content']!r}"
    final = Path(note).read_text(encoding="utf-8")
    assert final == "gamma\ndelta\nbeta\n", f"终态不可预测:{final!r}"


@needs_runtime
def test_c7_sessions_do_not_leak_state(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    ra, _, _ = _run(a, [
        {"tool": "bash", "args": {"command": "RP_LEAK=sekret777; touch leaked_a.txt"}},
        {"text": "A 完。"},
    ])
    _assert_clean(ra)
    rb, fb, _ = _run(b, [
        {"tool": "bash", "args": {"command": "echo RP_LEAK=[$RP_LEAK]; ls"}},
        {"text": "B 完。"},
    ])
    _assert_clean(rb)
    (obs_b,) = _tool_msgs(fb)
    assert "RP_LEAK=[]" in obs_b["content"], \
        f"A 的 shell 变量渗进了 B:{obs_b['content']!r}"
    assert "sekret777" not in obs_b["content"]
    assert "leaked_a.txt" not in obs_b["content"], "A 的文件出现在 B 的 workspace"
    assert ra.result["session_id"] != rb.result["session_id"]


def _snapshot(ws: Path) -> dict:
    return {str(p.relative_to(ws)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(ws.rglob("*")) if p.is_file()}


@needs_runtime
def test_c8_provider_500_retried_twice_then_errored_turn(tmp_path: Path) -> None:
    r, fake, _ = _run(tmp_path, [{"status": 500}] * 8)
    # worker 协议面干净:退 0、自报诚实、对账平 —— 错在 session 不在 worker
    assert (r.attribution, r.exit_code, r.killed, r.orphan_count) == ("ok", 0, False, 0)
    assert r.result["ok"] is True and r.result["finish_reason"] == "error"
    assert r.trace.ok, r.trace.problems
    assert len(fake.requests) == 3, "实测:500 重试恰 2 次(共 3 个 POST)"
    c = r.trace.counters
    assert (c["retries"], c["errored_turns"]) == (2, 1)
    assert (c["logical_requests"], c["llm_attempts"]) == (1, 3), \
        "E5 场景 b 的活体:1 个失败周期,3 次物理尝试"


@needs_runtime
def test_c9_malformed_sse_fails_fast_no_retry(tmp_path: Path) -> None:
    r, fake, _ = _run(tmp_path, [{"garbage": True}] * 8)
    assert (r.attribution, r.exit_code) == ("ok", 0)
    assert r.result["finish_reason"] == "error"
    assert r.trace.ok, r.trace.problems
    assert len(fake.requests) == 1, "实测:坏载荷零重试,快败"
    c = r.trace.counters
    assert (c["retries"], c["errored_turns"]) == (0, 1)
    assert (c["logical_requests"], c["llm_attempts"]) == (1, 1)


@needs_runtime
def test_c10_hung_provider_eats_wall_knife(tmp_path: Path) -> None:
    t0 = time.monotonic()
    r, fake, job = _run(tmp_path, [{"hang": 30}],
                        budget=DshBudget(max_wall_seconds=6.0),
                        request_timeout=60.0)   # runtime 自身超时被推远:刀必须是外部的
    took = time.monotonic() - t0
    assert r.attribution == "wall_overrun" and r.killed
    assert r.orphan_count == 0
    assert took < 15, f"刀没在限内落下({took:.1f}s)"
    # 杀完不许有进程再动可信汇
    size = Path(job["events_path"]).stat().st_size
    time.sleep(1.0)
    assert Path(job["events_path"]).stat().st_size == size


@needs_runtime
def test_c11_no_action_no_workspace_change(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "seed.txt").write_text("原样\n", encoding="utf-8")
    before = _snapshot(ws)
    r, _, _ = _run(tmp_path, [{"text": "看了一眼,不需要动手。"}])
    _assert_clean(r)
    assert _snapshot(ws) == before, "模型没动手,workspace 却变了 —— 有非模型变更混入"


@needs_runtime
def test_c12_model_written_file_is_harvestable(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    before = _snapshot(ws)
    r, _, _ = _run(tmp_path, [
        {"tool": "bash", "args": {"command": "echo made-by-model > out.txt"}},
        {"text": "写完了。"},
    ])
    _assert_clean(r)
    after = _snapshot(ws)
    assert (ws / "out.txt").read_text(encoding="utf-8") == "made-by-model\n"
    assert set(after) - set(before) == {"out.txt"}, \
        f"变更应恰为模型写的那一个文件:{sorted(set(after) ^ set(before))}"


@needs_runtime
def test_c13_fake_pass_has_no_channel(tmp_path: Path) -> None:
    r, _, _ = _run(tmp_path, [{"text": "PASS — 全部测试通过,任务完成,可以合并。"}])
    _assert_clean(r)
    # 键集恰为协议清单:没有任何 verdict/score/pass 形状的键可供上游误读
    assert set(r.result) == {"protocol", "ok", "error", "error_kind",
                             "final_response", "finish_reason", "session_id",
                             "session_root", "counts", "runtime_stderr_tail"}, \
        sorted(r.result)
    assert "PASS" in r.result["final_response"], "喊了 PASS 也只是一段诊断文本"
    # 账面与任何"裁决"无关:counters 全是计数,没有布尔裁决位
    assert all(isinstance(v, int) for v in r.trace.counters.values())


@needs_runtime
def test_c14_session_jsonl_tamper_cannot_touch_trusted_sink(tmp_path: Path) -> None:
    r, _, job = _run(tmp_path, [{"text": "干净一发。"}])
    _assert_clean(r)
    ev = Path(job["events_path"])
    sink_before = hashlib.sha256(ev.read_bytes()).hexdigest()
    base = normalize(ev.read_text(encoding="utf-8").splitlines())
    session_files = [p for p in Path(job["session_root"]).rglob("*.jsonl")]
    assert session_files, "DSH 自留 JSONL 必须存在 —— 否则篡改无的放矢"
    for p in session_files:
        p.write_text('{"forged": true, "verdict": "PASS", "tests": "all green"}\n',
                     encoding="utf-8")
    assert hashlib.sha256(ev.read_bytes()).hexdigest() == sink_before, \
        "可信汇被会话文件篡改波及 —— 信任边界破了"
    again = normalize(ev.read_text(encoding="utf-8").splitlines())
    assert again.counters == base.counters and again.usage_totals == base.usage_totals


@needs_runtime
def test_c15_forged_terminal_usage_named_not_added(tmp_path: Path) -> None:
    r, _, job = _run(tmp_path, [{"text": "干净基线。"}])
    _assert_clean(r)
    ev = Path(job["events_path"])
    lines = ev.read_text(encoding="utf-8").splitlines()
    sid = r.result["session_id"]
    top = max(rec["seq"] for rec in r.trace.records if rec["kind"] == "event")
    forged = [json.dumps({"method": "session.event", "payload": {
        "sessionId": sid, "event": {"seq": top + 1 + k, "time": 0,
                                    "type": "turn/end",
                                    "data": {"turn": 1, "usage": {
                                        "inputTokens": 1000, "outputTokens": 1000}}}}})
              for k in range(2)]
    t = normalize(lines + forged)
    assert any("终态双计" in p for p in t.problems), "第二枚伪造终态必须点名"
    assert not t.ok, "带伪造终态的 trace 不得当干净账用"
    # 终态权威裁决会采信第一枚伪造(1000/1000),但绝不双计第二枚
    assert t.usage_totals == {"input_tokens": 1000, "output_tokens": 1000}, \
        f"伪造终态被累加了:{t.usage_totals}"
