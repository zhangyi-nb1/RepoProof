"""GUIDED_ADOPTION 有界多轮修复(RFC-008 §11,Gate D)。

与 Benchmark 模式(agent-run,单次不变)分离的产品模式:
≤3 轮,每轮 = 同一 DefaultAgent 类的一次顺序调用(仍是全系统唯一
自主循环;RepairLoop 只是确定性编排,不是第二个 Agent)。

每轮反馈只允许公开来源(RFC-008 §一-6/7):公开合同测试结果 →
FailurePacket(类型化摘要,禁原始日志)。held-out 测试名、hidden
fixture、oracle 参考输出、gate 答案永不进入任何 Agent 可见文本。

循环结束(全绿/停滞/预算尽/上限)后:恢复最佳快照 → Freeze
Adaptation → 最终隐藏验证 → clean replay → Completion Gate——循环
自己永不宣布成功。
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from repoproof.adoption.repair.failure_packet import FailurePacket, build_failure_packets
from repoproof.adoption.repair.repair_budget import RepairBudget
from repoproof.adoption.repair.repair_loop import (
    RepairLoop,
    RoundResult,
    full_score,
)
from repoproof.agents.provider_gate import PreflightResult, ProviderConfig
from repoproof.domain.models import VerificationResult, sha256_bytes
from repoproof.harness.adaptation import PatchBudgetExceeded, freeze_adaptation, verify_frozen
from repoproof.harness.budget import BudgetMeter
from repoproof.harness.trace import verify_chain
from repoproof.runner.agent_run import AgentRunner, render_task_prompt
from repoproof.runner.baseline import (
    IMAGE,
    Mount,
    _skip_symlink_tree,
    ensure_upstream,
    hash_tree,
    make_read_only,
)
from repoproof.verification import completion_gate
from repoproof.verification.junit import parse_junit_xml
from repoproof.verification.verifiers import (
    REPLAY_MODE_BASELINE,
    REPLAY_MODE_CLEAN,
    policy_result,
    replay_result,
)

SCOPE_MARKER = "SCOPE_CHANGE_REQUEST:"

_ROUND_HEADER = (
    "\n\n==== GUIDED REPAIR ROUND {idx}/{max_rounds} ====\n"
    "This is a bounded repair round. The adaptation zone currently holds the\n"
    "best state so far. Address the failure packets below (they summarise the\n"
    "PUBLIC contract tests only). If — and only if — the task cannot proceed\n"
    "without a scope change (new large dependency, network access, changing\n"
    "success criteria, touching protected paths), print one line starting\n"
    "with `{marker}` followed by the reason, then submit; the system will\n"
    "pause for the human decision. Never invent test results.\n"
)


class RepairRoundRecord(BaseModel):
    """RFC-008 §11.2 — 每轮落盘账本(runs/<id>/repair/round-N/record.json)。"""

    round_index: int
    base_snapshot_hash: str = ""
    adaptation_root: str = ""
    changed_files: list[str] = []
    diff_lines: int = 0
    public_passed: int = 0
    public_failed: int = 0
    regression_passed: int | None = None   # v1:seam consumer 只读,回归在最终隐藏验证
    regression_failed: int | None = None
    policy_violations: int = 0
    model_calls: int = 0
    commands: int = 0
    tokens_in: int | str = "UNKNOWN"
    tokens_out: int | str = "UNKNOWN"
    wall_time_s: float = 0.0
    failure_packets: list[dict] = []
    scope_change_request: str | None = None
    score: list[float] = []
    selected_as_best: bool = False

    def to_dict(self) -> dict:
        return self.model_dump()


def render_packets(packets: list[FailurePacket]) -> str:
    """FailurePacket → 轮次提示文本。只含类型化摘要(§11.6:无原始
    pytest 日志;packet 本身已由 build_failure_packets 清洗)。"""
    if not packets:
        return "\nFAILURE PACKETS: none yet — run the public tests yourself first.\n"
    out = ["\nFAILURE PACKETS (public contract tests only):"]
    for i, p in enumerate(packets, 1):
        out.append(
            f"{i}. [{p.type}] {p.summary}\n"
            f"   expected: {p.expected}\n"
            f"   actual:   {p.actual}\n"
            f"   suggestion: {p.suggestion}"
        )
    return "\n".join(out) + "\n"


def _snapshot_dir_hash(d: Path) -> str:
    lines = []
    for p in sorted(d.rglob("*")):
        if p.is_file():
            lines.append(f"{p.relative_to(d)}\0{sha256_bytes(p.read_bytes())}")
    return sha256_bytes("\n".join(lines).encode())


def snapshot_adaptation(adaptation: Path, dest: Path) -> str:
    """快照适配区 → dest;返回内容哈希。"""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(adaptation, dest)
    return _snapshot_dir_hash(dest)


def restore_adaptation(adaptation: Path, snapshot: Path) -> None:
    """真实恢复:清空适配区,拷回快照(F3:不能只记录「已回滚」)。"""
    for p in adaptation.iterdir():
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
    if snapshot.exists():
        for p in snapshot.iterdir():
            if p.is_dir():
                shutil.copytree(p, adaptation / p.name)
            else:
                shutil.copy2(p, adaptation / p.name)


def extract_scope_change(submission: str) -> str | None:
    for line in (submission or "").splitlines():
        if line.strip().startswith(SCOPE_MARKER):
            return line.strip()[len(SCOPE_MARKER):].strip()[:300]
    return None


class GuidedRepairRunner(AgentRunner):
    """产品模式 runner。复用 AgentRunner 的全部基础设施(安装、容器、
    one_pass 隐藏验证、策略、重放、gate);只有 agent 阶段变为
    RepairLoop 驱动的 ≤max_rounds 轮。与 benchmark 路径互不影响。"""

    def run_guided(
        self,
        provider: ProviderConfig,
        preflight: PreflightResult,
        *,
        max_rounds: int = 3,
        model_factory: Callable[[dict], object] | None = None,
    ) -> dict:
        import os as _os

        ev = self.store.append_event
        t0 = time.monotonic()
        ev("run.start", actor="runner", payload={
            "run_id": self.run_id, "mode": "guided-repair",
            "max_rounds": max_rounds, "agent": "mini-swe-agent-2.4.6",
            "task_package_root_hash": self.package.root_hash,
            "provider_config_sha256": preflight.provider_config_sha256,
        })
        ev("contract.frozen", actor="harness",
           payload={"task_id": self.contract.task_id, "sha256": self.contract_sha})
        ev("task_package.verified", actor="harness", payload={"root_hash": self.package.root_hash})
        ev("provider.admitted", actor="harness", payload=preflight.summary())

        missing_external: list[str] = []
        budget_exhausted: str | None = None
        adaptation_manifest = None
        agent_metrics: dict = {"model_calls": 0, "commands": 0, "denied": 0,
                               "exit_status": None, "cost": "UNKNOWN"}
        setup_meter = BudgetMeter(self.contract.budgets)

        ok, server = self.backend.available()
        if not ok:
            missing_external.append(f"docker unavailable: {server}")
        first = replay = rep = None
        replay_mode = None
        oracle_before: dict = {}
        upstream_before: dict = {}
        upstream = oracle_snap = adaptation = wheelhouse = None
        prompt_sha = None
        repair_summary: dict = {}

        if not missing_external:
            self.backend.pull()
            digest = self.backend.image_digest()
            if digest:
                self.image_ref = digest
            upstream, repo_manifest = ensure_upstream(
                self.project_root / "upstream-cache", self.contract.source_repo)
            if repo_manifest.git_tree_hash != self.package.source_git_tree_hash:
                missing_external.append("upstream git tree hash != task package binding")
        if not missing_external:
            ev("upstream.pinned", actor="harness", payload=repo_manifest.model_dump())
            wheelhouse, wh_manifest = self.ensure_wheelhouse(upstream, setup_meter)
            ev("wheelhouse.frozen", actor="harness", payload={"root": wh_manifest["root"]})

            oracle_snap = self.store.run_dir / "oracle_snapshot"
            shutil.copytree(self.oracle_src, oracle_snap)
            make_read_only(oracle_snap)
            adaptation = self.store.run_dir / "adaptation"
            adaptation.mkdir(exist_ok=True)
            oracle_before = hash_tree(oracle_snap)
            upstream_before = _skip_symlink_tree(upstream)
            ev("oracle.hashed", actor="harness", payload={"files": len(oracle_before)})

            agent_meter = BudgetMeter(self.contract.budgets)
            venv_dir = self._install_phase("agent", wheelhouse, agent_meter)
            # 命令预算按轮数放大(合同 token 预算仍是全局硬墙)
            command_budget = self.contract.budgets.max_agent_steps * 2 * max_rounds
            cmd_timeout = self.contract.budgets.max_command_minutes * 60
            c_agent = self.backend.start(
                name_prefix="rp-guided",
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
                ev("container.security", actor="harness", payload={"label": "guided", **security})
                assert str(security.get("network_mode")) == "none"

                base_prompt, _spec, _spec_sha = render_task_prompt(
                    self.contract,
                    environment_constraints=self.package.environment_constraints,
                    project_root=self.project_root,
                )
                prompt_sha = sha256_bytes(base_prompt.encode())
                ev("agent.prompt", actor="harness",
                   payload={"sha256": prompt_sha, "chars": len(base_prompt)})

                from repoproof.agents.repoproof_env import RepoProofEnvironment

                env = RepoProofEnvironment(
                    backend=self.backend,
                    container=c_agent,
                    store=self.store,
                    command_timeout_s=cmd_timeout,
                    command_budget=command_budget,
                    budget_visibility=False,
                    model_call_limit=self.contract.budgets.max_agent_steps,
                    wall_limit_s=self.contract.budgets.max_wall_time_minutes * 60,
                    adaptation_dir=adaptation,
                    patch_files_limit=self.contract.budgets.max_patch_files,
                    patch_lines_limit=self.contract.budgets.max_patch_lines,
                    ledger_enabled=False,
                    ledger_requirements=[],
                )

                token_totals = {"in": 0, "out": 0, "seen": False}
                if model_factory is None:
                    _os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")
                    _os.environ["OPENAI_API_KEY"] = provider.api_key
                    _os.environ["OPENAI_API_BASE"] = provider.api_base
                    _os.environ["OPENAI_BASE_URL"] = provider.api_base
                    import litellm as _litellm
                    from minisweagent.models.litellm_model import LitellmModel
                    from minisweagent.models.litellm_textbased_model import (
                        LitellmTextbasedModel,
                    )

                    from repoproof.agents.token_budget import TokenBudgetedModel

                    def _usage_cb(kwargs, completion_response, start_time, end_time):  # noqa: ANN001
                        usage = getattr(completion_response, "usage", None)
                        if usage:
                            token_totals["seen"] = True
                            token_totals["in"] += getattr(usage, "prompt_tokens", 0) or 0
                            token_totals["out"] += getattr(usage, "completion_tokens", 0) or 0

                    _litellm.success_callback = [_usage_cb]
                    model_cls = (LitellmTextbasedModel
                                 if preflight.action_protocol == "textbased" else LitellmModel)
                    mkwargs = {"temperature": 0} if preflight.temperature == "0" else {}
                    model = TokenBudgetedModel(
                        inner=model_cls(model_name=f"openai/{provider.model_name}",
                                        model_kwargs=mkwargs),
                        totals=token_totals,
                        max_input_tokens=self.contract.budgets.max_input_tokens_total,
                        max_output_tokens=self.contract.budgets.max_output_tokens_total,
                        on_exhausted=lambda payload: self.store.append_event(
                            "budget.exhausted", actor="harness", payload=payload),
                    )
                else:
                    model = model_factory(token_totals)

                repair_dir = self.store.run_dir / "repair"
                repair_dir.mkdir(exist_ok=True)
                records: list[RepairRoundRecord] = []
                metrics_acc = {"model_calls": 0, "commands": 0, "denied": 0}
                last_exit: dict = {"status": None}

                def _run_public_tests() -> dict:
                    res = self.backend.exec(
                        c_agent,
                        ["/venv/env/bin/python", "-m", "pytest", "-q",
                         "/consumer/public_tests", "--junitxml=/tmp/rp_round.xml"],
                        timeout_s=cmd_timeout,
                    )
                    xml = self.backend.exec(c_agent, ["cat", "/tmp/rp_round.xml"], timeout_s=30)
                    junit = parse_junit_xml(xml.stdout if xml.exit_code == 0 else None)
                    junit["pytest_exit"] = res.exit_code
                    return junit

                def run_round(idx: int, packets: list[FailurePacket],
                              best_snapshot: str | None) -> RoundResult:
                    t_round = time.monotonic()
                    ev("repair.round.start", actor="harness",
                       payload={"round": idx, "packets": len(packets)})
                    # F3:上一轮劣化已回滚 → 从最佳快照真实恢复后再开工
                    if best_snapshot:
                        snap_path = Path(best_snapshot)
                        if snap_path.exists() and _snapshot_dir_hash(snap_path) != (
                                _snapshot_dir_hash(adaptation) if any(adaptation.iterdir()) else ""):
                            restore_adaptation(adaptation, snap_path)
                            ev("repair.restored_best", actor="harness",
                               payload={"round": idx, "snapshot": snap_path.name})
                    base_hash = (_snapshot_dir_hash(adaptation)
                                 if any(adaptation.iterdir()) else "")

                    from repoproof.agents.backend import MiniSWEBackend

                    round_prompt = (
                        base_prompt
                        + _ROUND_HEADER.format(idx=idx, max_rounds=max_rounds,
                                               marker=SCOPE_MARKER)
                        + render_packets(packets)
                    )
                    backend = MiniSWEBackend(
                        model=model, env=env,
                        step_limit=self.contract.budgets.max_agent_steps,
                        cost_limit=self.contract.budgets.monetary_soft_cap_usd,
                        output_path=self.store.run_dir / f"trajectory_round{idx}.json",
                    )
                    result = backend.run_task(round_prompt)
                    last_exit["status"] = result.exit_status
                    metrics_acc["model_calls"] += result.n_model_calls
                    metrics_acc["commands"] += result.commands_used
                    metrics_acc["denied"] += result.denied_count

                    round_dir = repair_dir / f"round-{idx}"
                    round_dir.mkdir(exist_ok=True)
                    snap = round_dir / "adaptation"
                    snap_hash = snapshot_adaptation(adaptation, snap)

                    junit = _run_public_tests()
                    nodes = junit.get("nodes", [])
                    collected_ok = bool(junit.get("junit_present")) and not junit.get("junit_parse_error")
                    failed_nodes = [n["node_id"] for n in nodes if n["outcome"] != "passed"]
                    details = {n["node_id"]: n.get("message", "") for n in nodes
                               if n["outcome"] != "passed"}
                    passed = sum(1 for n in nodes if n["outcome"] == "passed")
                    scope_req = extract_scope_change(result.submission)
                    diff_lines = sum(
                        len(p.read_text(encoding="utf-8", errors="replace").splitlines())
                        for p in snap.rglob("*") if p.is_file())

                    rr = RoundResult(
                        adapter_snapshot=str(snap),
                        passed=passed,
                        failed_nodes=failed_nodes,
                        failure_details=details,
                        diff_lines=diff_lines,
                        tokens_used=token_totals["in"] + token_totals["out"],
                        commands_used=result.commands_used,
                        scope_change_request=scope_req,
                        collected_ok=collected_ok,
                        policy_violations=result.denied_count,
                        regression_failed=0,   # v1:consumer 只读,回归风险为零,最终隐藏验证兜底
                        within_budget=result.exit_status not in
                        ("TokenBudgetExhausted", "LimitsExceeded"),
                    )
                    packets_next = build_failure_packets(failed_nodes, details)
                    record = RepairRoundRecord(
                        round_index=idx,
                        base_snapshot_hash=base_hash,
                        adaptation_root=snap_hash,
                        changed_files=sorted(str(p.relative_to(snap))
                                             for p in snap.rglob("*") if p.is_file()),
                        diff_lines=diff_lines,
                        public_passed=passed,
                        public_failed=len(failed_nodes),
                        policy_violations=result.denied_count,
                        model_calls=result.n_model_calls,
                        commands=result.commands_used,
                        tokens_in=token_totals["in"] if token_totals["seen"] else "UNKNOWN",
                        tokens_out=token_totals["out"] if token_totals["seen"] else "UNKNOWN",
                        wall_time_s=round(time.monotonic() - t_round, 1),
                        failure_packets=[p.to_dict() for p in packets_next],
                        scope_change_request=scope_req,
                        score=full_score(rr),
                    )
                    records.append(record)
                    (round_dir / "record.json").write_text(
                        json.dumps(record.to_dict(), ensure_ascii=False, indent=2,
                                   sort_keys=True), encoding="utf-8")
                    ev("repair.round.end", actor="harness", payload={
                        "round": idx, "public_passed": passed,
                        "public_failed": len(failed_nodes),
                        "collected_ok": collected_ok,
                        "exit_status": result.exit_status,
                        "scope_change": bool(scope_req),
                    })
                    return rr

                loop = RepairLoop(
                    run_round,
                    budget=RepairBudget(max_rounds=max_rounds),
                    score_fn=full_score,
                )
                outcome = loop.run()
                # 终态:恢复最佳快照(循环可能停在劣化轮)
                best_snap = Path(outcome.final_adapter)
                if best_snap.exists():
                    restore_adaptation(adaptation, best_snap)
                for r in records:
                    r.selected_as_best = (r.round_index == outcome.best_round)
                    (repair_dir / f"round-{r.round_index}" / "record.json").write_text(
                        json.dumps(r.to_dict(), ensure_ascii=False, indent=2,
                                   sort_keys=True), encoding="utf-8")
                repair_summary = {
                    "rounds_run": outcome.rounds_run,
                    "best_round": outcome.best_round,
                    "best_public_passed": outcome.best_passed,
                    "stop_reason": outcome.stop_reason,
                    "rolled_back_rounds": outcome.rolled_back_rounds,
                    "pending_scope_change": outcome.pending_scope_change,
                }
                (repair_dir / "summary.json").write_text(
                    json.dumps(repair_summary, ensure_ascii=False, indent=2,
                               sort_keys=True), encoding="utf-8")
                ev("repair.summary", actor="harness", payload=repair_summary)

                agent_metrics = {
                    **metrics_acc,
                    "exit_status": last_exit["status"],
                    "cost": "UNKNOWN",
                    "input_tokens": token_totals["in"] if token_totals["seen"] else "UNKNOWN",
                    "output_tokens": token_totals["out"] if token_totals["seen"] else "UNKNOWN",
                    "agent_wall_s": round(time.monotonic() - t_agent, 1),
                    "repair": repair_summary,
                }
                if model_factory is None:
                    import litellm as _litellm
                    _litellm.success_callback = []
                if getattr(model, "exhausted", None):
                    ex = model.exhausted
                    budget_exhausted = f"{ex['kind']} ({ex['used']} >= {ex['limit']})"
                ev("agent.end", actor="harness", payload=agent_metrics)
            finally:
                self.backend.destroy(c_agent)
            self.timings["agent_model_call_s"] = round(time.monotonic() - t_agent, 1)

            # ---- Scope change 待人:停点,不进入最终验证 ----
            if repair_summary.get("pending_scope_change"):
                ev("run.paused", actor="harness", payload={
                    "state": "SCOPE_CHANGE_PENDING_USER",
                    "request": repair_summary["pending_scope_change"]})
                report = {
                    "run_id": self.run_id, "task_id": self.contract.task_id,
                    "mode": "guided-repair",
                    "state": "SCOPE_CHANGE_PENDING_USER",
                    "final_verdict": "BLOCKED",
                    "scope_change_request": repair_summary["pending_scope_change"],
                    "repair": repair_summary,
                    "agent": agent_metrics,
                    "gate_reasons": [
                        "AI 请求超出冻结计划的范围变更,已暂停等待你的决定",
                        f"请求内容:{repair_summary['pending_scope_change']}",
                        "同意 → 生成新计划版本并重新冻结后重跑;拒绝 → 任务按 BLOCKED 结束",
                    ],
                }
                self.store.save_json("report.json", report)
                return report

            try:
                adaptation_manifest = freeze_adaptation(adaptation, self.contract.budgets)
                self.store.save_json("adaptation_manifest.json", adaptation_manifest.model_dump())
                ev("adaptation.frozen", actor="harness", payload={
                    "files": adaptation_manifest.total_files,
                    "lines": adaptation_manifest.total_lines,
                    "root": adaptation_manifest.tree_root_sha256,
                })
            except PatchBudgetExceeded as exc:
                budget_exhausted = str(exc)

        self.timings["system_setup_s"] = round(
            time.monotonic() - t0 - self.timings["agent_model_call_s"], 1)

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
            token_budget={
                "input_used": agent_metrics.get("input_tokens"),
                "output_used": agent_metrics.get("output_tokens"),
                "input_limit": self.contract.budgets.max_input_tokens_total,
                "output_limit": self.contract.budgets.max_output_tokens_total,
            },
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
                rep = replay_result(first=first.summary(), replay=replay.summary(),
                                    mode=replay_mode, evidence=[first.probe_normalized_sha])
                rep.extra["replay_model_calls"] = 0
                rep.extra["replay_agent_commands"] = 0
            except Exception as exc:  # noqa: BLE001
                rep = VerificationResult(
                    verifier="ReplayVerifier", passed=False,
                    detail=f"replay infrastructure failure: {exc}",
                    extra={"mode": replay_mode})

        vr_hashes: dict[str, str] = {}
        for r in (cap_vr, reg_vr, pol_vr) + ((rep,) if rep else ()):
            path = self.store.save_verification(r)
            ref = self.store.store_artifact(
                path.read_bytes(), media_type="application/json",
                producer="verification", name_hint=path.name)
            vr_hashes[r.verifier] = ref.sha256
            ev("verification.result", actor=r.verifier,
               payload={"passed": r.passed, "detail": r.detail, "result_sha256": ref.sha256},
               artifact_refs=[ref.sha256])

        gate = completion_gate.decide(
            capability=cap_vr, regression=reg_vr, policy=pol_vr, replay=rep,
            adaptation=adaptation_manifest, missing_external=missing_external,
            budget_exhausted=budget_exhausted,
        )
        ev("gate.verdict", actor="completion-gate",
           payload={**gate.model_dump(mode="json"), "verification_input_hashes": vr_hashes})
        self.timings["total_wall_s"] = round(time.monotonic() - t0, 1)
        ev("run.end", actor="runner",
           payload={"verdict": gate.verdict.value, "timings": self.timings})

        chain_ok, n_events, chain_err = verify_chain(self.store.trace_path)
        from repoproof.domain.models import sha256_file

        run_manifest = {
            "run_id": self.run_id,
            "task_id": self.contract.task_id,
            "mode": "guided-repair",
            "max_rounds": max_rounds,
            "task_package_root_hash": self.package.root_hash,
            "contract_sha256": self.contract_sha,
            "provider_config_sha256": preflight.provider_config_sha256,
            "preflight": preflight.summary(),
            "agent": agent_metrics,
            "prompt_sha256": prompt_sha,
            "repair": repair_summary,
            "image_digest": self.image_ref if self.image_ref != IMAGE else None,
            "adaptation_root": (adaptation_manifest.tree_root_sha256
                                if adaptation_manifest else None),
            "verification_result_hashes": vr_hashes,
            "missing_external": missing_external,
            "budget_exhausted": budget_exhausted,
            "final_trace_sha256": sha256_file(self.store.trace_path),
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


def run_guided_cli(contract_path: Path, project_root: Path, *, max_rounds: int = 3) -> dict:
    """CLI 入口:准入 → 预检 → GUIDED_ADOPTION 多轮运行。"""
    from repoproof.runner.agent_run import provider_from_env, run_adequacy_gate

    adequacy = run_adequacy_gate(contract_path, project_root)
    if not adequacy["ok"]:
        return {"blocked": True, "state": "INVALID_TASK_SPEC", "adequacy": adequacy,
                "agent_model_call_count": 0, "preflight": None}
    from repoproof.agents.provider_gate import run_preflight

    provider = provider_from_env()
    pf = run_preflight(provider)
    evidence_dir = project_root / "docs" / "evidence" / "gate3-preflight"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "latest_preflight.json").write_text(
        json.dumps(pf.summary(), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    if not pf.ready:
        return {"blocked": True, "preflight": pf.summary(), "agent_model_call_count": 0}
    runner = GuidedRepairRunner(contract_path, project_root, None)
    try:
        report = runner.run_guided(provider, pf, max_rounds=max_rounds)
    finally:
        runner.backend.destroy_all()
    return {"blocked": False, "preflight": pf.summary(), "report": report}
