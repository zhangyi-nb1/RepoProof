"""RepoProof CLI — Gate 2.5 surface.

Commands:
  baseline      run the direct-adoption baseline (scripted, no agent)
  freeze-task   build + commit the TaskPackageManifest (human pre-run step)
  verify-trace  verify a run's append-only trace hash chain
  verify-bundle verify hash/reference integrity of a whole run bundle
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from repoproof.harness.trace import verify_chain

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repoproof")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_base = sub.add_parser("baseline", help="run direct-adoption baseline for a frozen contract")
    p_base.add_argument("--contract", required=True, type=Path)
    p_base.add_argument("--runs-root", type=Path, default=None)

    p_freeze = sub.add_parser("freeze-task", help="freeze the task package manifest (pre-run, human step)")
    p_freeze.add_argument("--contract", required=True, type=Path)
    p_freeze.add_argument("--full", action="store_true", help="bind collection+wheelhouse+image+env (v3)")

    p_adeq = sub.add_parser("adequacy-check", help="ContractAdequacyGate: deterministic pre-agent spec admission")
    p_adeq.add_argument("--contract", required=True, type=Path)

    p_ahost = sub.add_parser(
        "analyze-host",
        help="Guided Adoption Phase 1: static host-project analysis (read-only, no LLM, no Docker)",
    )
    p_ahost.add_argument("--path", required=True, type=Path)
    p_ahost.add_argument("--json", action="store_true", help="stable JSON envelope (RFC-008 §5.1)")

    p_arepo = sub.add_parser(
        "analyze-repo",
        help="Guided Adoption Phase 2: repository analysis "
        "(anonymous shallow clone OR --local-path; never executes repo code)",
    )
    g = p_arepo.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="public GitHub URL (will shallow-clone into upstream-cache/analysis/)")
    g.add_argument("--local-path", type=Path, help="analyze an already-present repo directory (offline)")
    p_arepo.add_argument("--revision", default=None)
    p_arepo.add_argument("--json", action="store_true", help="stable JSON envelope (RFC-008 §5.1)")

    p_asrc = sub.add_parser(
        "analyze-source",
        help="RFC-008 §5.1 stable name for analyze-repo (same core, JSON envelope by default)",
    )
    g2 = p_asrc.add_mutually_exclusive_group(required=True)
    g2.add_argument("--repo", help="public GitHub URL")
    g2.add_argument("--local-path", type=Path, help="analyze an already-present repo directory (offline)")
    p_asrc.add_argument("--revision", default=None)
    p_asrc.add_argument("--json", action="store_true")

    p_adm = sub.add_parser(
        "admission",
        help="RFC-008 §六: deterministic four-state admission from two report JSON files",
    )
    p_adm.add_argument("--host-report", required=True, type=Path)
    p_adm.add_argument("--source-report", required=True, type=Path)
    p_adm.add_argument("--json", action="store_true")

    p_export = sub.add_parser(
        "export-bundle",
        help="RFC-008 §9.1 EXPORT_ONLY: build integration_bundle/ from a finished run "
        "(honest FAIL exports too; never touches the user's project; held-out never included)",
    )
    p_export.add_argument("--run-dir", required=True, type=Path)
    p_export.add_argument("--dest", type=Path, default=None,
                          help="default: <run-dir>/integration_bundle (must be empty/absent)")
    p_export.add_argument("--json", action="store_true")

    p_demo = sub.add_parser("demo", help="no-model evidence demos (Gate 8C): list / verify / replay")
    p_demo.add_argument("demo_cmd", choices=["list", "verify", "replay"])
    p_demo.add_argument("--case", default=None)

    p_task = sub.add_parser("task", help="task scaffolding (Gate 8D): init a DRAFT task / check adequacy pre-flight")
    p_task.add_argument("task_cmd", choices=["init", "check"])
    p_task.add_argument("--task-id", required=True)
    p_task.add_argument("--source-repo-url", default="TODO")
    p_task.add_argument("--source-commit", default="TODO")
    p_task.add_argument("--distribution", default="TODO")
    p_task.add_argument("--target-project", default="")
    p_task.add_argument("--capability-statement", default="TODO")
    p_task.add_argument("--dry-run", action="store_true")

    p_trace = sub.add_parser("verify-trace", help="verify the tamper-evident trace chain of a run")
    p_trace.add_argument("--run-dir", required=True, type=Path)

    p_agent = sub.add_parser("agent-run", help="Gate 3C/4A: provider admission + ONE real agent run")
    p_agent.add_argument("--contract", required=True, type=Path)
    p_agent.add_argument("--budget-visibility", action="store_true", help="Gate 4A ablation variable")
    p_agent.add_argument("--coverage-ledger", action="store_true", help="Gate 4B ablation variable")

    p_guided = sub.add_parser(
        "guided-run",
        help="RFC-008 §11 GUIDED_ADOPTION: bounded multi-round repair (product mode, "
        "public-only feedback, final hidden verification; never enters the benchmark)",
    )
    p_guided.add_argument("--contract", required=True, type=Path)
    p_guided.add_argument("--max-rounds", type=int, default=3)

    p_bundle = sub.add_parser("verify-bundle", help="verify hash/reference integrity of a run bundle")
    p_bundle.add_argument("--run-dir", required=True, type=Path)
    p_bundle.add_argument("--contract", type=Path, default=None)

    p_host = sub.add_parser(
        "host-run",
        help="TESTPLAN-V2 host-integrated guided run (mode L, LocalWorktree backend): "
        "session assembly + per-run venv rebuild + bounded repair + hidden oracle "
        "+ clean replay + benchmarks/v2/runs.jsonl record",
    )
    p_host.add_argument("--contract", required=True, type=Path,
                        help="benchmarks/v2/tasks/<task>/contract.yaml (frozen)")
    p_host.add_argument("--run-order", default="UNKNOWN",
                        help="preregistered execution order index (1, 2, ...)")
    p_host.add_argument("--run-index", default="UNKNOWN",
                        help="per-model run index (1 for pilot)")
    p_host.add_argument("--batch", default="UNKNOWN",
                        help="batch attribution written to runs.jsonl; pass "
                             "EXPLORATORY_UNPREREGISTERED for ad-hoc runs outside a "
                             "preregistration (excluded from stage-gate pass counts)")
    p_host.add_argument("--wheelhouse", type=Path, default=None,
                        help="frozen local wheel index (default: ~/RepoProofBench/wheelhouse-offerclaw-<commit7>)")
    p_host.add_argument("--fake", default=None, metavar="MODE",
                        help="smoke only: scripted fake model (never for official runs). "
                             "noop | positive | control:<name> —— control:<name> 把任务包里的"
                             "任一控制组当脚本跑完整条链路(负控走到 verdict,"
                             "用来验判据在**失败侧**的行为,那是矩阵看不到的一段)")
    p_host.add_argument("--keep-session", action="store_true",
                        help="debug: keep the session tree on disk after the run")
    p_host.add_argument("--allow-retired", action="store_true",
                        help="显式开跑已退出计分池的任务(contract.task_status=RETIRED)。"
                             "退役题每跑必 FAIL 且原因已知(典型:题面欠定),"
                             "只作探针用,发次不计模型表现;不带本旗标一律拒开")
    p_host.add_argument("--backend", default="mini-swe",
                        choices=["mini-swe", "dsh"],
                        help="agent backend(DSH 阶段 8):mini-swe = 仓内环(缺省,"
                             "既有全部发次);dsh = 封存 DSH minimal runtime 作不可信"
                             "AgentBackend(B-dsh 代际,只接 deepseek-native provider,"
                             "发次不计模型能力池)")

    args = parser.parse_args(argv)

    if args.cmd == "baseline":
        from repoproof.runner.baseline import run_baseline

        report = run_baseline(args.contract, PROJECT_ROOT, args.runs_root)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        # Exit 0 = the evidence chain completed; the verdict itself is
        # data (FAIL is a legitimate, honest outcome of a baseline).
        return 0

    if args.cmd == "freeze-task":
        from repoproof.domain.models import TaskContract
        from repoproof.execution.docker_backend import DockerExecutionBackend
        from repoproof.harness import task_package
        from repoproof.harness.wheelhouse import compute_manifest
        from repoproof.runner.baseline import IMAGE, ensure_upstream

        contract, _ = TaskContract.load_frozen(args.contract, require_sidecar=True)
        upstream, _mf = ensure_upstream(PROJECT_ROOT / "upstream-cache", contract.source_repo)
        collection = wheelhouse_manifest = image_digest = env_constraints = None
        if args.full:
            collection = task_package.collect_test_nodes(PROJECT_ROOT, contract)
            wh = PROJECT_ROOT / "upstream-cache" / f"wheelhouse-{contract.source_repo.resolved_commit[:12]}"
            wheelhouse_manifest = compute_manifest(wh)
            backend = DockerExecutionBackend(image=IMAGE)
            backend.pull()
            image_digest = backend.image_digest()
            from repoproof.harness.wheelhouse import select_wheel

            dist = contract.source_repo.distribution
            wheel_name, _sha = select_wheel(wheelhouse_manifest["wheels"], dist)
            version = wheel_name.split("-")[1]
            env_constraints = {
                "machine": "aarch64" if contract.environment.arch == "arm64" else contract.environment.arch,
                "python": contract.environment.python,
                contract.source_repo.import_name: version,
            }
        spec_kw: dict = {}
        if args.full and contract.requirement_spec_file:
            from repoproof.domain.models import sha256_file
            from repoproof.harness.controls_battery import run_controls_battery
            from repoproof.harness.prompt_manifest import build_prompt_manifest, write_prompt_manifest
            from repoproof.harness.task_package import _tree_sha
            from repoproof.runner.agent_run import render_task_prompt

            _c2, contract_sha = TaskContract.load_frozen(args.contract, require_sidecar=True)
            prompt, spec, spec_sha = render_task_prompt(
                contract, environment_constraints=env_constraints, project_root=PROJECT_ROOT
            )
            consumer_dir = PROJECT_ROOT / contract.target_project.path
            examples_path = consumer_dir / "public_examples" / "truth_table.json"
            public_tests_sha = _tree_sha(consumer_dir / "public_tests")
            pm = build_prompt_manifest(
                task_id=contract.task_id,
                public_contract_sha=contract_sha,
                requirement_spec_sha=spec_sha,
                public_examples_path=examples_path if examples_path.exists() else None,
                public_tests_tree_sha=public_tests_sha,
                rendered_prompt=prompt,
                spec=spec,
            )
            pm_path = args.contract.parent / (args.contract.stem + ".prompt_manifest.json")
            pm_sha = write_prompt_manifest(pm_path, pm)
            controls = run_controls_battery(
                PROJECT_ROOT, contract, spec,
                upstream=upstream,
                wheelhouse=PROJECT_ROOT / "upstream-cache" / f"wheelhouse-{contract.source_repo.resolved_commit[:12]}",
            )
            spec_kw = {
                "requirement_spec_sha256": sha256_file(args.contract.parent / contract.requirement_spec_file),
                "prompt_manifest_sha256": pm_sha,
                "public_tests_tree_sha256": public_tests_sha,
                "public_examples_sha256": sha256_file(examples_path) if examples_path.exists() else None,
                "responsibility_matrix": spec.responsibility_matrix(),
                "controls_summary": controls,
            }
        manifest = task_package.freeze(
            PROJECT_ROOT,
            args.contract,
            upstream_dir=upstream,
            collection=collection,
            wheelhouse_manifest=wheelhouse_manifest,
            image_digest=image_digest,
            environment_constraints=env_constraints,
            **spec_kw,
        )
        print(json.dumps(manifest.model_dump(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.cmd == "adequacy-check":
        from repoproof.runner.agent_run import run_adequacy_gate

        result = run_adequacy_gate(args.contract, PROJECT_ROOT)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["ok"] else 4

    if args.cmd == "analyze-host":
        from repoproof.adoption.analysis.host_analyzer import analyze_host_project

        report = analyze_host_project(args.path)
        payload = report.to_dict()
        if args.json:
            payload = {"schema_version": 1, "kind": "host_project_report", "report": payload}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.cmd in ("analyze-repo", "analyze-source"):
        from repoproof.adoption.analysis.repository_analyzer import (
            analyze_repository,
            analyze_repository_dir,
        )

        url = getattr(args, "url", None) or getattr(args, "repo", None)
        if args.local_path:
            rep = analyze_repository_dir(args.local_path, requested_revision=args.revision)
        else:
            rep = analyze_repository(url, args.revision,
                                     cache_root=PROJECT_ROOT / "upstream-cache")
        payload = rep.to_dict()
        if args.json:
            payload = {"schema_version": 1, "kind": "repository_report", "report": payload}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "export-bundle":
        from repoproof.adoption.delivery.integration_bundle import BundleError, export_bundle

        try:
            out = export_bundle(PROJECT_ROOT, args.run_dir, args.dest)
        except (BundleError, OSError) as exc:
            payload = {"ok": False, "error": str(exc)}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 3
        if args.json:
            out = {"schema_version": 1, "kind": "integration_bundle", **out}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "admission":
        from repoproof.adoption.admission.admission_report import decide
        from repoproof.adoption.analysis.host_analyzer import HostProjectReport
        from repoproof.adoption.analysis.repository_analyzer import RepositoryReport

        def _load_report(path: Path, key: str) -> dict:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("report", data) if isinstance(data, dict) else data

        host = HostProjectReport.model_validate(_load_report(args.host_report, "report"))
        repo = RepositoryReport.model_validate(_load_report(args.source_report, "report"))
        result = decide(host, repo)
        payload = result.to_dict()
        if args.json:
            payload = {"schema_version": 1, "kind": "admission_report", "report": payload}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "demo":
        from repoproof.runner.demo import CASES, demo_list, demo_replay, demo_verify

        if args.demo_cmd == "list":
            out = demo_list()
        else:
            if args.case not in CASES:
                print(json.dumps({"error": f"unknown case {args.case!r}", "known": sorted(CASES)}))
                return 2
            fn = demo_verify if args.demo_cmd == "verify" else demo_replay
            out = fn(PROJECT_ROOT, args.case)
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=False))
        if args.demo_cmd == "verify":
            return 0 if out.get("verdict_recomputation_matches") else 1
        if args.demo_cmd == "replay":
            return 0 if out.get("replay_ok") else 1
        return 0

    if args.cmd == "task":
        from repoproof.runner.scaffold import task_check, task_init

        if args.task_cmd == "init":
            out = task_init(
                PROJECT_ROOT,
                task_id=args.task_id,
                source_repo_url=args.source_repo_url,
                source_commit=args.source_commit,
                distribution=args.distribution,
                target_project=args.target_project,
                capability_statement=args.capability_statement,
                dry_run=args.dry_run,
            )
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out.get("ok") else 2
        out = task_check(PROJECT_ROOT, args.task_id)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ready") else 4

    if args.cmd == "agent-run":
        from repoproof.runner.agent_run import provider_from_env, run_gate3c, write_crash_report

        try:
            out = run_gate3c(
                args.contract,
                PROJECT_ROOT,
                provider_from_env(),
                budget_visibility=args.budget_visibility,
                coverage_ledger=args.coverage_ledger,
            )
        except Exception as exc:
            write_crash_report(PROJECT_ROOT, args.contract.stem, "real-agent-baseline", exc)
            raise
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0 if not out.get("blocked") else 3

    if args.cmd == "guided-run":
        from repoproof.runner.agent_run import write_crash_report
        from repoproof.runner.guided_repair import run_guided_cli

        try:
            out = run_guided_cli(args.contract, PROJECT_ROOT, max_rounds=args.max_rounds)
        except Exception as exc:
            write_crash_report(PROJECT_ROOT, args.contract.stem, "guided-repair", exc)
            raise
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0 if not out.get("blocked") else 3

    if args.cmd == "host-run":
        from repoproof.runner.agent_run import write_crash_report
        from repoproof.runner.host_guided import run_host_guided_cli

        try:
            out = run_host_guided_cli(
                args.contract,
                PROJECT_ROOT,
                fake=args.fake,
                run_order=args.run_order,
                run_index=args.run_index,
                batch=args.batch,
                wheelhouse=args.wheelhouse,
                keep_session=args.keep_session,
                backend=args.backend,
                allow_retired=args.allow_retired,
            )
        except Exception as exc:
            try:
                import yaml as _yaml

                task_stem = _yaml.safe_load(args.contract.read_text(encoding="utf-8"))["task_id"]
            except Exception:  # noqa: BLE001 — 兜底报告不允许二次崩溃
                task_stem = args.contract.parent.name
            write_crash_report(PROJECT_ROOT, task_stem, "host-guided-repair", exc)
            raise
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True, default=str))
        return 0 if not out.get("blocked") else 3

    if args.cmd == "verify-trace":
        ok, n, err = verify_chain(args.run_dir / "trace.jsonl")
        print(json.dumps({"ok": ok, "events": n, "error": err}))
        return 0 if ok else 1

    if args.cmd == "verify-bundle":
        from repoproof.verification.bundle_check import verify_bundle

        result = verify_bundle(args.run_dir, PROJECT_ROOT, args.contract)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
