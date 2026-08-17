"""DSH 宿主侧事件适配:原始通知 → 可信 normalized trace(DSH 阶段 4)。

输入是 dsh_worker 逐条 flush 的宿主侧 events.jsonl(ADR §6:usage 与请求
计数只认这份 host-side 汇,DSH 自身的会话 JSONL 不可信)。本模块是**量具**:
不改变模型可见内容、工具行为或预算 —— 预算执法在 dsh_backend(执行语义面),
这里只负责把账算对、把破的地方点名。

**失败方向朝紧**:重复 seq、seq 空洞、乱序、多 session 混流、终态缺失,
一律进 `problems` 点名 —— PASS 相关的消费方必须要求 `ok`(problems 为空);
诊断性消费(崩溃归因)允许带着 problems 读计数。

**usage 双计守则**(H7 同型,批 13 流式双终态的病;2026-08-17 C3 实测修正):
工具环里同一 turn 有多枚 assistant/message,**每枚是独立一次 LLM 调用的
计费,逐枚累加** —— 这不是双计。双计有两种真形:同 turn 的 turn/end
第二次带 usage(终态重复,定罪);message 侧与 turn/end 都带 usage 时
只认 turn/end(终态权威,message 侧记 note 不入总账)—— 阶段 6 C15
(duplicate terminal usage)踩的就是这条。事件级重复由 (session, seq)
身份去重承担。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

# usage 键的两种拼法都认(runtime 是二进制,回包字段拼法以实测为准;
# 阶段 6 假端点会把真实形状钉死)。
_USAGE_KEYS = (
    ("input_tokens", ("inputTokens", "input_tokens", "promptTokens", "prompt_tokens")),
    ("output_tokens", ("outputTokens", "output_tokens", "completionTokens", "completion_tokens")),
    ("reasoning_tokens", ("reasoningTokens", "reasoning_tokens")),
)


@dataclass
class DshTrace:
    session_id: str | None = None
    records: list = field(default_factory=list)          # normalized,按原始行序
    counters: dict = field(default_factory=dict)
    usage_totals: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)         # 点名的破;空 = ok
    notes: list = field(default_factory=list)            # 诊断,不定罪
    raw_lines: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems


def _extract_usage(data: dict) -> dict | None:
    u = data.get("usage")
    if not isinstance(u, dict):
        return None
    out = {}
    for norm, aliases in _USAGE_KEYS:
        for a in aliases:
            if isinstance(u.get(a), (int, float)):
                out[norm] = out.get(norm, 0) + int(u[a])
                break
    return out or None


def normalize(raw_lines: list[str]) -> DshTrace:
    """原始 JSONL 行 → 可信 trace。逐行都有去处:session.event / session.status
    进 records,认不出的行进 problems(没证据不当成没问题)。"""
    t = DshTrace(raw_lines=len(raw_lines))
    seen_seq: set[int] = set()
    last_seq = -1
    current_turn = None
    # usage 按 (turn, 来源) 暂存,收尾时执行终态权威裁决
    usage_by_turn: dict[tuple, dict] = {}
    c = {"session_events": 0, "status_updates": 0, "request_headers": 0,
         "assistant_messages": 0, "turn_starts": 0, "turn_ends": 0,
         "errored_turns": 0, "retries": 0}
    last_status = None

    for i, ln in enumerate(raw_lines):
        try:
            n = json.loads(ln)
        except json.JSONDecodeError:
            t.problems.append(f"行 {i}:不是 JSON")
            continue
        method = n.get("method")
        p = n.get("payload") or {}
        sid = p.get("sessionId")
        if sid is not None:
            if t.session_id is None:
                t.session_id = sid
            elif sid != t.session_id:
                t.problems.append(f"行 {i}:混入他 session {sid}(本汇属 {t.session_id})")
                continue
        if method == "session.status":
            c["status_updates"] += 1
            last_status = p.get("status")
            t.records.append({"raw_index": i, "kind": "status", "status": last_status})
            continue
        if method != "session.event":
            t.problems.append(f"行 {i}:认不出的 method {method!r}")
            continue
        ev = p.get("event")
        if not isinstance(ev, dict) or not isinstance(ev.get("seq"), int):
            t.problems.append(f"行 {i}:session.event 缺 event/seq")
            continue
        seq, etype = ev["seq"], ev.get("type")
        if seq in seen_seq:
            t.problems.append(f"行 {i}:重复 seq {seq}(type={etype})—— 事件级双计")
            continue
        # 计数在判重之后:被点名的行进 problems 不进账,对账才平(E4)
        c["session_events"] += 1
        if seq < last_seq:
            # 不用"行 N:"前缀 —— 该前缀专指"此行未成 record"(对账约定),
            # 乱序行仍入 records
            t.problems.append(f"seq 乱序:{seq} < {last_seq}(行 {i})")
        seen_seq.add(seq)
        last_seq = max(last_seq, seq)
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}

        if etype == "turn/start":
            c["turn_starts"] += 1
            current_turn = data.get("turn", current_turn)
        elif etype == "turn/end":
            c["turn_ends"] += 1
            current_turn = data.get("turn", current_turn)
            reason = data.get("reason")
            if isinstance(reason, dict) and reason.get("kind") == "error":
                c["errored_turns"] += 1
        elif etype == "request/header":
            c["request_headers"] += 1
        elif etype == "llm/retry-started":
            c["retries"] += 1
        elif etype == "assistant/message":
            c["assistant_messages"] += 1

        rec = {"raw_index": i, "kind": "event", "seq": seq, "type": etype,
               "turn": data.get("turn", current_turn)}
        if etype == "tool/call":
            # fidelity ④ 的证据面(阶段 8):工具名落 trace。字段名 name 是
            # 2026-08-17 假端点探针实测(data_keys 含 name/callId/arguments)。
            rec["tool"] = data.get("name")
        u = _extract_usage(data)
        if u:
            src = "turn_end" if etype == "turn/end" else "message"
            key = (rec["turn"], src)
            if key not in usage_by_turn:
                usage_by_turn[key] = dict(u)
            elif src == "turn_end":
                t.problems.append(f"终态双计:turn {rec['turn']} 的 turn/end"
                                  f" 第二次带 usage(行 {i})")
            else:
                # 工具环(C3 实测):同 turn 每枚 message = 独立一次 LLM
                # 调用的计费,逐枚累加,不是双计
                for k, v in u.items():
                    usage_by_turn[key][k] = usage_by_turn[key].get(k, 0) + v
            rec["usage"] = u
        t.records.append(rec)

    # 终态权威裁决:同 turn 两侧都有 → 只认 turn/end,message 侧记 note
    totals: dict[str, int] = {}
    for (turn, src), u in usage_by_turn.items():
        if src == "message" and (turn, "turn_end") in usage_by_turn:
            t.notes.append(f"turn {turn}:message 与 turn/end 双双带 usage,"
                           "只入 turn/end(终态权威)")
            continue
        for k, v in u.items():
            totals[k] = totals.get(k, 0) + v
    t.usage_totals = totals

    # 请求计数的经验修正(2026-08-17,C3 实测):request/header **只在首次
    # 调用发射**(疑似配置回显),后续 LLM 调用不再带 —— 按它数请求会把
    # 两次调用数成一次。周期 = 一次走完的 LLM 调用:成功以 assistant/message
    # 落地,失败以 turn/end(error) 收尾;llm/retry-started 是周期内追加的
    # 物理尝试。预算轴一律吃这两个派生值,request_headers 只作信息。
    c["logical_requests"] = c["assistant_messages"] + c["errored_turns"]
    c["llm_attempts"] = c["logical_requests"] + c["retries"]

    # seq 空洞:0..last_seq 应稠密(实测 runtime 从 0 起稠密编号)
    if last_seq >= 0:
        missing = sorted(set(range(last_seq + 1)) - seen_seq)
        if missing:
            t.problems.append(f"seq 空洞:{missing[:10]}{'…' if len(missing) > 10 else ''}"
                              " —— 有事件丢失")
    # 终态存在性:有 turn 就得有对应 turn/end;收尾状态应为 idle
    if c["turn_starts"] != c["turn_ends"]:
        t.problems.append(f"turn 始末不配:starts={c['turn_starts']} ends={c['turn_ends']}"
                          " —— 终态丢失或未收敛")
    if c["session_events"] and last_status != "idle":
        t.problems.append(f"收尾 status 不是 idle(实得 {last_status!r})")
    t.counters = c
    return t


def selfcheck(trace: DshTrace) -> list[str]:
    """raw/normalized 对账:每条原始行要么成了 record,要么在 problems 里
    被点名 —— 不许有第三种去向(静默蒸发)。返回违规清单,空 = 账平。
    约定:"行 N:"前缀专指"此行未成 record";成了 record 的毛病(乱序、
    终态双计)用别的措辞,否则这里重复计入、账反而不平。"""
    out = []
    accounted = len(trace.records) + sum(
        1 for p in trace.problems if p.startswith("行 "))
    if accounted != trace.raw_lines:
        out.append(f"对账不平:raw {trace.raw_lines} 行,record {len(trace.records)}"
                   f" + 点名行 {accounted - len(trace.records)} = {accounted}")
    ev_records = sum(1 for r in trace.records if r["kind"] == "event")
    if ev_records != trace.counters.get("session_events", -1):
        out.append(f"event 计数不自洽:records {ev_records} vs "
                   f"counter {trace.counters.get('session_events')}")
    return out
