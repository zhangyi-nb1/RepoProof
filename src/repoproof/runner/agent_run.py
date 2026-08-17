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
from repoproof.domain.models import TaskContract, VerificationResult, sha256_bytes
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


def render_agent_prompt(
    contract,
    *,
    command_budget: int,
    cmd_timeout: int,
    installed_note: str,
    sample_inputs_line: str = "",
    spec=None,
) -> str:
    """Fully CONTRACT-DRIVEN agent prompt.

    Every task-specific token comes from the contract (statement,
    params, target package/entry point) or the frozen package
    (installed distribution note). The Gate 6 run proved why: the old
    module-level template carried hardcoded chonkie deliverable text
    ('chunk_documents', 'document_id', 'ConsumerChunkingError') into
    OTHER tasks' prompts, and the agent trusted the contaminated
    request shape over the consumer source it had already read
    (HARNESS_PROMPT_CONTAMINATION in docs/FAILURE_TAXONOMY.md).
    """
    cap = contract.capability
    target = contract.target_project
    parts = [
        "You are adopting a capability from a pinned open-source repo "
        "into a host project, fully offline.",
        f"GOAL\n{cap.statement.strip()}",
    ]
    if cap.params is not None:
        params = [
            f"- strategies: {', '.join(cap.params.strategies)}",
            f"- tokenizer: {cap.params.tokenizer}",
            f"- chunk_size: {cap.params.chunk_size}",
            f"- chunk_overlap (sentence strategy only): {cap.params.chunk_overlap}",
        ]
        if cap.units_semantics:
            params.append(f"- units semantics: {cap.units_semantics.strip()}")
        parts.append("FROZEN PARAMETERS (from the pinned upstream API)\n" + "\n".join(params))
    parts.append(
        "YOUR ENVIRONMENT (network=none; everything is already installed)\n"
        "- /upstream        read-only pinned source checkout of the candidate repo\n"
        f"- /consumer        read-only host consumer fixture (python package under /consumer/src/{target.package})\n"
        f"{sample_inputs_line}"
        "- /adaptation      THE ONLY PERSISTENT WRITABLE ZONE — your deliverable goes here\n"
        f"- /venv/env/bin/python   pinned python with {installed_note} + pytest preinstalled\n"
        "- /tmp             scratch (destroyed afterwards)"
    )
    parts.append(
        "DELIVERABLE\n"
        "Write /adaptation/adapter.py exposing:\n"
        f"    def {target.entry_point}(request: dict) -> dict\n"
        f"The host loads it automatically ({target.package}.{target.entry_point} delegates to it when\n"
        "REPOPROOF_ADAPTATION_DIR is set — it already is: try\n"
        "  PYTHONPATH=/consumer/src REPOPROOF_ADAPTATION_DIR=/adaptation \\\n"
        f'  /venv/env/bin/python -c "from {target.package} import {target.entry_point}; ..."\n'
        ").\n"
        "The exact request/response field names, record schema and error-wrapping\n"
        "contract are defined by the GOAL above and by the host consumer source:\n"
        f"read /consumer/src/{target.package}/ and treat it as AUTHORITATIVE for\n"
        "field names and shapes — do not invent or rename fields."
    )
    if spec is not None:
        req_lines: list[str] = []
        for r in spec.requirements:
            text = " ".join(r.public_text.split())
            req_lines.append(f"[{r.id}] ({r.owner}, {r.severity}) {text}")
            for ex in r.examples:
                req_lines.append(f"    e.g. {ex}")
        parts.append("REQUIREMENTS (each is verified; owners below)\n" + "\n".join(req_lines))
        matrix = spec.responsibility_matrix()
        matrix_lines = [f"- {owner}: {', '.join(ids)}" for owner, ids in matrix.items()]
        parts.append(
            "RESPONSIBILITY MATRIX\n"
            + "\n".join(matrix_lines)
            + "\nHOST_INPUT_GUARD requirements are ALREADY IMPLEMENTED by the host "
            "(see the consumer source) — do not re-implement or bypass them. "
            "HARNESS/UPSTREAM rows are enforced outside your code. "
            "Your adapter owns exactly the ADAPTER rows."
        )
        parts.append(
            "PUBLIC EXAMPLES AND RUNNABLE PUBLIC TESTS\n"
            "- /consumer/public_examples/truth_table.json   the boolean truth table + error-code cases\n"
            "- /consumer/public_tests/   public contract tests you SHOULD run before submitting:\n"
            "  PYTHONPATH=/consumer/src REPOPROOF_ADAPTATION_DIR=/adaptation \\\n"
            "    /venv/env/bin/python -m pytest -q /consumer/public_tests\n"
            "These cover the public semantics only; final acceptance additionally runs "
            "held-out inputs of the SAME public semantics."
        )
    parts.append(
        "BUDGETS\n"
        f"- model calls: {contract.budgets.max_agent_steps}; executed commands: {command_budget}; "
        f"per-command timeout {cmd_timeout}s.\n"
        "Acceptance is judged AFTER you finish by tests you cannot see; there is no partial "
        "credit for claims.\n"
        "When done, submit with: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
    )
    return "\n\n".join(parts)


