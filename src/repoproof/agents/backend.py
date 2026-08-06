"""MiniSWEBackend — the one-shot AgentBackend.

Call chain (the ONLY autonomous loop in the whole system):

    RepoProofRunner.run_once
      → MiniSWEBackend.run_task(spec)          (calls DefaultAgent.run ONCE)
        → minisweagent DefaultAgent.run(task)  (the single while/step loop)
          → RepoProofEnvironment.execute(action)
            → Policy / Budget / Docker / Trace
          → observation back into the SAME DefaultAgent loop

RepoProof never writes next_action, never runs its own agent while
loop, and never calls a second LLM on rejection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minisweagent.agents.default import DefaultAgent

SYSTEM_TEMPLATE = """You are a careful software engineer working alone in a
sandboxed Linux container (no network). You interact ONLY by issuing bash
commands; each reply must contain exactly the command(s) to run next.
When you are completely done, run a command whose first output line is
COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
(e.g. `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`)."""

INSTANCE_TEMPLATE = "{{task}}"


@dataclass
class AgentRunResult:
    exit_status: str
    submission: str
    n_model_calls: int
    cost: float | str
    trajectory_path: Path | None
    commands_used: int
    denied_count: int


class MiniSWEBackend:
    """One-shot backend: constructs DefaultAgent once, runs it once."""

    def __init__(self, *, model: Any, env: Any, step_limit: int, cost_limit: float, output_path: Path) -> None:
        self._model = model
        self._env = env
        self._step_limit = step_limit
        self._cost_limit = cost_limit
        self._output_path = output_path
        self.run_count = 0

    def run_task(self, task: str) -> AgentRunResult:
        assert self.run_count == 0, "MiniSWEBackend.run_task may be called exactly once"
        self.run_count += 1
        agent = DefaultAgent(
            self._model,
            self._env,
            system_template=SYSTEM_TEMPLATE,
            instance_template=INSTANCE_TEMPLATE,
            step_limit=self._step_limit,
            cost_limit=self._cost_limit,
            output_path=self._output_path,
        )
        try:
            extra = agent.run(task)
        except Exception as exc:  # noqa: BLE001 — uncaught agent errors become a typed exit
            extra = {"exit_status": f"Uncaught:{type(exc).__name__}", "submission": ""}
        cost: float | str = agent.cost
        if not cost:
            # A proxy provider that reports no usage-based dollar figure
            # yields UNKNOWN — never a fabricated 0 for a real model.
            cost = 0.0 if getattr(self._model, "is_free_fake", False) else "UNKNOWN"
        return AgentRunResult(
            exit_status=str(extra.get("exit_status", "")),
            submission=str(extra.get("submission", "")),
            n_model_calls=agent.n_calls,
            cost=cost,
            trajectory_path=self._output_path,
            commands_used=getattr(self._env, "commands_used", 0),
            denied_count=getattr(self._env, "denied_count", 0),
        )
