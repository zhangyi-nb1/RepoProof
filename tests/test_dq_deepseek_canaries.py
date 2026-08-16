"""DQ canary 脚本钉(离线)。

三条 canary 的编排逻辑用 FakeModel 全离线走通(PASS 形状与 FAIL 路径
都要红绿分明);纯函数(观察模拟 / 长观察构造 / §11.5 判决)逐条钉;
零执行面用 AST 钉死 —— canary 绝不执行模型给的命令。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from dq_deepseek_canaries import (  # noqa: E402
    NEEDLE_PREFIX,
    OBS_CAP_CHARS,
    build_long_observation,
    canary1_single_tool,
    canary2_multiturn_passback,
    canary3_long_observation,
    dq_verdict,
    simulate_echo_output,
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dq_deepseek_canaries.py"


# ---------------------------------------------------------------- FakeModel


def _mk(content=None, commands=(), reasoning=None, tin=100, tout=20):
    return {
        "role": "assistant",
        "content": content,
        "reasoning_content": reasoning,
        "tool_calls": [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": "bash", "arguments": "{}"}}
            for i, _ in enumerate(commands)
        ] or None,
        "extra": {
            "actions": [{"command": c, "tool_call_id": f"call_{i}"}
                        for i, c in enumerate(commands)],
            "response": {"usage": {"prompt_tokens": tin, "completion_tokens": tout}},
            "cost": 0.0,
        },
    }


class FakeModel:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.seen: list[list[dict]] = []

    def query(self, messages, **kw):
        self.seen.append([dict(m) for m in messages])
        nxt = self.scripted.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def format_observation_messages(self, message, outputs, tvars):
        acts = message["extra"]["actions"]
        return [{"role": "tool", "content": o["output"], "tool_call_id": a["tool_call_id"]}
                for a, o in zip(acts, outputs)]


# ---------------------------------------------------------------- 纯函数


def test_simulate_echo_takes_literal_and_strips_quotes():
    assert simulate_echo_output("echo DQ_C1_OK")["output"] == "DQ_C1_OK\n"
    assert simulate_echo_output("echo 'hi there'")["output"] == "hi there\n"
    out = simulate_echo_output("cat /etc/passwd")
    assert out["output"].startswith("[simulated observation for:")


def test_long_observation_exact_cap_with_needle_at_tail():
    blob = build_long_observation("abc123def456")
    assert len(blob) == OBS_CAP_CHARS
    assert blob.endswith(f"{NEEDLE_PREFIX}abc123def456\n")
    assert blob.count(NEEDLE_PREFIX) == 1


def test_dq_verdict_requires_every_cell_green_and_complete():
    ok = [{"profile": "P", "canary": f"C{i}", "status": "PASS"} for i in (1, 2, 3)]
    assert dq_verdict(ok, 3)["dq_status"] == "PASS"
    one_red = ok[:2] + [{"profile": "P", "canary": "C3", "status": "FAIL", "reason": "x"}]
    v = dq_verdict(one_red, 3)
    assert v["dq_status"] == "PROVIDER_PROTOCOL_FAILURE"
    assert v["failed_cells"] == [{"profile": "P", "canary": "C3", "reason": "x"}]
    # 缺格 = 没考完,同样不算过(§11.5 的 100% 是对全矩阵说的)
    assert dq_verdict(ok, 6)["dq_status"] == "PROVIDER_PROTOCOL_FAILURE"


# ---------------------------------------------------------------- C1


def test_c1_pass_shape():
    m = FakeModel([_mk(commands=["echo DQ_C1_OK"])])
    cell = canary1_single_tool(m, max_tokens=100)
    assert cell["status"] == "PASS"
    assert cell["usage"] == {"in": 100, "out": 20}
    assert cell["checks"]["command_echoes_token"]


def test_c1_fails_without_usage():
    m = FakeModel([_mk(commands=["echo DQ_C1_OK"], tin=0, tout=0)])
    cell = canary1_single_tool(m, max_tokens=100)
    assert cell["status"] == "FAIL"
    assert not cell["checks"]["usage_prompt_positive"]


# ---------------------------------------------------------------- C2


def test_c2_full_tool_loop_pass_and_reasoning_recorded_not_gated():
    """全工具轮设计(冒烟教训:mini 协议里无 tool_call 轮 = FormatError,
    收尾必须也是工具调用)。"""
    m = FakeModel([
        _mk(commands=["echo DQ_C2_STEP1"], reasoning="thinking..."),
        _mk(commands=["echo DQ_C2_STEP2"]),
        _mk(commands=["echo DQ_C2_DONE"]),
    ])
    cell = canary2_multiturn_passback(m, max_tokens=100, max_rounds=4)
    assert cell["status"] == "PASS"
    assert cell["tool_rounds"] == 3 and cell["rounds"] == 3
    assert cell["reasoning_rounds_observed"] == 1
    assert cell["checks"]["done_step_reached"]
    # 第二轮请求里必须带上第一轮的观察(tool 消息进了历史)
    round2 = m.seen[1]
    assert any(x.get("role") == "tool" and "DQ_C2_STEP1" in x.get("content", "")
               for x in round2)


def test_c2_protocol_rejection_is_fail_with_typed_reason():
    m = FakeModel([
        _mk(commands=["echo DQ_C2_STEP1"]),
        RuntimeError("simulated 400: reasoning_content rejected"),
    ])
    cell = canary2_multiturn_passback(m, max_tokens=100, max_rounds=4)
    assert cell["status"] == "FAIL"
    assert "RuntimeError" in cell["reason"]
    assert not cell["checks"]["no_protocol_error"]


def test_c2_format_error_reason_carries_the_message_content():
    """FormatError 的 str() 为空 —— 病名必须从其消息 dict 里掏出来。"""
    from minisweagent.exceptions import FormatError

    m = FakeModel([FormatError({"role": "user", "content": "No tool calls found in x"})])
    cell = canary2_multiturn_passback(m, max_tokens=100, max_rounds=4)
    assert cell["status"] == "FAIL"
    assert "FormatError: No tool calls found" in cell["reason"]


def test_c2_endless_tool_loop_fails_on_round_budget():
    m = FakeModel([_mk(commands=["echo x"]) for _ in range(4)])
    cell = canary2_multiturn_passback(m, max_tokens=100, max_rounds=4)
    assert cell["status"] == "FAIL"
    assert "DONE step not reached" in cell["reason"]


# ---------------------------------------------------------------- C3


def test_c3_pass_requires_verbatim_needle_in_report_action():
    token = "feedbeef0123"
    m = FakeModel([
        _mk(commands=["cat service.log"]),
        _mk(commands=[f"echo REPORT:{token}"]),
    ])
    cell = canary3_long_observation(m, max_tokens=100, needle_token=token)
    assert cell["status"] == "PASS"
    assert cell["observation"]["chars"] == OBS_CAP_CHARS
    assert cell["observation"]["simulated"] is True
    round2 = m.seen[1]
    tool_msgs = [x for x in round2 if x.get("role") == "tool"]
    assert tool_msgs and len(tool_msgs[0]["content"]) == OBS_CAP_CHARS
    assert tool_msgs[0]["content"].rstrip().endswith(token)


def test_c3_fails_when_needle_not_echoed():
    m = FakeModel([
        _mk(commands=["cat service.log"]),
        _mk(commands=["echo REPORT:i-lost-it"]),
    ])
    cell = canary3_long_observation(m, max_tokens=100, needle_token="feedbeef0123")
    assert cell["status"] == "FAIL"
    assert not cell["checks"]["needle_echoed_verbatim"]


def test_c3_fails_without_round1_tool_call():
    m = FakeModel([_mk(content="no tools used")])
    cell = canary3_long_observation(m, max_tokens=100, needle_token="feedbeef0123")
    assert cell["status"] == "FAIL"
    assert cell["reason"] == "no tool call in round 1"


# ---------------------------------------------------------------- 零执行面(AST)


def test_canary_script_has_zero_execution_surface():
    """模型给的命令绝不执行:整个脚本里 subprocess 只许出现一次,且第一个
    参数是 git;不许出现 os.system / os.popen / eval / exec 调用。"""
    tree = ast.parse(SCRIPT.read_text())
    sub_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        owner = getattr(f.value, "id", "") if isinstance(f, ast.Attribute) else ""
        if owner == "subprocess":
            sub_calls.append(node)
        assert not (owner == "os" and name in ("system", "popen")), "os.system/popen 禁用"
        assert name not in ("eval", "exec"), "eval/exec 禁用"
    assert len(sub_calls) == 1, "subprocess 只许 git rev-parse 一处"
    first_arg = sub_calls[0].args[0]
    assert isinstance(first_arg, ast.List) and first_arg.elts[0].value == "git"
