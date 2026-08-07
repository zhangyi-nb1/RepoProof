"""Gate 4A — budget-awareness observation tests.

The ONE ablation variable: observations optionally carry a
budget_state built from the harness's REAL counters plus a short text
summary. Nothing else changes — pinned here.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from repoproof.agents.backend import MiniSWEBackend
from repoproof.agents.fake_model import FakeModel
from repoproof.agents.repoproof_env import RepoProofEnvironment
from repoproof.execution.docker_backend import DockerExecutionBackend
from repoproof.execution.profiles import agent_profile
from repoproof.persistence.run_store import FileRunStore

REPO = Path(__file__).resolve().parent.parent
IMAGE = "python:3.12-slim-bookworm"
docker_ok, _ = DockerExecutionBackend.available()
needs_docker = pytest.mark.skipif(not docker_ok, reason="docker daemon not reachable")

SUBMIT = {"content": "done", "actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}]}
BUDGET_KEYS = (
    "model_calls_used",
    "model_calls_remaining",
    "agent_commands_used",
    "agent_commands_remaining",
    "wall_time_remaining_seconds",
    "patch_files_remaining",
    "patch_lines_remaining",
)


@pytest.fixture()
def rig():
    import shutil
    import subprocess

    tmp = REPO / "runs" / f"_g4a-{uuid.uuid4().hex[:8]}"
    for name in ("upstream", "workspace", "adaptation", "venv"):
        (tmp / name).mkdir(parents=True)
    (tmp / "upstream" / "README.md").write_text("pinned\n")
    backend = DockerExecutionBackend(image=IMAGE)
    profile = agent_profile(
        upstream=tmp / "upstream", agent_workspace=tmp / "workspace",
        adaptation=tmp / "adaptation", venv=tmp / "venv",
    )
    kwargs = profile.start_kwargs()
    kwargs["user"] = f"{os.getuid()}:{os.getgid()}"
    cid = backend.start(name_prefix="rp-4a", **kwargs)
    store = FileRunStore(tmp / "run")
    env = RepoProofEnvironment(
        backend=backend, container=cid, store=store, command_timeout_s=60, command_budget=10,
        budget_visibility=True, model_call_limit=20, wall_limit_s=1800,
        adaptation_dir=tmp / "adaptation", patch_files_limit=8, patch_lines_limit=400,
    )
    yield backend, cid, store, env, tmp
    backend.destroy(cid)
    subprocess.run(["chmod", "-R", "u+w", str(tmp)], capture_output=True)
    shutil.rmtree(tmp, ignore_errors=True)


@needs_docker
def test_budget_state_matches_counters_every_observation(rig) -> None:
    _b, _c, _s, env, tmp = rig
    model = FakeModel(script=[
        {"content": "a", "actions": [{"command": "echo one"}]},
        {"content": "b", "actions": [{"command": "echo two"}, {"command": "echo three"}]},
        SUBMIT,
    ])
    backend = MiniSWEBackend(model=model, env=env, step_limit=20, cost_limit=1.0, output_path=tmp / "t.json")
    result = backend.run_task("t")
    assert result.exit_status == "Submitted"
    # every observation carries all seven fields + a visible summary
    flat = [o for outs in model.observed for o in outs]
    for o in flat:
        bs = o["extra"]["budget_state"]
        for key in BUDGET_KEYS:
            assert key in bs, f"missing {key}"
        assert "[BUDGET]" in o["output"]
        assert bs["agent_commands_used"] + bs["agent_commands_remaining"] == 10
        assert bs["model_calls_used"] + bs["model_calls_remaining"] == 20


@needs_docker
def test_multi_action_reply_decrements_per_command(rig) -> None:
    _b, _c, _s, env, tmp = rig
    model = FakeModel(script=[
        {"content": "two", "actions": [{"command": "echo A"}, {"command": "echo B"}]},
        SUBMIT,
    ])
    backend = MiniSWEBackend(model=model, env=env, step_limit=20, cost_limit=1.0, output_path=tmp / "t.json")
    backend.run_task("t")
    outs = model.observed[0]
    assert outs[0]["extra"]["budget_state"]["agent_commands_used"] == 1
    assert outs[0]["extra"]["budget_state"]["agent_commands_remaining"] == 9
    assert outs[1]["extra"]["budget_state"]["agent_commands_used"] == 2
    assert outs[1]["extra"]["budget_state"]["agent_commands_remaining"] == 8


@needs_docker
def test_model_call_remaining_decrements_per_call(rig) -> None:
    _b, _c, _s, env, tmp = rig
    model = FakeModel(script=[
        {"content": "1", "actions": [{"command": "echo x"}]},
        {"content": "2", "actions": [{"command": "echo y"}]},
        SUBMIT,
    ])
    backend = MiniSWEBackend(model=model, env=env, step_limit=20, cost_limit=1.0, output_path=tmp / "t.json")
    backend.run_task("t")
    used = [outs[0]["extra"]["budget_state"]["model_calls_used"] for outs in model.observed]
    # the submit action raises Submitted inside execute(), so its
    # observation never flows back — only the first two are observed,
    # each showing the LIVE n_calls at observation time.
    assert used == [1, 2]


def test_threshold_flags() -> None:
    env = RepoProofEnvironment(
        backend=None, container="", store=None, command_timeout_s=1, command_budget=40,
        budget_visibility=True, model_call_limit=20, wall_limit_s=100,
        patch_files_limit=8, patch_lines_limit=400,
    )
    for used, low, crit, final in ((10, False, False, False), (15, True, False, False),
                                   (17, True, True, False), (19, True, True, True)):
        env.model_calls_provider = lambda u=used: u
        st = env._budget_state()
        assert (st["low_budget"], st["critical_budget"], st["final_model_call"]) == (low, crit, final)
        summary = env._budget_summary(st)
        assert f"({20 - used} remaining)" in summary


def test_budget_text_contains_no_oracle_or_test_knowledge() -> None:
    env = RepoProofEnvironment(
        backend=None, container="", store=None, command_timeout_s=1, command_budget=40,
        budget_visibility=True, model_call_limit=20, wall_limit_s=100,
        patch_files_limit=8, patch_lines_limit=400,
    )
    env.model_calls_provider = lambda: 19
    st = env._budget_state()
    blob = (env._budget_summary(st) + str(st)).lower()
    for forbidden in ("oracle", "held_out", "heldout", "test_", "fixture", "reference"):
        assert forbidden not in blob, f"budget surface leaked {forbidden!r}"


def test_enhancement_touches_only_the_environment() -> None:
    """Policy, verifiers and the completion gate are byte-level free of
    the budget-visibility feature — the ablation variable lives ONLY in
    the environment layer."""
    src = REPO / "src" / "repoproof"
    for rel in ("harness/policy.py", "verification/verifiers.py", "verification/completion_gate.py"):
        text = (src / rel).read_text(encoding="utf-8")
        assert "budget_visibility" not in text and "_budget_summary" not in text, rel


def test_visibility_off_preserves_gate3_shape() -> None:
    env = RepoProofEnvironment(
        backend=None, container="", store=None, command_timeout_s=1, command_budget=40,
        budget_visibility=False,
    )
    st = env._budget_state()
    assert set(st) == {"commands_used", "command_budget", "denied"}  # exact Gate 3 shape
