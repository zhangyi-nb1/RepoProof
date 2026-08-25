"""Gate 3B.F — model preflight: minimal, non-business, host-only.

Validates provider alias, auth, api base, native bash tool-call
parsing, usage/cost accounting, trajectory serialization and
temperature compatibility BEFORE any real task. The API key exists
only in this host process — never in containers, trace, or artifacts.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

def load_provider_env() -> dict:
    """Gate 4A decoupling: official runs read ONLY host env vars
    (REPOPROOF_API_BASE / REPOPROOF_API_KEY / REPOPROOF_MODEL)."""
    base = os.environ.get("REPOPROOF_API_BASE", "")
    key = os.environ.get("REPOPROOF_API_KEY", "")
    if not base or not key:
        raise RuntimeError("set REPOPROOF_API_BASE and REPOPROOF_API_KEY")
    os.environ["OPENAI_API_KEY"] = key
    os.environ["OPENAI_BASE_URL"] = base
    os.environ["OPENAI_API_BASE"] = base
    return {"api_base_set": True, "key_chars": len(key)}


def main() -> int:
    model_name = "openai/" + os.environ.get("REPOPROOF_MODEL", "gpt-5.6-terra")
    meta = load_provider_env()
    report: dict = {"model_name": model_name, "api_base_set": meta["api_base_set"]}

    from minisweagent.models.litellm_model import LitellmModel

    from repoproof.agents.backend import MiniSWEBackend
    from repoproof.agents.repoproof_env import RepoProofEnvironment
    from repoproof.execution.docker_backend import DockerExecutionBackend
    from repoproof.execution.profiles import agent_profile
    from repoproof.persistence.run_store import FileRunStore

    # temperature probe: prefer 0; fall back to provider default on rejection
    temperature_mode = "0"
    try:
        model = LitellmModel(model_name=model_name, model_kwargs={"temperature": 0})
        probe = model.query([
            {"role": "system", "content": "Reply by calling the bash tool."},
            {"role": "user", "content": "Run: echo PREFLIGHT_OK"},
        ])
    except Exception as exc:  # noqa: BLE001
        report["temperature0_error"] = f"{type(exc).__name__}: {exc}"[:300]
        temperature_mode = "provider_default"
        model = LitellmModel(model_name=model_name)
        probe = model.query([
            {"role": "system", "content": "Reply by calling the bash tool."},
            {"role": "user", "content": "Run: echo PREFLIGHT_OK"},
        ])
    report["temperature"] = temperature_mode
    actions = probe.get("extra", {}).get("actions", [])
    report["native_toolcall_actions"] = len(actions)
    report["probe_cost_field"] = probe.get("extra", {}).get("cost", None)
    if not actions:
        report["action_protocol"] = "native_FAILED"
        print(json.dumps(report, indent=2))
        return 1
    report["action_protocol"] = "native"

    # micro end-to-end: echo READY then submit, in a throwaway container
    tmp = REPO / "runs" / f"_preflight-{uuid.uuid4().hex[:8]}"
    for name in ("upstream", "workspace", "adaptation", "venv"):
        (tmp / name).mkdir(parents=True)
    backend = DockerExecutionBackend(image="python:3.12-slim-bookworm")
    profile = agent_profile(
        upstream=tmp / "upstream", agent_workspace=tmp / "workspace",
        adaptation=tmp / "adaptation", venv=tmp / "venv",
    )
    kwargs = profile.start_kwargs()
    kwargs["user"] = f"{os.getuid()}:{os.getgid()}"
    cid = backend.start(name_prefix="rp-preflight", **kwargs)
    try:
        store = FileRunStore(tmp / "run")
        env = RepoProofEnvironment(backend=backend, container=cid, store=store,
                                   command_timeout_s=60, command_budget=6)
        mkwargs = {"temperature": 0} if temperature_mode == "0" else {}
        agent_model = LitellmModel(model_name=model_name, model_kwargs=mkwargs)
        b = MiniSWEBackend(model=agent_model, env=env, step_limit=4, cost_limit=1.0,
                           output_path=tmp / "trajectory.json")
        result = b.run_task(
            "This is a harness preflight, not a real task. Run exactly one command: "
            "echo READY. After you see READY, submit by running: "
            "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        )
        report["micro_run"] = {
            "exit_status": result.exit_status,
            "model_calls": result.n_model_calls,
            "commands": result.commands_used,
            "cost": result.cost,
        }
        traj = json.loads((tmp / "trajectory.json").read_text())
        report["trajectory_serialized"] = traj["trajectory_format"]
        report["usage_recorded"] = traj["info"]["model_stats"]
        raw = json.dumps(traj)
        key = os.environ["OPENAI_API_KEY"]
        report["key_leak_in_trajectory"] = key in raw
    finally:
        backend.destroy(cid)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    ok = report["micro_run"]["exit_status"] == "Submitted" and not report["key_leak_in_trajectory"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