def render_task_prompt(contract, *, environment_constraints: dict | None, project_root: Path):
    """The ONE Contract -> Prompt projection, shared verbatim by
    freeze (PromptManifest), the ContractAdequacyGate and the real run
    — three call sites, one renderer, so the projection cannot drift.
    Returns (prompt, spec_or_None, spec_sha_or_None)."""
    from repoproof.harness.requirement_spec import load_requirement_spec

    spec = spec_sha = None
    if contract.requirement_spec_file:
        spec_path = project_root / "contracts" / contract.requirement_spec_file
        spec, spec_sha = load_requirement_spec(spec_path)
    version = (environment_constraints or {}).get(contract.source_repo.import_name)
    installed_note = contract.source_repo.distribution + (f" {version}" if version else "")
    consumer_dir = project_root / Path(contract.target_project.path)
    sample_file = consumer_dir / "sample_documents.json"
    sample_line = (
        "- /consumer/sample_documents.json   public sample inputs you may test with\n"
        if sample_file.exists()
        else ""
    )
    prompt = render_agent_prompt(
        contract,
        command_budget=contract.budgets.max_agent_steps * 2,
        cmd_timeout=contract.budgets.max_command_minutes * 60,
        installed_note=installed_note,
        sample_inputs_line=sample_line,
        spec=spec,
    )
    return prompt, spec, spec_sha


def run_adequacy_gate(contract_path: Path, project_root: Path) -> dict:
    """Deterministic pre-agent ContractAdequacyGate (zero model calls).

    For requirement-spec tasks: verifies requirement/oracle/prompt
    mutual adequacy, the frozen PromptManifest projection and the
    frozen control results. Legacy contracts (no spec) pass through
    with adequacy_applicable=False."""
    import json as _json

    from repoproof.harness import task_package
    from repoproof.harness.contract_adequacy import evaluate_adequacy
    from repoproof.harness.prompt_manifest import verify_prompt_manifest

    contract, _sha = TaskContract.load_frozen(contract_path, require_sidecar=True)
    package = task_package.load_and_verify(project_root, contract_path)
    if not contract.requirement_spec_file:
        return {"adequacy_applicable": False, "state": "ADEQUATE", "ok": True, "failures": []}

    prompt, spec, _spec_sha = render_task_prompt(
        contract,
        environment_constraints=package.environment_constraints,
        project_root=project_root,
    )
    coll = _json.loads(task_package.collection_path_for(contract_path).read_text(encoding="utf-8"))
    forbidden = tuple(
        n.split("::", 1)[1].split("[", 1)[0]
        for n in coll.get("capability_nodes", []) + coll.get("regression_nodes", [])
    ) + ("ORACLE CALIBRATION ONLY", "held_out_documents", "8/11", "PASS_ADAPTED", "expected verdict")
    result = evaluate_adequacy(
        spec=spec,
        capability_nodes=coll.get("capability_nodes", []),
        regression_nodes=coll.get("regression_nodes", []),
        rendered_prompt=prompt,
        contract_path=contract_path,
        controls_summary=package.controls_summary,
        forbidden_prompt_tokens=forbidden,
    )
    failures = list(result.failures)
    pm_path = contract_path.parent / (contract_path.stem + ".prompt_manifest.json")
    if not pm_path.exists():
        failures.append("prompt_manifest: file missing (re-run freeze-task --full)")
    else:
        manifest = _json.loads(pm_path.read_text(encoding="utf-8"))
        failures.extend(
            f"prompt_manifest: {f}"
            for f in verify_prompt_manifest(manifest, spec=spec, rendered_prompt=prompt)
        )
    ok = not failures
    return {
        "adequacy_applicable": True,
        "state": "ADEQUATE" if ok else "INVALID_TASK_SPEC",
        "ok": ok,
        "failures": failures,
        "checked": result.checked,
        "prompt_sha256": sha256_bytes(prompt.encode()),
    }


