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

**协议事实**(2026-08-17 实测):`POST {base}/chat/completions`(无 /v1),
强制 SSE;工具回传 {"role":"tool","tool_call_id","content"};usage 在
assistant/message(camelCase);request/header 仅首次调用发射。
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from repoproof.agents.dsh_backend import DshBudget, run_dsh_worker

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
    不出网)。script:{"text": 终答} 或 {"tool": 工具名, "args": 参数}。
    脚本用尽后兜底回终答 —— 宁可让断言红,不让 runtime 空转。"""

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
                if "tool" in s:
                    first = _chunk({"role": "assistant", "tool_calls": [
                        {"index": 0, "id": f"call_fake_{i}", "type": "function",
                         "function": {"name": s["tool"],
                                      "arguments": json.dumps(s["args"],
                                                              ensure_ascii=False)}}]})
                    last = _chunk({}, finish="tool_calls", usage=_USAGE)
                else:
                    first = _chunk({"role": "assistant", "content": s["text"]})
                    last = _chunk({}, finish="stop", usage=_USAGE)
                payload = (first + last + "data: [DONE]\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.base_url = f"http://127.0.0.1:{self.srv.server_port}"

    def __enter__(self) -> "_FakeDeepSeek":
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a) -> None:
        self.srv.shutdown()
        self.srv.server_close()


def _run(tmp: Path, scripts: list[dict], prompt: str = "做点事。"):
    """一发 = 新 workspace + 新 fake + 新 worker。返回 (report, fake, job)。"""
    ws = tmp / "ws"
    ws.mkdir(exist_ok=True)
    job = {"prompt": prompt, "workspace": str(ws),
           "events_path": str(tmp / "ev" / "events.jsonl"),
           "session_root": str(tmp / "sess"),
           "cordis": str(RT_ROOT / "config" / "minimal.upstream.0.1.0rc6.cordis.yml"),
           "request_timeout_seconds": 60.0}
    with _FakeDeepSeek(scripts) as fake:
        job["env"] = {"DEEPSEEK_BASE_URL": fake.base_url}
        r = run_dsh_worker(job, worker_python=SEALED_PY,
                           budget=DshBudget(max_wall_seconds=180,
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
