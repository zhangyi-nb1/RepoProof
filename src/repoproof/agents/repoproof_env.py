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

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minisweagent.exceptions import Submitted

from repoproof.execution.docker_backend import DockerExecutionBackend
from repoproof.harness.policy import PolicyDecision, evaluate_agent_command
from repoproof.persistence.run_store import FileRunStore

MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


def clip_observation(output: str, cap: int | None) -> str:
    """观察限流(TESTPLAN v2 修订④,2026-08-10):单条观察超过 cap 字符
    则头尾截断并附定向读取提示。

    动机:DefaultAgent 每次调用重发全部历史,一次整文件 cat(~80k 字符)
    会在其后每次调用重复计费——读入量随调用数平方放大(deepseek 三发
    每轮 460-540k 的主因;E1 时代跨任务同画像)。全模型统一生效、预算
    不变;trace/artifact 仍存完整输出,只有给模型的观察被限流。
    首行永不截断(submit 标记检测依赖首行)。"""
    if not cap or len(output) <= cap:
        return output
    head = output[: int(cap * 0.7)]
    tail = output[-int(cap * 0.25):]
    omitted = len(output) - len(head) - len(tail)
    return (head
            + f"\n[...RepoProof obs-cap: {omitted} of {len(output)} chars omitted. "
            "Use targeted reads instead of dumping whole files: "
            "sed -n 'START,ENDp' FILE / grep -n PATTERN FILE ...]\n"
            + tail)


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
    policy_denials: list[str] = field(default_factory=list)
    """每次 deny 的原因原文(H9-b/LESSONS #41)。终局要按**原因**分类
    —— 越界访问和预算耗尽都会让 denied_count 加一,只看计数分不出来。"""
    _action_seq: int = 0
    template_vars: dict[str, Any] = field(default_factory=dict)
    # ---- Gate 4A: budget visibility (the ONE ablation variable) ----
    budget_visibility: bool = False
    """When True, every observation carries the full budget_state AND a
    short text summary the model actually sees. Counters are the
    harness's REAL counters — no extra LLM, no oracle/test knowledge."""
    model_call_limit: int = 0
    model_calls_provider: Callable[[], int] | None = None
    """Set by MiniSWEBackend to the live DefaultAgent.n_calls reader."""
    wall_limit_s: float = 0.0
    started_at: float = field(default_factory=time.monotonic)
    adaptation_dir: Path | None = None
    patch_files_limit: int = 0
    patch_lines_limit: int = 0
    # ---- Gate 4B: Public Contract Coverage Ledger (the ONE variable) ----
    ledger_enabled: bool = False
    ledger_requirements: list[dict] = field(default_factory=list)
    ledger_path: str = "/tmp/coverage_ledger.json"
    obs_char_cap: int | None = None
    """观察限流阈值(字符)。None=关闭——样例管线默认行为零改变;
    宿主级 runner 显式传入(修订④)。"""
    injected_chars: int = 0
    """Cumulative characters the harness appended to observations
    (budget + ledger lines) — the measured harness token overhead."""

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
            self.policy_denials.extend(decision.reasons)
            self.store.append_event(
                "action.denied",
                actor="harness",
                payload={"action_id": action_id, "actor_kind": "agent", "reasons": decision.reasons},
            )
            deny_state = self._budget_state()
            deny_output = "POLICY_DENIED: " + "; ".join(decision.reasons)
            if self.budget_visibility:
                deny_output += "\n\n" + self._budget_summary(deny_state)
            return {
                "output": deny_output,
                "returncode": 126,
                "exception_info": "",
                "extra": {
                    "action_id": action_id,
                    "policy_decision": "deny",
                    "typed_failure": "POLICY_DENIED",
                    "artifact_refs": [],
                    "budget_state": deny_state,
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
        output = clip_observation(output, self.obs_char_cap)
        typed_failure = None
        if res.timed_out:
            typed_failure = "COMMAND_TIMEOUT"
        state = self._budget_state()
        result = {
            "output": output,
            "returncode": res.exit_code,
            "exception_info": "",
            "extra": {
                "action_id": action_id,
                "policy_decision": "allow",
                "typed_failure": typed_failure,
                "artifact_refs": [out_ref.sha256, err_ref.sha256],
                "budget_state": state,
                "cwd": workdir,
            },
        }
        # Submit-marker check runs on the RAW output; harness lines are
        # appended afterwards so they can never mask or fake the marker.
        self._check_finished(result)
        appended = ""
        if self.budget_visibility:
            appended += "\n\n" + self._budget_summary(state)
        if self.ledger_enabled:
            appended += "\n" + self._ledger_line(state)
        if appended:
            self.injected_chars += len(appended)
            result["output"] = output + appended
        return result

    def _ledger_line(self, state: dict) -> str:
        from repoproof.harness.coverage_ledger import observation_line, summarize

        read = self.backend.exec(self.container, ["cat", self.ledger_path], timeout_s=15)
        raw = read.stdout.decode("utf-8", errors="replace") if read.exit_code == 0 else None
        summary = summarize(raw, self.ledger_requirements)
        self.last_ledger_summary = summary
        low = bool(state.get("low_budget")) if self.budget_visibility else (
            self.model_calls_provider is not None
            and self.model_call_limit - self.model_calls_provider() <= 5
        )
        return observation_line(summary, low_budget=low, requirements=self.ledger_requirements)

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
        state = {
            "commands_used": self.commands_used,
            "command_budget": self.command_budget,
            "denied": self.denied_count,
        }
        if not self.budget_visibility:
            return state
        model_used = self.model_calls_provider() if self.model_calls_provider else 0
        model_remaining = max(0, self.model_call_limit - model_used)
        files_used = lines_used = 0
        if self.adaptation_dir is not None:
            from repoproof.harness.adaptation import inventory

            inv = inventory(self.adaptation_dir)
            files_used, lines_used = inv.total_files, inv.total_lines
        wall_remaining = max(0.0, self.wall_limit_s - (time.monotonic() - self.started_at))
        state.update(
            {
                "model_calls_used": model_used,
                "model_calls_remaining": model_remaining,
                "agent_commands_used": self.commands_used,
                "agent_commands_remaining": max(0, self.command_budget - self.commands_used),
                "wall_time_remaining_seconds": int(wall_remaining),
                "patch_files_remaining": max(0, self.patch_files_limit - files_used),
                "patch_lines_remaining": max(0, self.patch_lines_limit - lines_used),
                "low_budget": model_remaining <= 5,
                "critical_budget": model_remaining <= 3,
                "final_model_call": model_remaining == 1,
            }
        )
        return state

    def _budget_summary(self, state: dict) -> str:
        """Short text the model actually sees. Built ONLY from harness
        counters — never oracle contents, hidden fixtures or test names."""
        flags = "".join(
            f" {name}=true"
            for name in ("low_budget", "critical_budget", "final_model_call")
            if state.get(name)
        )
        return (
            f"[BUDGET] model_calls {state['model_calls_used']}/"
            f"{state['model_calls_used'] + state['model_calls_remaining']} used "
            f"({state['model_calls_remaining']} remaining); "
            f"commands {state['agent_commands_used']} used "
            f"({state['agent_commands_remaining']} remaining); "
            f"wall {state['wall_time_remaining_seconds']}s remaining; "
            f"patch budget {state['patch_files_remaining']} files / "
            f"{state['patch_lines_remaining']} lines remaining.{flags}"
        )

    def workspace_dir(self) -> str:
        """The absolute directory the agent's shell actually starts in.

        ``default_cwd`` is a backend-relative sentinel ("host", "/adaptation"),
        which is useless to the agent: it cannot `cd` to it and cannot tell
        whether it is already there.  Resolving it here lets the task statement
        name the real path instead of leaving the agent to search for it — and
        searching the filesystem is precisely what the policy blocks.
        """

        session_root = getattr(self.backend, "session_root", None)
        if not callable(session_root):
            return str(self.default_cwd)
        try:
            root = Path(session_root(self.container))
        except Exception:  # noqa: BLE001 — a prompt fact must never break a run
            return str(self.default_cwd)
        relative = str(self.default_cwd).lstrip("/")
        return str((root / relative).resolve() if relative else root.resolve())

    def scratch_dir(self) -> str:
        """The sanctioned self-test output directory (see local_worktree_backend.scratch_dir)."""

        session_root = getattr(self.backend, "session_root", None)
        if not callable(session_root):
            return ""
        try:
            root = Path(session_root(self.container))
        except Exception:  # noqa: BLE001 — a prompt fact must never break a run
            return ""
        from repoproof.execution.local_worktree_backend import scratch_dir

        return str(scratch_dir(root))

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return {
            "cwd": self.default_cwd,
            "workdir_abs": self.workspace_dir(),
            "scratch_abs": self.scratch_dir(),
            **self.template_vars,
        }

    def serialize(self) -> dict:
        return {
            "env": {
                "type": "RepoProofEnvironment",
                "command_budget": self.command_budget,
                "commands_used": self.commands_used,
                "denied": self.denied_count,
            }
        }
