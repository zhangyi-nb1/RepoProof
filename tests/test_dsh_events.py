"""DSH 事件适配的钉死(DSH 阶段 4,ADR §6 可信 host-side trace)。

**冻结判据**(先写判据与反例,再写实现;措辞此后不改):

- E1 **事件级双计 fail closed**:重复 (session, seq) 必须点名且不入计数。
  反例:runtime 重发一条 request/header 被照单全收 —— 请求数翻倍,
  预算 watchdog 提前杀发,读数像"模型话多",其实是账错。
- E2 **丢失与乱序点名**:seq 空洞 = 有事件丢了;seq 倒走 = 乱序;turn
  始末不配 / 收尾不是 idle = 终态丢失。全部进 problems,不许静默容忍。
  反例:丢了 turn/end 还给出干净计数 —— "跑完了"与"被掐断"读成同一种账。
- E3 **终态权威,usage 不双计**(H7 同型,批 13 流式双终态的病):同 turn
  的 assistant/message 与 turn/end 都带 usage 时只入 turn/end;单侧带则入
  那一侧。反例:两侧都入 —— 台账 tokens 翻倍,等总额桥接批两臂直接不可比。
- E4 **对账不平即违规**:每条原始行要么成 record 要么被点名,selfcheck
  不许有第三种去向。反例:认不出的行被丢弃 —— 伪造/损坏在账面上蒸发。
- E5 **请求与尝试分开数**:request/header = 逻辑请求;llm/retry-started
  追加物理尝试。反例:混成一个数 —— 重试风暴读成"模型多轮",预算歧义。

同 dsh_worker:本层只算账,不裁决;PASS 相关消费必须要求 trace.ok。
"""

from __future__ import annotations

import json

from repoproof.agents.dsh_events import normalize, selfcheck


def _ev(seq: int, etype: str, data: dict | None = None, sid: str = "s1") -> str:
    return json.dumps({"method": "session.event", "payload": {
        "sessionId": sid,
        "event": {"seq": seq, "time": seq, "type": etype, "data": data or {}}}})


def _status(status: str, sid: str = "s1") -> str:
    return json.dumps({"method": "session.status",
                       "payload": {"sessionId": sid, "status": status}})


def _good() -> list[str]:
    return [
        _ev(0, "turn/start", {"turn": 1}),
        _ev(1, "request/header", {"header": {}}),
        _ev(2, "assistant/message", {"turn": 1}),
        _ev(3, "turn/end", {"turn": 1, "usage": {"inputTokens": 10, "outputTokens": 5}}),
        _status("idle"),
    ]


def test_good_trace_is_ok_and_counted() -> None:
    t = normalize(_good())
    assert t.ok, t.problems
    assert t.counters["logical_requests"] == 1
    assert t.counters["llm_attempts"] == 1
    assert t.usage_totals == {"input_tokens": 10, "output_tokens": 5}
    assert selfcheck(t) == []


def test_e1_duplicate_seq_fail_closed() -> None:
    lines = _good()
    lines.insert(2, _ev(1, "request/header", {"header": {}}))  # 重发同 seq
    t = normalize(lines)
    assert any("重复 seq" in p for p in t.problems)
    assert t.counters["logical_requests"] == 1, "重复事件不得入计数"
    assert selfcheck(t) == [], "被点名的行也要有去处 —— 账仍要平"


def test_e2_gap_disorder_and_lost_terminal_named() -> None:
    # 空洞:抽掉 seq 2
    t = normalize([ln for ln in _good() if '"seq": 2' not in ln])
    assert any("空洞" in p for p in t.problems)
    # 乱序:1 与 2 对调
    lines = _good()
    lines[1], lines[2] = lines[2], lines[1]
    assert any("乱序" in p for p in normalize(lines).problems)
    # 终态丢失:去掉 turn/end;收尾非 idle 也一并点名
    t3 = normalize([ln for ln in _good() if "turn/end" not in ln])
    assert any("始末不配" in p for p in t3.problems)
    t4 = normalize(_good()[:-1] + [_status("running")])
    assert any("idle" in p for p in t4.problems)


def test_e3_terminal_usage_wins_no_double_count() -> None:
    lines = [
        _ev(0, "turn/start", {"turn": 1}),
        _ev(1, "request/header", {}),
        _ev(2, "assistant/message",
            {"turn": 1, "usage": {"inputTokens": 10, "outputTokens": 5}}),
        _ev(3, "turn/end",
            {"turn": 1, "usage": {"inputTokens": 10, "outputTokens": 5}}),
        _status("idle"),
    ]
    t = normalize(lines)
    assert t.usage_totals == {"input_tokens": 10, "output_tokens": 5}, \
        "两侧都带 usage 只许入终态一侧"
    assert any("终态权威" in n for n in t.notes)
    # 单侧(仅 message)带 → 入 message 侧,不许归零
    t2 = normalize([lines[0], lines[1], lines[2], _ev(3, "turn/end", {"turn": 1}),
                    _status("idle")])
    assert t2.usage_totals == {"input_tokens": 10, "output_tokens": 5}


def test_e4_unrecognized_lines_are_named_and_books_balance() -> None:
    lines = _good() + ["这不是 JSON", json.dumps({"method": "别的", "payload": {}})]
    t = normalize(lines)
    assert any("不是 JSON" in p for p in t.problems)
    assert any("认不出的 method" in p for p in t.problems)
    assert selfcheck(t) == []
    # 白盒:悄悄抽走一条 record → 对账必须报不平
    t.records.pop()
    assert selfcheck(t), "record 蒸发必须被对账抓住"


def test_e5_requests_vs_attempts() -> None:
    lines = [
        _ev(0, "turn/start", {"turn": 1}),
        _ev(1, "request/header", {}),
        _ev(2, "llm/retry-started", {}),
        _ev(3, "llm/retry-started", {}),
        _ev(4, "request/header", {}),
        _ev(5, "turn/end", {"turn": 1}),
        _status("idle"),
    ]
    t = normalize(lines)
    assert t.counters["logical_requests"] == 2
    assert t.counters["llm_attempts"] == 4
    assert t.counters["retries"] == 2


def test_foreign_session_lines_rejected() -> None:
    t = normalize(_good() + [_ev(4, "turn/start", {"turn": 2}, sid="s2")])
    assert any("混入他 session" in p for p in t.problems)
