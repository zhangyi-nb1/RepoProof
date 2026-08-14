"""Token budget enforcement (Gate 5.1).

Found by running: contract max_input_tokens_total=250000 was a paper
number — real runs used 290k+ while Policy reported PASS. This wrapper
makes the budget REAL, with honestly-labeled enforcement types:

  input  : a call is issued ONLY if ``used + projected_cost_of_this_call
           <= cap``. ``used`` is accounted **synchronously** from the
           response the wrapper just received; ``projected`` is a local
           estimate of the exact messages being sent, scaled by a ratio
           calibrated against provider-reported truth and floored by the
           largest single call observed so far.
  output : remaining allowance is passed as ``max_tokens`` on every
           request (request-level cap) plus the same post-call check.

LESSONS #39 (order-63) rewrote the input side. The old shape was
"provider-reported totals, checked before the next call, with the
enforcement line inset by a flat 50k". It leaked twice over:

  * the totals came from ``litellm.success_callback``, which litellm
    dispatches through a thread pool (``executor.submit`` in
    ``litellm/utils.py``) — so the pre-call check read a total that
    lagged one call behind. Round 1 of order-63 stood at 752,243 (past
    the 750,000 line) and the check still saw 703,172, let the call
    through, and landed on 803,310 > the 800,000 policy line;
  * the flat inset was a guess. That round's largest single call was
    51,067 tokens — the guess missed by 1,067.

The pre-call projection makes crossing impossible as long as a call's
true cost stays under its projection, and it costs no flat tax: the
agent gets exactly the contract allowance, no more, no less.

Providers that report no usage anywhere (neither in the response nor via
the hook) leave totals UNKNOWN — never fabricated zeros — and only
request-level output capping applies; the final policy gate likewise
does not judge UNKNOWN, so nothing is killed for a number nobody has.

On exhaustion: the next model call NEVER happens; a ``budget.exhausted``
event is recorded; DefaultAgent terminates via the official
InterruptAgentFlow path with exit_status=TokenBudgetExhausted; the
runner maps that to FAIL/BUDGET_EXHAUSTED when hard goals are unmet
(never BLOCKED).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from minisweagent.exceptions import LimitsExceeded

ENFORCEMENT = {
    "input": ("pre_call_projection (local estimate × calibrated ratio, floored by "
              "observed max call) + provider_reported_post_call (accounted "
              "synchronously from the response, hook used only as a lower bound)"),
    "output": "max_tokens_request_cap + provider_reported_post_call",
}

# CJK 一字约一 token;拉丁/代码约 3.6 字符一 token。实测 order-63 轮 1:
# 照搬 chars/4 估成 604,905(真实 803,310,比值 1.33),按此式估 754,295
# (比值 1.07)。估得越准,投影的浪费越小。
_CJK = re.compile(r"[⺀-鿿豈-﫿　-〿＀-￯]")
CHARS_PER_TOKEN = 3.6
PER_MESSAGE_OVERHEAD = 8
# 工具 schema 等**不在消息里**的固定开销,估算时补上。
TOOL_OVERHEAD_TOKENS = 400
# 冷启动比值:还没有任何真值可校准时用。
COLD_RATIO = 1.6
# 校准只采信"提示已经够大"的样本 —— 小提示上的比值被固定开销污染,
# 采信它会让后续投影长期虚高、把额度白白吃掉。
RATIO_MIN_ESTIMATE = 2_000
# 在已观测最差比值之上再留的余量。
SAFETY_FACTOR = 1.25


def _estimate_text(text: str) -> int:
    cjk = len(_CJK.findall(text))
    return cjk + math.ceil(max(0, len(text) - cjk) / CHARS_PER_TOKEN)


def estimate_prompt_tokens(messages: list[dict] | None) -> int:
    """本地估算一次请求的输入 token。宁可高估,不可低估。

    ``extra`` 不计:mini-swe-agent 在发出前会把它剥掉(``_prepare_
    messages_for_api``),而它装着上一次响应的完整 dump——算进去会把
    估算抬高一个量级。"""
    total = 0
    for msg in messages or []:
        if not isinstance(msg, dict):
            total += PER_MESSAGE_OVERHEAD + _estimate_text(str(msg))
            continue
        total += PER_MESSAGE_OVERHEAD
        for key, value in msg.items():
            if key == "extra" or value is None:
                continue
            total += _estimate_text(
                value if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, default=str))
    return total


def _response_usage(response: Any) -> tuple[int, int] | None:
    """从**返回体**里同步取 usage(不等异步钩子)。取不到就 None。"""
    extra = response.get("extra") if isinstance(response, dict) else None
    if not isinstance(extra, dict):
        return None
    raw = extra.get("response")
    usage = raw.get("usage") if isinstance(raw, dict) else getattr(raw, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        pin, pout = usage.get("prompt_tokens"), usage.get("completion_tokens")
    else:
        pin = getattr(usage, "prompt_tokens", None)
        pout = getattr(usage, "completion_tokens", None)
    if pin is None and pout is None:
        return None
    return int(pin or 0), int(pout or 0)


@dataclass
class TokenBudgetedModel:
    """Model proxy: accounting + pre-call gate. The ONE loop stays in
    DefaultAgent; this never plans, never calls a second LLM."""

    inner: Any
    totals: dict
    """Shared accumulator {"in": int, "out": int, "seen": bool} fed by
    the litellm success hook (or by the inner fake in tests). Read as a
    LOWER BOUND only — the hook is asynchronous, so it may lag."""
    max_input_tokens: int
    max_output_tokens: int
    on_exhausted: Callable[[dict], None] | None = None
    # E1-S2 上下文投影。None = E0(全历史重发,一字不动)。
    projector: Callable[[list[dict]], tuple[list[dict], dict]] | None = None
    on_projection: Callable[[dict], None] | None = None
    exhausted: dict | None = field(default=None)

    # --- 同步记账:执法的权威来源,不依赖异步钩子(LESSONS #39 H7-a)
    sync_in: int = 0
    sync_out: int = 0
    sync_seen: bool = False
    max_call_in: int = 0
    observed_ratio: float = 0.0
    last_used_in: int = 0

    @property
    def used_in(self) -> int:
        """已用输入 = max(同步记账, 钩子读数) —— 两边都不许被低估。"""
        return max(self.sync_in, int(self.totals.get("in", 0) or 0))

    @property
    def used_out(self) -> int:
        return max(self.sync_out, int(self.totals.get("out", 0) or 0))

    @property
    def seen(self) -> bool:
        return bool(self.sync_seen or self.totals.get("seen"))

    @property
    def ratio(self) -> float:
        return max(self.observed_ratio, 1.0) if self.observed_ratio > 0 else COLD_RATIO

    def project_input(self, messages: list[dict] | None) -> int:
        """本次调用的输入投影。两条支撑,取大者:

        估算支——覆盖"提示突然变大"(已观测最大救不了);
        下限支——覆盖"估算失准"(工具 schema、provider 侧改写不在消息里)。
        """
        est = estimate_prompt_tokens(messages) + TOOL_OVERHEAD_TOKENS
        return max(math.ceil(est * self.ratio * SAFETY_FACTOR), self.max_call_in)

    def _raise_exhausted(self, kind: str, used: int, limit: int, *,
                         reason: str, projected: int | None = None) -> None:
        payload = {
            "kind": kind,
            "used": used,
            "limit": limit,
            "reason": reason,
            "enforcement": ENFORCEMENT,
        }
        if projected is not None:
            payload["projected"] = projected
        self.exhausted = payload
        if self.on_exhausted:
            self.on_exhausted(payload)
        raise LimitsExceeded(
            {
                "role": "exit",
                "content": "TokenBudgetExhausted",
                "extra": {
                    "exit_status": "TokenBudgetExhausted",
                    "submission": "",
                    "budget": payload,
                },
            }
        )

    def _account(self, response: Any, est: int) -> None:
        usage = _response_usage(response)
        if usage is None:
            return
        pin, pout = usage
        self.sync_seen = True
        self.sync_in += pin
        self.sync_out += pout
        self.max_call_in = max(self.max_call_in, pin)
        if pin > 0 and est >= RATIO_MIN_ESTIMATE:
            self.observed_ratio = max(self.observed_ratio, pin / est)

    def query(self, messages: list[dict], **kwargs) -> dict:
        # E1-S2:先投影,再记账。顺序不可颠倒 —— 预算必须按**真正发出去的**
        # 那份算,否则折叠省下的额度会被"按未投影历史投影"的预算白白吃掉,
        # 收益归零。完整历史仍留在 agent 与轨迹里(证据不减,C4)。
        if self.projector is not None:
            messages, manifest = self.projector(messages)
            if manifest.get("folded_messages") and self.on_projection is not None:
                self.on_projection(manifest)
        used_in, used_out = self.used_in, self.used_out
        # provider 只在钩子里给 usage 时(返回体不带),同步记账看不到任何
        # 一次调用的大小,下限支会永远是 0 —— 不可越线的保证就只剩估算一条
        # 腿。用两次调用之间的增量补出"单次最大";钩子滞后时增量会跨越多次
        # 调用,只会偏保守,不会偏松。
        if used_in > self.last_used_in:
            self.max_call_in = max(self.max_call_in, used_in - self.last_used_in)
        self.last_used_in = used_in
        if self.seen:
            if used_in >= self.max_input_tokens:
                self._raise_exhausted("max_input_tokens_total", used_in,
                                      self.max_input_tokens, reason="used")
            if used_out >= self.max_output_tokens:
                self._raise_exhausted("max_output_tokens_total", used_out,
                                      self.max_output_tokens, reason="used")
            projected = self.project_input(messages)
            if used_in + projected > self.max_input_tokens:
                self._raise_exhausted("max_input_tokens_total", used_in,
                                      self.max_input_tokens, reason="projected",
                                      projected=projected)
            remaining_out = self.max_output_tokens - used_out
        else:
            remaining_out = self.max_output_tokens
        kwargs.setdefault("max_tokens", max(1, remaining_out))
        est = estimate_prompt_tokens(messages) + TOOL_OVERHEAD_TOKENS
        response = self.inner.query(messages, **kwargs)
        self._account(response, est)
        return response

    # -------- pure delegation (protocol surface) --------
    def format_message(self, **kwargs) -> dict:
        return self.inner.format_message(**kwargs)

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars: dict) -> list[dict]:
        return self.inner.format_observation_messages(message, outputs, template_vars)

    def get_template_vars(self, **kwargs) -> dict:
        return self.inner.get_template_vars(**kwargs)

    def serialize(self) -> dict:
        data = self.inner.serialize() if hasattr(self.inner, "serialize") else {}
        return {**data, "token_budget": {"enforcement": ENFORCEMENT}}
