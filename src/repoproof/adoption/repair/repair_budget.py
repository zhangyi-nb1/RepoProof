"""Repair Budget(RFC-006)— 有界修复的硬预算。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RepairBudget(BaseModel):
    max_rounds: int = Field(default=3, ge=1)
    max_tokens: int = 400_000
    max_commands: int = 120
    max_diff_lines: int = 400

    def exceeded(self, *, rounds: int, tokens: int, commands: int, diff_lines: int) -> str | None:
        """返回耗尽原因(None=仍在预算内)。"""
        if rounds >= self.max_rounds:
            return f"max_rounds({self.max_rounds})"
        # 语义统一(F10):达到额度即耗尽(>=);diff 同样以超出上限为耗尽
        if tokens >= self.max_tokens:
            return f"max_tokens({self.max_tokens})"
        if commands >= self.max_commands:
            return f"max_commands({self.max_commands})"
        if diff_lines > self.max_diff_lines:  # 上限值本身允许,超过即耗尽
            return f"max_diff_lines({self.max_diff_lines})"
        return None
