"""Gate 3B — mini-swe-agent protocol integration with a FREE fake model.

Proves, without any LLM call:
  1. an allowed command executes and its Observation reaches the loop;
  2. a Policy DENY returns a structured Observation and the SAME
     DefaultAgent loop keeps going;
  3. one model reply with multiple actions → one action_id + budget
     tick per action;
  4. the official completion marker is recognized (Submitted);
  5. MiniSWEBackend calls DefaultAgent.run exactly once;
  6. RepoProof contains no second autonomous loop.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from repoproof.agents.backend import MiniSWEBackend
from repoproof.agents.fake_model import FakeModel
from repoproof.agents.repoproof_env import RepoProofEnvironment
from repoproof.execution.docker_backend import DockerExecutionBackend
from repoproof.execution.profiles import agent_profile
from repoproof.harness.trace import scan_events
from repoproof.persistence.run_store import FileRunStore

REPO = Path(__file__).resolve().parent.parent
IMAGE = "python:3.12-slim-bookworm"
docker_ok, _ = DockerExecutionBackend.available()
needs_docker = pytest.mark.skipif(not docker_ok, reason="docker daemon not reachable")

SUBMIT = {"content": "done", "actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]}


@pytest.fixture()
def agent_rig():
    import shutil

    tmp = REPO / "runs" / f"_agent_rig-{uuid.uuid4().hex[:8]}"
    for name in ("upstream", "workspace", "adaptation", "venv"):
        (tmp / name).mkdir(parents=True)
    (tmp / "upstream" / "README.md").write_text("pinned\n")
    backend = DockerExecutionBackend(image=IMAGE)
    profile = agent_profile(
        upstream=tmp / "upstream",
        agent_workspace=tmp / "workspace",
        adaptation=tmp / "adaptation",
        venv=tmp / "venv",
    )
    kwargs = profile.start_kwargs()
    kwargs["user"] = f"{os.getuid()}:{os.getgid()}"
    cid = backend.start(name_prefix="rp-3b", **kwargs)
    store = FileRunStore(tmp / "run")
    env = RepoProofEnvironment(
        backend=backend, container=cid, store=store, command_timeout_s=60, command_budget=10
    )
    yield backend, cid, store, env, tmp
    backend.destroy(cid)
    import subprocess

    subprocess.run(["chmod", "-R", "u+w", str(tmp)], capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)


def _run(env, store, script, tmp) -> tuple:
    model = FakeModel(script=list(script))
    backend = MiniSWEBackend(
        model=model, env=env, step_limit=10, cost_limit=1.0, output_path=tmp / "trajectory.json"
    )
    result = backend.run_task("test task")
    return model, backend, result


@needs_docker
def test_allowed_command_executes_and_observation_returns(agent_rig) -> None:
    _b, _c, store, env, tmp = agent_rig
    model, _backend, result = _run(env, store, [
        {"content": "look", "actions": [{"command": "echo hello-from-container"}]},
        SUBMIT,
    ], tmp)
    assert result.exit_status == "Submitted"
    first_obs = model.observed[0][0]
    assert first_obs["returncode"] == 0
    assert "hello-from-container" in first_obs["output"]
    assert first_obs["extra"]["action_id"].startswith("agent-a")


@needs_docker
def test_policy_deny_observation_same_loop_recovers(agent_rig) -> None:
    _b, _c, store, env, tmp = agent_rig
    model, _backend, result = _run(env, store, [
        {"content": "bad", "actions": [{"command": "sudo rm -rf /"}]},
        {"content": "ok then", "actions": [{"command": "echo recovered"}]},
        SUBMIT,
    ], tmp)
    assert result.exit_status == "Submitted"
    deny_obs = model.observed[0][0]
    assert deny_obs["returncode"] == 126
    assert "POLICY_DENIED" in deny_obs["output"]
    assert deny_obs["extra"]["typed_failure"] == "POLICY_DENIED"
    # The SAME loop consumed the denial and issued the next action:
    assert model.calls == 3
    assert "recovered" in model.observed[1][0]["output"]
    denied_events = scan_events(store.trace_path, "action.denied")
    assert len(denied_events) == 1
    # denied action ids never get start/end events
    denied_id = denied_events[0]["payload"]["action_id"]
    started = {e["payload"]["action_id"] for e in scan_events(store.trace_path, "action.start")}
    assert denied_id not in started


@needs_docker
def test_multiple_actions_in_one_reply_get_own_ids_and_budget(agent_rig) -> None:
    _b, _c, store, env, tmp = agent_rig
    model, _backend, result = _run(env, store, [
        {"content": "two", "actions": [{"command": "echo A"}, {"command": "echo B"}]},
        SUBMIT,
    ], tmp)
    assert result.exit_status == "Submitted"
    outs = model.observed[0]
    assert len(outs) == 2
    ids = [o["extra"]["action_id"] for o in outs]
    assert len(set(ids)) == 2
    assert outs[0]["extra"]["budget_state"]["commands_used"] == 1
    assert outs[1]["extra"]["budget_state"]["commands_used"] == 2
    assert result.commands_used == 3  # A, B, submit


@needs_docker
def test_completion_marker_recognized_and_claim_traced(agent_rig) -> None:
    _b, _c, store, env, tmp = agent_rig
    _model, _backend, result = _run(env, store, [SUBMIT], tmp)
    assert result.exit_status == "Submitted"
    claims = scan_events(store.trace_path, "agent.claim_complete")
    assert len(claims) == 1
    traj = json.loads((tmp / "trajectory.json").read_text())
    assert traj["info"]["exit_status"] == "Submitted"
    assert traj["trajectory_format"].startswith("mini-swe-agent")


@needs_docker
def test_backend_runs_default_agent_exactly_once(agent_rig, monkeypatch) -> None:
    _b, _c, store, env, tmp = agent_rig
    from minisweagent.agents import default as d

    calls = {"n": 0}
    orig = d.DefaultAgent.run

    def counting_run(self, task="", **kw):
        calls["n"] += 1
        return orig(self, task, **kw)

    monkeypatch.setattr(d.DefaultAgent, "run", counting_run)
    model = FakeModel(script=[SUBMIT])
    backend = MiniSWEBackend(model=model, env=env, step_limit=5, cost_limit=1.0, output_path=tmp / "t.json")
    backend.run_task("t")
    assert calls["n"] == 1
    with pytest.raises(AssertionError):
        backend.run_task("t again")  # one-shot enforced


def test_no_second_autonomous_loop_in_repoproof() -> None:
    """Static guard: RepoProof source never implements its own agent
    loop — no next_action producer, no while-loop that queries a model."""
    src = REPO / "src" / "repoproof"
    offenders = []
    for p in src.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        if "def next_action" in text:
            offenders.append(f"{p.name}: next_action")
        if "while True" in text and ".query(" in text:
            offenders.append(f"{p.name}: while-loop+model.query")
    assert not offenders, offenders