class AgentRunner(_Runner):
    """Gate 3C runner. Reuses the hardened baseline infrastructure; adds
    the single agent phase between setup and verification."""

    def run_agent(
        self,
        provider: ProviderConfig,
        preflight: PreflightResult,
        *,
        budget_visibility: bool = False,
        coverage_ledger: bool = False,
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
                "coverage_ledger": coverage_ledger,
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

                ledger_paragraph = ""
                if coverage_ledger:
                    ledger_paragraph = (
                        "\n\nSELF-TRACKING LEDGER\n"
                        "A checklist built ONLY from the public contract lives at "
                        "/tmp/coverage_ledger.json. Keep each requirement's status updated as you work "
                        "(UNASSESSED/IMPLEMENTED/SELF_TESTED/BLOCKED). Observations show your "
                        "addressed count and unresolved ids; it is a self-tracking aid with no "
                        "acceptance knowledge."
                    )
                base_prompt, _spec, _spec_sha = render_task_prompt(
                    self.contract,
                    environment_constraints=self.package.environment_constraints,
                    project_root=self.project_root,
                )
                prompt = base_prompt + ledger_paragraph
                prompt_sha = sha256_bytes(prompt.encode())
                ev("agent.prompt", actor="harness", payload={"sha256": prompt_sha, "chars": len(prompt)})

                ledger_requirements: list[dict] = []
                if coverage_ledger:
                    from repoproof.harness.coverage_ledger import (
                        LEDGER_PATH,
                        build_requirements,
                        initial_ledger_json,
                    )

                    ledger_requirements = build_requirements(self.contract)
                    seed = initial_ledger_json(self.contract)
                    res_seed = self.backend.exec(
                        c_agent,
                        ["bash", "-lc", f"cat > {LEDGER_PATH} <<'RPLEDGER'\n{seed}\nRPLEDGER"],
                        timeout_s=30,
                    )
                    ev(
                        "ledger.seeded",
                        actor="harness",
                        payload={
                            "requirements": len(ledger_requirements),
                            "exit_code": res_seed.exit_code,
                            "path": LEDGER_PATH,
                        },
                    )
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
                    ledger_enabled=coverage_ledger,
                    ledger_requirements=ledger_requirements,
                )

                # Aggregate REAL token usage via litellm's success hook
                # (non-behavioral: prompts/observations/actions untouched).
                import litellm as _litellm

                token_totals = {"in": 0, "out": 0, "seen": False}

                # 去重实现共用 host_guided 那一份(H7-f/H7-g):流式路对同一
                # 请求派两枚带 usage 的终态事件,各写各的回调 = 各自翻倍。
                from repoproof.runner.host_guided import make_usage_cb

                _litellm.success_callback = [make_usage_cb(token_totals)]
                if preflight.action_protocol == "textbased":
                    model_cls = LitellmTextbasedModel
                else:
                    model_cls = LitellmModel
                mkwargs = {"temperature": 0} if preflight.temperature == "0" else {}
                from repoproof.agents.token_budget import TokenBudgetedModel

                model = TokenBudgetedModel(
                    inner=model_cls(model_name=f"openai/{provider.model_name}", model_kwargs=mkwargs),
                    totals=token_totals,
                    max_input_tokens=self.contract.budgets.max_input_tokens_total,
                    max_output_tokens=self.contract.budgets.max_output_tokens_total,
                    on_exhausted=lambda payload: self.store.append_event(
                        "budget.exhausted", actor="harness", payload=payload
                    ),
                )
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
                    "input_tokens": token_totals["in"] if token_totals["seen"] else "UNKNOWN",
                    "output_tokens": token_totals["out"] if token_totals["seen"] else "UNKNOWN",
                    "harness_injected_chars": env.injected_chars,
                    "agent_wall_s": round(time.monotonic() - t_agent, 1),
                }
                _litellm.success_callback = []
                if result.exit_status == "TokenBudgetExhausted" and model.exhausted:
                    ex = model.exhausted
                    budget_exhausted = f"{ex['kind']} ({ex['used']} >= {ex['limit']})"
                ledger_final = None
                if coverage_ledger:
                    from repoproof.harness.coverage_ledger import LEDGER_PATH, summarize

                    read = self.backend.exec(c_agent, ["cat", LEDGER_PATH], timeout_s=15)
                    raw = read.stdout if read.exit_code == 0 else b""
                    if raw:
                        self.store.store_artifact(
                            raw, media_type="application/json", producer="ledger",
                            name_hint="coverage_ledger.final.json",
                        )
                    ledger_final = summarize(raw.decode("utf-8", errors="replace") or None, ledger_requirements)
                    ledger_final.pop("statuses", None)
                    ev("ledger.final", actor="harness", payload=ledger_final)
                agent_metrics["ledger_final"] = ledger_final
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

        token_budget_stats = {
            "input_used": agent_metrics.get("input_tokens"),
            "output_used": agent_metrics.get("output_tokens"),
            "input_limit": self.contract.budgets.max_input_tokens_total,
            "output_limit": self.contract.budgets.max_output_tokens_total,
        }
        pol_vr = policy_result(
            token_budget=token_budget_stats,
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
            "coverage_ledger": coverage_ledger,
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
    reaches the repo, trace or artifacts.

    REPOPROOF_PROVIDER=deepseek-native 切到 P-D 直连通道:改读
    REPOPROOF_DEEPSEEK_BASE / REPOPROOF_DEEPSEEK_KEY,模型取
    REPOPROOF_MODEL(缺省 REPOPROOF_DEEPSEEK_DEFAULT),profile 必须由
    REPOPROOF_DS_PROFILE 显式点名(§55 两候选,无静默默认)。"""
    import os

    if os.environ.get("REPOPROOF_PROVIDER") == "deepseek-native":
        from repoproof.agents.deepseek_native import build_deepseek_provider

        base = os.environ.get("REPOPROOF_DEEPSEEK_BASE")
        key = os.environ.get("REPOPROOF_DEEPSEEK_KEY")
        model = os.environ.get("REPOPROOF_MODEL") or os.environ.get("REPOPROOF_DEEPSEEK_DEFAULT")
        profile = os.environ.get("REPOPROOF_DS_PROFILE")
        pairs = (("REPOPROOF_DEEPSEEK_BASE", base), ("REPOPROOF_DEEPSEEK_KEY", key),
                 ("REPOPROOF_MODEL|REPOPROOF_DEEPSEEK_DEFAULT", model),
                 ("REPOPROOF_DS_PROFILE", profile))
        missing = [n for n, v in pairs if not v]
        if missing:
            raise RuntimeError(f"deepseek provider env vars missing: {missing}")
        return build_deepseek_provider(
            profile=profile, api_base=base, api_key=key, model_name=model
        )

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


def write_crash_report(project_root: Path, task_id: str, mode: str, exc: Exception) -> str | None:
    """运行崩溃时的兜底报告——运行绝不允许"隐身"。

    用户实测:env probe 崩溃后进程直接死掉、不写 report.json,该次
    运行在进度页/回顾下拉/历史里全体消失。这里找到该任务最新且尚无
    report.json 的 runs/ 目录,写入典型化 BLOCKED(CRASHED_INTERNAL)
    报告:系统层中断是可恢复的非结论,与任务级 FAIL 严格区分。"""
    runs = project_root / "runs"
    cands = sorted(
        (p for p in runs.glob(f"{task_id}-2*") if p.is_dir() and not (p / "report.json").exists()),
        key=lambda p: p.name, reverse=True)
    if not cands:
        return None
    err = f"{type(exc).__name__}: {exc}"
    report = {
        "run_id": cands[0].name, "task_id": task_id, "mode": mode,
        "final_verdict": "BLOCKED", "verdict": "BLOCKED",
        "state": "CRASHED_INTERNAL", "error": err[:500],
        "capability": "not_run", "regression": "not_run",
        "policy": "not_run", "replay": "not_run",
        "gate_reasons": [
            f"运行中断:{err[:300]}",
            "这是系统层中断,不是任务结论;根因排除后可重新运行同一任务",
        ],
        "agent": {"exit_status": "Crashed", "model_calls": None},
    }
    (cands[0] / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return str(cands[0])


def run_gate3c(
    contract_path: Path,
    project_root: Path,
    provider: ProviderConfig,
    *,
    budget_visibility: bool = False,
    coverage_ledger: bool = False,
) -> dict:
    """CLI entry: adequacy gate → real preflight → BLOCKED stop or the
    single agent run. The ContractAdequacyGate runs FIRST: an
    inadequate spec yields INVALID_TASK_SPEC with zero model calls
    (not even preflight) and never an agent FAIL."""
    adequacy = run_adequacy_gate(contract_path, project_root)
    if not adequacy["ok"]:
        return {
            "blocked": True,
            "state": "INVALID_TASK_SPEC",
            "adequacy": adequacy,
            "agent_model_call_count": 0,
            "preflight": None,
        }
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
        report = runner.run_agent(
            provider, pf, budget_visibility=budget_visibility, coverage_ledger=coverage_ledger
        )
    finally:
        runner.backend.destroy_all()
    return {"blocked": False, "preflight": pf.summary(), "report": report}
