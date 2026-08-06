"""RepoProofEnvironment — the mini-swe-agent Environment implementation.

The ONE autonomous loop lives in mini-swe-agent's DefaultAgent.run();
this class is the deterministic environment side: every agent action
({"command": str}) passes Policy → Budget → Docker exec → Trace, and
the observation returns to the SAME DefaultAgent loop.

Wrapper note (Gate 3B.C): the trusted harness executes the agent's
command via ``docker exec … bash -lc <command>``. That wrapper is
HARNESS-internal and is not the agent submitting ``sh -c``; the policy
denies the agent explicitly invoking nested shell launchers itself,
without claiming complete static analysis of arbitrary bash.

Completion signal (official mini-swe-agent semantics): returncode==0
and first lstripped output line == COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
→ record agent.claim_complete and raise Submitted. The claim is a stop
request only; the completion gate never consumes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minisweagent.exceptions import Submitted

from repoproof.execution.docker_backend import DockerExecutionBackend
from repoproof.harness.policy import PolicyDecision, evaluate_agent_command
from repoproof.persistence.run_store import FileRunStore

MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


@dataclass
class RepoProofEnvironment:
    backend: DockerExecutionBackend
    container: str
    store: FileRunStore
    command_timeout_s: int
    command_budget: int
    """RepoProof-side budget for EXECUTED agent commands — separate
    from the model-call step_limit, because one model reply may carry
    several actions."""
    default_cwd: str = "/adaptation"
    commands_used: int = 0
    denied_count: int = 0
    _action_seq: int = 0
    template_vars: dict[str, Any] = field(default_factory=dict)

    def _next_action_id(self) -> str:
        self._action_seq += 1
        return f"agent-a{self._action_seq:04d}"

    def execute(self, action: dict, cwd: str = "") -> dict[str, Any]:
        command = action.get("command", "")
        workdir = cwd or self.default_cwd
        action_id = self._next_action_id()

        if self.commands_used >= self.command_budget:
            decision = PolicyDecision(False, [f"command_budget_exhausted ({self.command_budget})"])
        else:
            decision = evaluate_agent_command(command)

        self.store.append_event(
            "policy.decision",
            actor="harness",
            payload={
                "action_id": action_id,
                "actor_kind": "agent",
                "command": command[:2000],
                "allowed": decision.allowed,
                "reasons": decision.reasons,
            },
        )
        if not decision.allowed:
            self.denied_count += 1
            self.store.append_event(
                "action.denied",
                actor="harness",
                payload={"action_id": action_id, "actor_kind": "agent", "reasons": decision.reasons},
            )
            return {
                "output": "POLICY_DENIED: " + "; ".join(decision.reasons),
                "returncode": 126,
                "exception_info": "",
                "extra": {
                    "action_id": action_id,
                    "policy_decision": "deny",
                    "typed_failure": "POLICY_DENIED",
                    "artifact_refs": [],
                    "budget_state": self._budget_state(),
                    "cwd": workdir,
                },
            }

        self.commands_used += 1
        self.store.append_event(
            "action.start",
            actor="agent",
            payload={"action_id": action_id, "actor_kind": "agent", "command": command[:2000], "cwd": workdir},
        )
        res = self.backend.exec(
            self.container,
            ["bash", "-lc", command],
            timeout_s=self.command_timeout_s,
            workdir=workdir,
        )
        out_ref = self.store.store_artifact(
            res.stdout, media_type="text/plain", producer=f"agent:{action_id}", name_hint="stdout"
        )
        err_ref = self.store.store_artifact(
            res.stderr, media_type="text/plain", producer=f"agent:{action_id}", name_hint="stderr"
        )
        self.store.append_event(
            "action.end",
            actor="agent",
            payload={
                "action_id": action_id,
                "actor_kind": "agent",
                "exit_code": res.exit_code,
                "timed_out": res.timed_out,
                "duration_ms": res.duration_ms,
                "budget": self._budget_state(),
            },
            artifact_refs=[out_ref.sha256, err_ref.sha256],
        )

        stdout = res.stdout.decode("utf-8", errors="replace")
        stderr = res.stderr.decode("utf-8", errors="replace")
        output = stdout if not stderr else f"{stdout}\n[stderr]\n{stderr}"
        typed_failure = None
        if res.timed_out:
            typed_failure = "COMMAND_TIMEOUT"
        result = {
            "output": output,
            "returncode": res.exit_code,
            "exception_info": "",
            "extra": {
                "action_id": action_id,
                "policy_decision": "allow",
                "typed_failure": typed_failure,
                "artifact_refs": [out_ref.sha256, err_ref.sha256],
                "budget_state": self._budget_state(),
                "cwd": workdir,
            },
        }
        self._check_finished(result)
        return result

    def _check_finished(self, output: dict) -> None:
        lines = output["output"].lstrip().splitlines()
        if lines and lines[0].strip() == MARKER and output["returncode"] == 0:
            submission = "\n".join(output["output"].lstrip().splitlines()[1:])
            self.store.append_event(
                "agent.claim_complete",
                actor="agent",
                payload={
                    "note": "official mini-swe-agent submit marker; stop request only — "
                    "never a completion-gate input",
                    "submission_chars": len(submission),
                },
            )
            raise Submitted(
                {
                    "role": "exit",
                    "content": submission,
                    "extra": {"exit_status": "Submitted", "submission": submission},
                }
            )

    def _budget_state(self) -> dict:
        return {
            "commands_used": self.commands_used,
            "command_budget": self.command_budget,
            "denied": self.denied_count,
        }

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return {"cwd": self.default_cwd, **self.template_vars}

    def serialize(self) -> dict:
        return {
            "env": {
                "type": "RepoProofEnvironment",
                "command_budget": self.command_budget,
                "commands_used": self.commands_used,
                "denied": self.denied_count,
            }
        }
