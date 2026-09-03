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

# The statement must describe the environment the run actually provides.  It
# used to claim a "sandboxed Linux container" and never named the working
# directory; the shell in fact starts in a session directory on the host.  A
# model that reads that literally goes looking for its own package — and the
# harness answers those sweeps with POLICY_DENIED, which its own policy calls
# "block, don't kill" precisely because agents kept hunting for things nobody
# had told them the location of.  Naming the directory removes an obstacle the
# task never meant to set; it reveals nothing about the hidden tests.
SYSTEM_TEMPLATE = """You are a careful software engineer working alone in an
offline POSIX shell session (no network access). Your shell already starts in
{{workdir_abs}} — that directory IS the tool package you must change, and it is
the only place you need. Do not search the wider filesystem for it: sweeps
outside this directory are denied by policy and waste your budget.
Self-test outputs (trial workspaces, generated files) go under
{{scratch_abs}} (also $REPOPROOF_SCRATCH_DIR) — it is discarded after the run.
Every file you leave inside the package counts toward the patch budget and is
judged as part of your change, and /tmp is off limits for outputs.
You interact ONLY by issuing bash commands; each reply must contain exactly the
command(s) to run next.
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
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    model_calls_observed: bool = True
    policy_denials: tuple[str, ...] = ()
    policy_audit_complete: bool = True


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
        # Keep the Product Codex connector independent from mini-swe's import
        # side effects (including loading its global provider .env).  The
        # compatibility backend is imported only when explicitly selected.
        from minisweagent.agents.default import DefaultAgent

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
        if hasattr(self._env, "model_calls_provider"):
            self._env.model_calls_provider = lambda: agent.n_calls
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
