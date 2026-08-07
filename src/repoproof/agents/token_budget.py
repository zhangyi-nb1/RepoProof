"""Token budget enforcement (Gate 5.1).

Found by running: contract max_input_tokens_total=250000 was a paper
number — real runs used 290k+ while Policy reported PASS. This wrapper
makes the budget REAL, with honestly-labeled enforcement types:

  input  : ``provider_reported_post_call`` totals, checked BEFORE the
           next model call (pre-call check of post-call accounting).
           Without a reliable local tokenizer we do NOT claim a strict
           pre-call hard cap on the very call that crosses the line.
  output : remaining allowance is passed as ``max_tokens`` on every
           request (request-level cap) plus the same post-call check.

On exhaustion: the next model call NEVER happens; a ``budget.exhausted``
event is recorded; DefaultAgent terminates via the official
InterruptAgentFlow path with exit_status=TokenBudgetExhausted; the
runner maps that to FAIL/BUDGET_EXHAUSTED when hard goals are unmet
(never BLOCKED). Providers that report no usage leave totals UNKNOWN —
never fabricated zeros — and only request-level output capping applies.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from minisweagent.exceptions import LimitsExceeded

ENFORCEMENT = {
    "input": "provider_reported_post_call (checked pre-next-call)",
    "output": "max_tokens_request_cap + provider_reported_post_call",
}


@dataclass
class TokenBudgetedModel:
    """Model proxy: accounting + pre-call gate. The ONE loop stays in
    DefaultAgent; this never plans, never calls a second LLM."""

    inner: Any
    totals: dict
    """Shared accumulator {"in": int, "out": int, "seen": bool} fed by
    the litellm success hook (or by the inner fake in tests)."""
    max_input_tokens: int
    max_output_tokens: int
    on_exhausted: Callable[[dict], None] | None = None
    exhausted: dict | None = field(default=None)

    def _raise_exhausted(self, kind: str, used: int, limit: int) -> None:
        payload = {
            "kind": kind,
            "used": used,
            "limit": limit,
            "enforcement": ENFORCEMENT,
        }
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

    def query(self, messages: list[dict], **kwargs) -> dict:
        if self.totals.get("seen"):
            used_in = int(self.totals.get("in", 0))
            used_out = int(self.totals.get("out", 0))
            if used_in >= self.max_input_tokens:
                self._raise_exhausted("max_input_tokens_total", used_in, self.max_input_tokens)
            if used_out >= self.max_output_tokens:
                self._raise_exhausted("max_output_tokens_total", used_out, self.max_output_tokens)
            remaining_out = self.max_output_tokens - used_out
        else:
            remaining_out = self.max_output_tokens
        kwargs.setdefault("max_tokens", max(1, remaining_out))
        return self.inner.query(messages, **kwargs)

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
