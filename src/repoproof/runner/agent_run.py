"""Gate 3C — the one real agent baseline run.

Order of operations (frozen):
  ProviderAdmissionGate (60s, BEFORE any agent container)
  → agent venv provisioning (identical pinned env)
  → ONE mini-swe-agent DefaultAgent.run inside the agent-profile
    container (upstream ro, consumer ro, adaptation rw, /tmp scratch,
    network=none; no oracle/held-out/probes/harness/evidence/socket/keys)
  → freeze AdaptationManifest, destroy the agent container
  → independent verification (Capability → HostRegression → Policy)
  → clean_adoption replay ONLY if all three passed (fresh everything,
    zero model calls, zero agent commands); otherwise an optional
    failure_reproduction replay as evidence
  → Completion Gate → run manifest binding provider_config_sha256.

Never: feeding oracle failures back to the agent, hand-patching the
adapter, silent model switching, a second autonomous loop.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from repoproof.agents.provider_gate import (
    PreflightResult,
    ProviderConfig,
    Transport,
    run_preflight,
)
from repoproof.domain.models import VerificationResult, sha256_bytes
from repoproof.execution.docker_backend import Mount
from repoproof.harness.adaptation import PatchBudgetExceeded, freeze_adaptation, verify_frozen
from repoproof.harness.budget import BudgetMeter
from repoproof.harness.oracle_guard import hash_tree, make_read_only
from repoproof.harness.trace import verify_chain
from repoproof.runner.baseline import IMAGE, _Runner, _skip_symlink_tree, ensure_upstream
from repoproof.verification import completion_gate
from repoproof.verification.verifiers import (
    REPLAY_MODE_BASELINE,
    REPLAY_MODE_CLEAN,
    policy_result,
    replay_result,
)


def admit_or_block(
    config: ProviderConfig,
    *,
    transport: Transport | None = None,
    backend_factory: Callable[[], object],
) -> dict:
    """Provider admission wiring: the backend factory runs ONLY on
    PROVIDER_READY — a blocked preflight can never construct the agent
    backend, so agent_model_call_count is structurally 0."""
    pf = run_preflight(config, transport=transport)
    if not pf.ready:
        return {
            "blocked": True,
            "preflight": pf.summary(),
            "agent_model_call_count": 0,
            "agent_command_count": 0,
        }
    backend = backend_factory()
    return {
        "blocked": False,
        "preflight": pf.summary(),
        "backend": backend,
        "run_binding": {
            "provider_config_sha256": pf.provider_config_sha256,
            "action_protocol": pf.action_protocol,
            "temperature": pf.temperature,
        },
    }


AGENT_PROMPT_TEMPLATE = """You are adopting a capability from a pinned open-source repo \
into a host project, fully offline.

GOAL
{statement}

FROZEN PARAMETERS (from the pinned upstream API)
- strategies: {strategies}
- tokenizer: {tokenizer}
- chunk_size: {chunk_size}
- chunk_overlap (sentence strategy only): {chunk_overlap}
- units semantics: {units}

POST-PROCESSING RULES (contract-frozen)
- R1: whitespace-only documents yield ZERO records.
- R2: an indivisible over-size chunk from upstream is preserved verbatim (never re-split).

YOUR ENVIRONMENT (network=none; everything is already installed)
- /upstream        read-only pinned source checkout of the candidate repo
- /consumer        read-only host consumer fixture (python package under /consumer/src/rag_consumer)
- /consumer/sample_documents.json   public sample inputs you may test with
- /adaptation      THE ONLY PERSISTENT WRITABLE ZONE — your deliverable goes here
- /venv/env/bin/python   pinned python with chonkie 1.7.0 + pytest preinstalled
- /tmp             scratch (destroyed afterwards)

DELIVERABLE
Write /adaptation/adapter.py exposing:
    def chunk_documents(request: dict) -> dict
The host loads it automatically (rag_consumer.chunk_documents delegates to it when
REPOPROOF_ADAPTATION_DIR is set — it already is: try
  PYTHONPATH=/consumer/src REPOPROOF_ADAPTATION_DIR=/adaptation \
  /venv/env/bin/python -c "from rag_consumer import chunk_documents; ..."
). Request shape: {{"documents": [{{"document_id", "text", "metadata"}}...],
"strategy": "sentence"|"recursive", "chunk_size": int}}.
Each output record must carry exactly these fields:
    chunk_id, document_id, ordinal, text, char_start, char_end, units, metadata
