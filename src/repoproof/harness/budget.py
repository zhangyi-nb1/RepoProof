"""Run budgets: step count, wall time, per-command timeout.

Budget exhaustion is a structured stop (PARTIAL/BLOCKED/FAIL by the
gate), never an infinite continuation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from repoproof.domain.models import Budgets


class BudgetExceeded(RuntimeError):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"budget exceeded: {kind} ({detail})")
        self.kind = kind
        self.detail = detail


@dataclass
class BudgetMeter:
    budgets: Budgets
    started_monotonic: float = field(default_factory=time.monotonic)
    steps_used: int = 0

    @property
    def command_timeout_seconds(self) -> int:
        return self.budgets.max_command_minutes * 60

    def note_step(self, label: str) -> int:
        self.steps_used += 1
        if self.steps_used > self.budgets.max_agent_steps:
            raise BudgetExceeded("max_agent_steps", f"{self.steps_used} > {self.budgets.max_agent_steps} at {label}")
        self.check_wall(label)
        return self.steps_used

    def check_wall(self, label: str) -> None:
        elapsed_min = (time.monotonic() - self.started_monotonic) / 60.0
        if elapsed_min > self.budgets.max_wall_time_minutes:
            raise BudgetExceeded(
                "max_wall_time_minutes", f"{elapsed_min:.1f}m > {self.budgets.max_wall_time_minutes}m at {label}"
            )

    def snapshot(self) -> dict:
        return {
            "steps_used": self.steps_used,
            "max_agent_steps": self.budgets.max_agent_steps,
            "elapsed_seconds": round(time.monotonic() - self.started_monotonic, 1),
            "max_wall_time_minutes": self.budgets.max_wall_time_minutes,
        }