with stable deterministic chunk ids (never upstream per-call ids), document input order,
per-document ordinals from 0, offsets that slice back into the source text, metadata passthrough,
upstream errors wrapped as rag_consumer.chunking.ConsumerChunkingError.
The chunk text/order/boundaries must come from the real chonkie chunkers for the requested strategy.

BUDGETS
- model calls: {step_limit}; executed commands: {command_budget}; per-command timeout {cmd_timeout}s.
Acceptance is judged AFTER you finish by tests you cannot see; there is no partial credit for claims.
When done, submit with: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"""


class AgentRunner(_Runner):
    """Gate 3C runner. Reuses the hardened baseline infrastructure; adds
    the single agent phase between setup and verification."""

    def run_agent(
        self, provider: ProviderConfig, preflight: PreflightResult, *, budget_visibility: bool = False
    ) -> dict:
        import os as _os

        # Proxy-custom model aliases (e.g. deepseek-v4-pro) are absent
        # from litellm's price map; without this the FIRST model call
        # dies in cost tracking (observed run 20260807-145003). Official
        # mini-swe-agent escape hatch — cost stays honestly UNKNOWN.
        _os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")
        _os.environ["OPENAI_API_KEY"] = provider.api_key
        _os.environ["OPENAI_API_BASE"] = provider.api_base
        _os.environ["OPENAI_BASE_URL"] = provider.api_base
        from minisweagent.models.litellm_model import LitellmModel
        from minisweagent.models.litellm_textbased_model import LitellmTextbasedModel

        from repoproof.agents.backend import MiniSWEBackend
        from repoproof.agents.repoproof_env import RepoProofEnvironment

        ev = self.store.append_event
        t0 = time.monotonic()
        ev(
            "run.start",
            actor="runner",
            payload={
                "run_id": self.run_id,
                "mode": "real-agent-baseline",
                "budget_visibility": budget_visibility,
                "agent": "mini-swe-agent-2.4.6",
                "task_package_root_hash": self.package.root_hash,
                "provider_config_sha256": preflight.provider_config_sha256,
            },
        )
        ev("contract.frozen", actor="harness", payload={"task_id": self.contract.task_id, "sha256": self.contract_sha})
        ev("task_package.verified", actor="harness", payload={"root_hash": self.package.root_hash})
        ev("provider.admitted", actor="harness", payload=preflight.summary())

        missing_external: list[str] = []
        budget_exhausted: str | None = None
        adaptation_manifest = None
        agent_metrics: dict = {"model_calls": 0, "commands": 0, "denied": 0, "exit_status": None, "cost": "UNKNOWN"}
        setup_meter = BudgetMeter(self.contract.budgets)

        ok, server = self.backend.available()
        if not ok:
            missing_external.append(f"docker unavailable: {server}")
        first = replay = None
        rep = None
        replay_mode = None
        oracle_before: dict = {}
        upstream_before: dict = {}
        upstream = oracle_snap = adaptation = wheelhouse = None
        prompt_sha = trajectory_sha = None

        if not missing_external:
            self.backend.pull()
            digest = self.backend.image_digest()
            if digest:
                self.image_ref = digest
            upstream, repo_manifest = ensure_upstream(self.project_root / "upstream-cache", self.contract.source_repo)
            if repo_manifest.git_tree_hash != self.package.source_git_tree_hash:
                missing_external.append("upstream git tree hash != task package binding")
        if not missing_external:
            ev("upstream.pinned", actor="harness", payload=repo_manifest.model_dump())
            wheelhouse, wh_manifest = self.ensure_wheelhouse(upstream, setup_meter)
            ev("wheelhouse.frozen", actor="harness", payload={"root": wh_manifest["root"]})

            import shutil

            oracle_snap = self.store.run_dir / "oracle_snapshot"
            shutil.copytree(self.oracle_src, oracle_snap)
            make_read_only(oracle_snap)
            adaptation = self.store.run_dir / "adaptation"
            adaptation.mkdir(exist_ok=True)
            oracle_before = hash_tree(oracle_snap)
            upstream_before = _skip_symlink_tree(upstream)
            ev("oracle.hashed", actor="harness", payload={"files": len(oracle_before)})

            # ---------------- agent phase ----------------
            agent_meter = BudgetMeter(self.contract.budgets)
            venv_dir = self._install_phase("agent", wheelhouse, agent_meter)
            command_budget = self.contract.budgets.max_agent_steps * 2  # commands ≠ model calls
            cmd_timeout = self.contract.budgets.max_command_minutes * 60
            c_agent = self.backend.start(
                name_prefix="rp-agent",
                network="none",
                mounts=[
                    Mount(upstream, "/upstream", True),
                    Mount(self.consumer_src, "/consumer", True),
                    Mount(adaptation, "/adaptation", False),
                    Mount(venv_dir, "/venv", True),
                ],
                env={
                    "PYTHONPATH": "/consumer/src",
                    "REPOPROOF_ADAPTATION_DIR": "/adaptation",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONHASHSEED": "0",
                    "HOME": "/tmp",
                },
                user=self.user,
                image_ref=self.image_ref,
            )
            t_agent = time.monotonic()
            try:
                security = self.backend.inspect_security(c_agent)
                ev("container.security", actor="harness", payload={"label": "agent", **security})
                assert str(security.get("network_mode")) == "none"

                cap = self.contract.capability
                prompt = AGENT_PROMPT_TEMPLATE.format(
                    statement=cap.statement.strip(),
                    strategies=", ".join(cap.params.strategies) if cap.params else "sentence",
                    tokenizer=cap.params.tokenizer if cap.params else "character",
                    chunk_size=cap.params.chunk_size if cap.params else 120,
                    chunk_overlap=cap.params.chunk_overlap if cap.params else 0,
                    units=(cap.units_semantics or "").strip(),
                    step_limit=self.contract.budgets.max_agent_steps,
                    command_budget=command_budget,
                    cmd_timeout=cmd_timeout,
                )
                prompt_sha = sha256_bytes(prompt.encode())
                ev("agent.prompt", actor="harness", payload={"sha256": prompt_sha, "chars": len(prompt)})

                env = RepoProofEnvironment(
                    backend=self.backend,
                    container=c_agent,
                    store=self.store,
                    command_timeout_s=cmd_timeout,
                    command_budget=command_budget,
                    budget_visibility=budget_visibility,
                    model_call_limit=self.contract.budgets.max_agent_steps,
                    wall_limit_s=self.contract.budgets.max_wall_time_minutes * 60,
                    adaptation_dir=adaptation,
                    patch_files_limit=self.contract.budgets.max_patch_files,
                    patch_lines_limit=self.contract.budgets.max_patch_lines,
                )
                if preflight.action_protocol == "textbased":
                    model_cls = LitellmTextbasedModel
                else:
                    model_cls = LitellmModel
                mkwargs = {"temperature": 0} if preflight.temperature == "0" else {}
                model = model_cls(model_name=f"openai/{provider.model_name}", model_kwargs=mkwargs)
                backend = MiniSWEBackend(
                    model=model,
                    env=env,
                    step_limit=self.contract.budgets.max_agent_steps,
                    cost_limit=self.contract.budgets.monetary_soft_cap_usd,
                    output_path=self.store.run_dir / "trajectory.json",
                )
                result = backend.run_task(prompt)
                agent_metrics = {
                    "model_calls": result.n_model_calls,
                    "commands": result.commands_used,
                    "denied": result.denied_count,
                    "exit_status": result.exit_status,
                    "cost": result.cost,
                    "agent_wall_s": round(time.monotonic() - t_agent, 1),
                }
                ev("agent.end", actor="harness", payload=agent_metrics)
            finally:
                self.backend.destroy(c_agent)
            self.timings["agent_model_call_s"] = round(time.monotonic() - t_agent, 1)

            traj_path = self.store.run_dir / "trajectory.json"
            if traj_path.exists():
                raw = traj_path.read_bytes()
                assert provider.api_key.encode() not in raw, "API key leaked into trajectory"
                trajectory_sha = self.store.store_artifact(
                    raw, media_type="application/json", producer="agent", name_hint="trajectory.json"
                ).sha256
                ev("agent.trajectory", actor="harness", payload={"sha256": trajectory_sha})

            # ---------------- freeze adaptation, then verify ----------------
            try:
                adaptation_manifest = freeze_adaptation(adaptation, self.contract.budgets)
                self.store.save_json("adaptation_manifest.json", adaptation_manifest.model_dump())
                ev(
                    "adaptation.frozen",
                    actor="harness",
                    payload={
                        "files": adaptation_manifest.total_files,
                        "lines": adaptation_manifest.total_lines,
                        "root": adaptation_manifest.tree_root_sha256,
                    },
                )
            except PatchBudgetExceeded as exc:
                budget_exhausted = str(exc)

        self.timings["system_setup_s"] = round(time.monotonic() - t0 - self.timings["agent_model_call_s"], 1)

        if not missing_external and budget_exhausted is None:
            try:
                t1 = time.monotonic()
                first = self.one_pass("primary", upstream, oracle_snap, adaptation, wheelhouse)
                self.timings["verification_s"] = round(time.monotonic() - t1, 1)
            except Exception as exc:  # noqa: BLE001
                missing_external.append(f"verification infrastructure failure: {exc}")

        recheck_ok, recheck_detail = (
            verify_frozen(adaptation, adaptation_manifest)
            if adaptation_manifest is not None and adaptation is not None
            else (False, "adaptation never frozen")
        )

        if first is not None:
            cap_vr = self._completion_vr_public("CapabilityVerifier", first, capability=True)
            reg_vr = self._completion_vr_public("HostRegressionVerifier", first, capability=False)
        else:
            cap_vr = VerificationResult(verifier="CapabilityVerifier", passed=False, detail="not run")
            reg_vr = VerificationResult(verifier="HostRegressionVerifier", passed=False, detail="not run")

        from repoproof.domain.models import AdaptationManifest as _AM

        pol_vr = policy_result(
            trace_path=self.store.trace_path,
            oracle_before=oracle_before,
            oracle_after=hash_tree(oracle_snap) if oracle_snap else {},
            upstream_before=upstream_before,
            upstream_after=_skip_symlink_tree(upstream) if upstream else {},
            adaptation_manifest=adaptation_manifest or _AM(),
            adaptation_recheck_ok=recheck_ok,
            adaptation_recheck_detail=recheck_detail,
            budgets=self.contract.budgets,
            evidence=[],
        )

        if first is not None and cap_vr.passed and reg_vr.passed and pol_vr.passed:
            replay_mode = REPLAY_MODE_CLEAN
        elif first is not None:
            replay_mode = REPLAY_MODE_BASELINE
        if replay_mode is not None:
            try:
                t2 = time.monotonic()
                replay = self.one_pass("replay", upstream, oracle_snap, adaptation, wheelhouse)
                self.timings["replay_s"] = round(time.monotonic() - t2, 1)
                rep = replay_result(
                    first=first.summary(), replay=replay.summary(), mode=replay_mode,
                    evidence=[first.probe_normalized_sha],
                )
                rep.extra["replay_model_calls"] = 0
                rep.extra["replay_agent_commands"] = 0
            except Exception as exc:  # noqa: BLE001
                rep = VerificationResult(
                    verifier="ReplayVerifier", passed=False, detail=f"replay infrastructure failure: {exc}",
                    extra={"mode": replay_mode},
                )

        vr_hashes: dict[str, str] = {}
        for r in (cap_vr, reg_vr, pol_vr) + ((rep,) if rep else ()):
            path = self.store.save_verification(r)
            ref = self.store.store_artifact(
                path.read_bytes(), media_type="application/json", producer="verification", name_hint=path.name
            )
            vr_hashes[r.verifier] = ref.sha256
            ev(
                "verification.result",
                actor=r.verifier,
                payload={"passed": r.passed, "detail": r.detail, "result_sha256": ref.sha256},
                artifact_refs=[ref.sha256],
            )

        gate = completion_gate.decide(
            capability=cap_vr,
            regression=reg_vr,
            policy=pol_vr,
            replay=rep,
            adaptation=adaptation_manifest,
            missing_external=missing_external,
            budget_exhausted=budget_exhausted,
        )
        ev(
            "gate.verdict",
            actor="completion-gate",
            payload={**gate.model_dump(mode="json"), "verification_input_hashes": vr_hashes},
        )
        self.timings["total_wall_s"] = round(time.monotonic() - t0, 1)
        ev("run.end", actor="runner", payload={"verdict": gate.verdict.value, "timings": self.timings})

        chain_ok, n_events, chain_err = verify_chain(self.store.trace_path)
        from repoproof.domain.models import sha256_file

        final_trace_sha = sha256_file(self.store.trace_path)
        run_manifest = {
            "run_id": self.run_id,
            "task_id": self.contract.task_id,
            "mode": "real-agent-baseline",
            "budget_visibility": budget_visibility,
            "task_package_root_hash": self.package.root_hash,
            "contract_sha256": self.contract_sha,
            "provider_config_sha256": preflight.provider_config_sha256,
            "action_protocol": preflight.action_protocol,
            "temperature": preflight.temperature,
            "preflight": preflight.summary(),
            "agent": agent_metrics,
            "prompt_sha256": prompt_sha,
            "trajectory_sha256": trajectory_sha,
            "source_git_tree_hash": self.package.source_git_tree_hash,
            "image_digest": self.image_ref if self.image_ref != IMAGE else None,
            "wheelhouse_root": self.package.wheelhouse_root,
            "adaptation_root": adaptation_manifest.tree_root_sha256 if adaptation_manifest else None,
            "verification_result_hashes": vr_hashes,
            "missing_external": missing_external,
            "budget_exhausted": budget_exhausted,
            "final_trace_sha256": final_trace_sha,
            "trace_events": n_events,
            "trace_chain_ok": chain_ok,
            "verdict": gate.verdict.value,
            "final_verdict": gate.verdict.value,
            "timings": self.timings,
        }
        self.store.save_json("run_manifest.json", run_manifest)
        report = {
            **run_manifest,
            "gate_reasons": gate.reasons,
            "capability": cap_vr.detail,
            "regression": reg_vr.detail,
            "policy": pol_vr.detail,
            "replay": rep.detail if rep else None,
            "capability_failed_tests": first.capability_failed if first else [],
            "trace_chain_error": chain_err,
        }
        self.store.save_json("report.json", report)
        return report

    def _completion_vr_public(self, verifier: str, outcome, *, capability: bool) -> VerificationResult:
        completion = outcome.capability_completion if capability else outcome.regression_completion
        exit_code = outcome.capability_exit if capability else outcome.regression_exit
        evidence = outcome.capability_stdout_sha if capability else outcome.regression_stdout_sha
        x = completion.extra
        return VerificationResult(
            verifier=verifier,
            passed=completion.ok,
            detail=(
                f"passed_checks={x['passed_count']}, failed_checks={len(x['failed_nodes'])}, "
                f"total_checks={x['expected_count']}; {completion.detail}"
            ),
            evidence=[evidence],
            extra={"exit_code": exit_code, **x},
        )


def provider_from_env() -> ProviderConfig:
    """Official runs read ONLY host env vars (Gate 4A decoupling):
    REPOPROOF_API_BASE / REPOPROOF_API_KEY / REPOPROOF_MODEL
    (compatible aliases REPOPROOF_BASE_URL / REPOPROOF_MODEL_NAME).
    RepoProof never reads any other project's .env; the key never
    reaches the repo, trace or artifacts."""
    import os

    base = os.environ.get("REPOPROOF_API_BASE") or os.environ.get("REPOPROOF_BASE_URL")
    key = os.environ.get("REPOPROOF_API_KEY")
    model = os.environ.get("REPOPROOF_MODEL") or os.environ.get("REPOPROOF_MODEL_NAME")
    pairs = (("REPOPROOF_API_BASE", base), ("REPOPROOF_API_KEY", key), ("REPOPROOF_MODEL", model))
    missing = [n for n, v in pairs if not v]
    if missing:
        raise RuntimeError(f"provider env vars missing: {missing}")
    return ProviderConfig(
        provider="openai-compatible", model_name=model, api_base=base.rstrip("/"), api_key=key
    )


def run_gate3c(
    contract_path: Path,
    project_root: Path,
    provider: ProviderConfig,
    *,
    budget_visibility: bool = False,
) -> dict:
    """CLI entry: real preflight → BLOCKED stop or the single agent run."""
    pf = run_preflight(provider)
    evidence_dir = project_root / "docs" / "evidence" / "gate3-preflight"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "latest_preflight.json").write_text(
        json.dumps(pf.summary(), indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    if not pf.ready:
        return {"blocked": True, "preflight": pf.summary(), "agent_model_call_count": 0}
    runner = AgentRunner(contract_path, project_root, None)
    try:
        report = runner.run_agent(provider, pf, budget_visibility=budget_visibility)
    finally:
        runner.backend.destroy_all()
    return {"blocked": False, "preflight": pf.summary(), "report": report}
