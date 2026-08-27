"""RepoProof CLI — Product Mode and Benchmark Lab entry points.

The ``tool`` command group is the CLI-first GitHub capability → verified local
tool journey. Historical adaptation, guided-run, host-run, evidence, and demo
commands remain available for the Benchmark Lab and reproducible case studies.
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

    p_tin = sub.add_parser(
        "tool-intake",
        help="LOCAL-TOOL intake (M2/RFC-010 [G1]): repo + capability goal → "
             "admission(4-state) + deterministic ToolContract DRAFT + gap list; "
             "zero LLM, never executes repo code",
    )
    gt = p_tin.add_mutually_exclusive_group(required=True)
    gt.add_argument("--repo", help="public GitHub URL (shallow-clone into upstream-cache/analysis/)")
    gt.add_argument("--local-path", type=Path, help="already-present repo directory (offline)")
    p_tin.add_argument("--capability", required=True, help="one-line capability goal")
    p_tin.add_argument("--revision", default=None)
    p_tin.add_argument("--draft-out", type=Path, default=None,
                       help="write an editable draft bundle (draft.yaml/GAPS.md/"
                            "examples/…) to this directory")

    p_tdf = sub.add_parser(
        "tool-draft",
        help="LOCAL-TOOL drafter (M2-d/[G1] LLM-in-draft-layer-only): fill "
             "owner=LLM gaps in a draft bundle; output stays DRAFT and must "
             "pass tool-confirm + human review before freezing",
    )
    p_tdf.add_argument("--draft-dir", type=Path, required=True)
    gd = p_tdf.add_mutually_exclusive_group(required=True)
    gd.add_argument("--repo", help="public GitHub URL (re-runs intake for context)")
    gd.add_argument("--local-path", type=Path)
    p_tdf.add_argument("--capability", required=True)
    p_tdf.add_argument("--revision", default=None)
    p_tdf.add_argument("--fake", action="store_true",
                       help="deterministic template drafter (zero API)")

    p_tcf = sub.add_parser(
        "tool-confirm",
        help="LOCAL-TOOL confirm (M2/RFC-010 [G1] human gate): completed draft "
             "bundle → D-checks → assemble → adequacy T-gate → frozen contract",
    )
    p_tcf.add_argument("--draft-dir", type=Path, required=True)

    p_tool = sub.add_parser(
        "tool",
        help="LOCAL-TOOL 单命令旅程(M3/RFC-010):add(intake+起草+人务清单)"
             " / build(confirm→物化→彩排门→真发→export+注册) / list / audit / withdraw / mcp",
    )
    tsub = p_tool.add_subparsers(dest="tool_cmd", required=True)
    pt_add = tsub.add_parser("add", help="URL+一句话 → draft 束+起草+人的待办清单")
    pt_add.add_argument("--repo", required=True)
    pt_add.add_argument("--capability", required=True)
    pt_add.add_argument("--revision", default=None)
    pt_add.add_argument("--draft-out", type=Path, required=True)
    pt_add.add_argument("--fake-drafter", action="store_true",
                        help="确定性模板起草(零 API)")
    pt_build = tsub.add_parser(
        "build", help="人补完 draft 束后:一条龙到历史已验证、运营待审核工具"
    )
    pt_build.add_argument("--draft-dir", type=Path, required=True)
    pt_build.add_argument("--bench-root", type=Path,
                          default=Path("~/RepoProofBench").expanduser())
    pt_build.add_argument("--dest-root", type=Path,
                          default=Path("~/tools").expanduser())
    pt_build.add_argument("--rehearsal-only", action="store_true",
                          help="只到 fake 彩排门,不烧真模型预算")
    pt_build.add_argument(
        "--agent-backend",
        choices=["codex-cli", "mini-swe"],
        default="codex-cli",
        help=("真实 AGENT_ADAPT 执行后端:codex-cli=ChatGPT 订阅登录的官方 "
              "Codex harness(产品默认);mini-swe=API provider + 仓内循环"),
    )
    pt_build.add_argument("--batch", default="EXPLORATORY_UNPREREGISTERED")
    pt_plan = tsub.add_parser(
        "plan", help="RFC-013 Gate1:证据化能力表面 + 确定性路由(零模型)")
    pt_plan.add_argument("--repo", default=None, help="公开仓 URL(匿名克隆分析)")
    pt_plan.add_argument("--dir", type=Path, default=None, dest="local_dir",
                         help="本地仓目录(离线分析)")
    pt_plan.add_argument("--capability", required=True, help="用户能力意图原文")
    pt_plan.add_argument("--revision", default=None)
    pt_plan.add_argument("--out", type=Path, required=True, help="plan YAML 落盘路径")
    pt_planc = tsub.add_parser(
        "plan-confirm", help="人闸:逐项确认后翻 confirmed(冻结前必经)")
    pt_planc.add_argument("--plan", type=Path, required=True)
    pt_planc.add_argument("--ack", action="append", default=[],
                          help="确认项原文,可多次;须覆盖 human_confirmations 全部")
    pt_list = tsub.add_parser("list", help="本地工具历史验证+当前运营状态")
    pt_list.add_argument("--dest-root", type=Path,
                         default=Path("~/tools").expanduser())
    pt_list.add_argument("--scan", action="store_true",
                         help="扫描补录未登记的工具包(不伪造导出时间)")
    pt_mcp = tsub.add_parser(
        "mcp", help="仅为历史已验证且运营 ACTIVE 的工具生成 MCP server"
    )
    pt_mcp.add_argument("name")
    pt_mcp.add_argument("--dest-root", type=Path,
                        default=Path("~/tools").expanduser())
    pt_audit = tsub.add_parser(
        "audit", help="以 fresh non-example 输入审核工具并追加 ACTIVE/REVOKED 决策")
    pt_audit.add_argument("name")
    pt_audit.add_argument("--input", required=True, type=Path)
    pt_audit.add_argument("--expected-file", required=True, type=Path)
    pt_audit.add_argument("--build", action="store_true",
                          help="审核前先运行工具包 build.sh")
    pt_audit.add_argument("--dest-root", type=Path,
                          default=Path("~/tools").expanduser())
    pt_withdraw = tsub.add_parser(
        "withdraw", help="只追加 REVOKED 决策；不删除工具包或历史证据")
    pt_withdraw.add_argument("name")
    pt_withdraw.add_argument("--reason", required=True)
    pt_withdraw.add_argument("--dest-root", type=Path,
                             default=Path("~/tools").expanduser())
    pt_import = tsub.add_parser(
        "import-audits", help="从 append-only operator audit JSONL 幂等迁移运营决策")
    pt_import.add_argument("--audits", required=True, type=Path)
    pt_import.add_argument("--dest-root", type=Path,
                           default=Path("~/tools").expanduser())

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

        host_report = analyze_host_project(args.path)
        host_payload = host_report.to_dict()
        if args.json:
            host_payload = {"schema_version": 1, "kind": "host_project_report",
                            "report": host_payload}
        print(json.dumps(host_payload, ensure_ascii=False, indent=2))
        return 0

    if args.cmd in ("analyze-repo", "analyze-source"):
        from repoproof.adoption.analysis.repository_analyzer import (
            analyze_repository,
            analyze_repository_dir,
        )

        url = getattr(args, "url", None) or getattr(args, "repo", None)
        if args.local_path:
            rep = analyze_repository_dir(args.local_path, requested_revision=args.revision)
        elif not url:
            # 互斥组保证二选一,但 --url/--repo 两种别名经 getattr 取值;
            # 取空时如实拒绝,不把 None 送进分析器(那会在克隆层炸出难读的栈)
            print(json.dumps({"ok": False, "error": "缺少 --url/--repo"},
                             ensure_ascii=False))
            return 2
        else:
            rep = analyze_repository(str(url), args.revision,
                                     cache_root=PROJECT_ROOT / "upstream-cache")
        payload = rep.to_dict()
        if args.json:
            payload = {"schema_version": 1, "kind": "repository_report", "report": payload}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "tool-intake":
        from repoproof.adoption.intake.tool_confirm import write_draft_bundle
        from repoproof.adoption.intake.tool_intake import run_tool_intake

        intake_rep = run_tool_intake(
            args.repo or "", args.capability,
            cache_root=PROJECT_ROOT / "upstream-cache",
            revision=args.revision, local_path=args.local_path)
        payload = {"schema_version": 1, "kind": "tool_intake_report",
                   **intake_rep.to_dict()}
        if args.draft_out is not None and intake_rep.draft:
            payload["draft_bundle"] = str(write_draft_bundle(intake_rep, args.draft_out))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "tool":
        if args.tool_cmd == "add":
            from repoproof.adoption.intake.tool_confirm import write_draft_bundle
            from repoproof.adoption.intake.tool_drafter import (
                DraftError,
                FakeDrafter,
                draft_into_bundle,
                online_drafter,
            )
            from repoproof.adoption.intake.tool_intake import run_tool_intake

            add_rep = run_tool_intake(args.repo, args.capability,
                                  cache_root=PROJECT_ROOT / "upstream-cache",
                                  revision=args.revision)
            add_payload: dict = {"admission": add_rep.admission.to_dict()}
            if add_rep.admission.status == "UNSUPPORTED" or not add_rep.draft:
                print(json.dumps({"ok": False, **add_payload},
                                 ensure_ascii=False, indent=2))
                return 3
            bundle = write_draft_bundle(add_rep, args.draft_out)
            add_payload["draft_bundle"] = str(bundle)
            try:
                drafter = FakeDrafter() if args.fake_drafter else online_drafter()
                add_payload["drafted"] = draft_into_bundle(add_rep, bundle, drafter)
            except DraftError as exc:
                add_payload["draft_error"] = str(exc)
                print(json.dumps({"ok": False, **add_payload}, ensure_ascii=False, indent=2))
                return 3
            add_payload["your_todo"] = [
                f"1. 审阅并修改 {bundle}/draft.yaml(statement/summary/格式;"
                "工具名 tool.name 由你定)",
                f"2. 审阅 {bundle}/reference_impl.py(必须真调上游;起草仅供参考)",
                f"3. 放样例真值:{bundle}/examples/ 放输入文件,"
                f"{bundle}/examples.yaml 写 >=3 组断言(含文件样例;尾部自动 held-out)",
                f"4. (可选){bundle}/reference.lock.txt 写全量 pinned",
                f"5. 跑:repoproof tool build --draft-dir {bundle}",
                "6. build 成功后另备 fresh non-example 输入/真值，跑 tool audit 才会 ACTIVE",
            ]
            print(json.dumps({"ok": True, **add_payload}, ensure_ascii=False, indent=2))
            return 0
        if args.tool_cmd == "build":
            from repoproof.adoption.intake.tool_confirm import ConfirmError
            from repoproof.runner.tool_pipeline import (
                PipelineError,
                tool_build,
                tool_build_completed,
            )

            try:
                out = tool_build(args.draft_dir, PROJECT_ROOT,
                                 bench_root=args.bench_root,
                                 dest_root=args.dest_root,
                                 run_real=not args.rehearsal_only,
                                 agent_backend=args.agent_backend,
                                 batch=args.batch)
            except (ConfirmError, PipelineError) as exc:
                print(json.dumps({"ok": False, "error": str(exc),
                                  **({"problems": exc.problems}
                                     if hasattr(exc, "problems") else {})},
                                 ensure_ascii=False, indent=2))
                return 3
            completed = tool_build_completed(
                out, rehearsal_only=args.rehearsal_only
            )
            print(
                json.dumps(
                    {"ok": completed, **out},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if completed else 3
        if args.tool_cmd == "plan":
            import yaml as _yaml

            from repoproof.adoption.admission.support_policy import evaluate_tool_policy
            from repoproof.adoption.analysis.repository_analyzer import (
                analyze_repository,
                analyze_repository_dir,
            )
            from repoproof.adoption.planning.capability_plan import (
                build_capability_plan,
            )

            if bool(args.repo) == bool(args.local_dir):
                print(json.dumps({"ok": False,
                                  "error": "--repo 与 --dir 恰好给一个"},
                                 ensure_ascii=False))
                return 2
            if args.local_dir:
                root = Path(args.local_dir).expanduser().resolve()
                plan_report = analyze_repository_dir(root)
            else:
                # cache_root 是必填关键字参数,漏给会在调用点直接 TypeError
                # ——`tool plan --repo` 这条路径此前**每次必崩**(2026-08-27
                # mypy 首次覆盖 cli 时揪出,已补回归钉)。
                plan_report = analyze_repository(
                    args.repo, revision=args.revision,
                    cache_root=PROJECT_ROOT / "upstream-cache")
                root = (Path(plan_report.sources[0])
                        if plan_report.sources else Path("."))
                # analyze_repository 的分析克隆根:从 to_dict 元数据取不到时
                # 由 clone 缓存约定推导 —— 保守起见要求本地分析用 --dir。
            policy = evaluate_tool_policy(plan_report)
            plan = build_capability_plan(root, plan_report, policy,
                                         goal=args.capability)
            out_p = Path(args.out)
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(_yaml.safe_dump(plan.model_dump(),
                                             allow_unicode=True,
                                             sort_keys=False),
                             encoding="utf-8")
            print(json.dumps({
                "ok": True, "plan": str(out_p),
                "support_status": plan.support_status,
                "implementation_route": plan.implementation_route,
                "reason_codes": plan.reason_codes,
                "surfaces": len(plan.detected_surfaces),
                "plan_sha256": plan.plan_sha256,
                "next": ("tool plan-confirm --plan <file> --ack ... 后方可冻结"
                         if plan.support_status == "SUPPORTED"
                         else "非 SUPPORTED:按 reason_codes 补事实或停止"),
            }, ensure_ascii=False, indent=2))
            return 0
        if args.tool_cmd == "plan-confirm":
            import yaml as _yaml

            from repoproof.adoption.planning.capability_plan import (
                CapabilityPlanV1,
                PlanError,
                confirm_plan,
            )

            plan_p = Path(args.plan)
            plan = CapabilityPlanV1.model_validate(
                _yaml.safe_load(plan_p.read_text(encoding="utf-8")))
            try:
                confirm_plan(plan, acks=list(args.ack))
            except PlanError as exc:
                print(json.dumps({"ok": False, "error": str(exc)},
                                 ensure_ascii=False, indent=2))
                return 3
            plan_p.write_text(_yaml.safe_dump(plan.model_dump(),
                                              allow_unicode=True,
                                              sort_keys=False),
                              encoding="utf-8")
            print(json.dumps({"ok": True, "confirmed": True,
                              "plan_sha256": plan.plan_sha256},
                             ensure_ascii=False, indent=2))
            return 0
        if args.tool_cmd == "list":
            from repoproof.runner.tool_registry import list_tools
            from repoproof.runner.tool_release import ReleaseLedgerError

            try:
                rows = list_tools(args.dest_root, scan=args.scan)
            except (ReleaseLedgerError, OSError, ValueError) as exc:
                print(json.dumps({"ok": False, "error": str(exc)},
                                 ensure_ascii=False, indent=2))
                return 3
            print(json.dumps({"tools": rows}, ensure_ascii=False, indent=2))
            return 0
        if args.tool_cmd == "mcp":
            from repoproof.runner.tool_mcp import write_mcp_server

            try:
                out_p = write_mcp_server(
                    Path(args.dest_root) / args.name, dest_root=args.dest_root)
            except (RuntimeError, OSError, ValueError) as exc:
                print(json.dumps({"ok": False, "error": str(exc)},
                                 ensure_ascii=False, indent=2))
                return 3
            print(json.dumps({
                "ok": True, "server": str(out_p),
                "attach": f"claude mcp add {args.name} -- python3 {out_p}",
            }, ensure_ascii=False, indent=2))
            return 0
        if args.tool_cmd == "audit":
            from repoproof.runner.tool_release import (
                ReleaseLedgerError,
                ToolAuditError,
                audit_tool,
            )

            try:
                result = audit_tool(
                    args.dest_root,
                    args.name,
                    input_path=args.input,
                    expected_file=args.expected_file,
                    run_build=args.build,
                )
            except (ReleaseLedgerError, ToolAuditError, OSError, ValueError) as exc:
                print(json.dumps({"ok": False, "error": str(exc)},
                                 ensure_ascii=False, indent=2))
                return 3
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 3
        if args.tool_cmd == "withdraw":
            from repoproof.runner.tool_release import (
                ReleaseLedgerError,
                ToolAuditError,
                withdraw_tool,
            )

            try:
                decision = withdraw_tool(
                    args.dest_root, args.name, reason=args.reason)
            except (ReleaseLedgerError, ToolAuditError, OSError, ValueError) as exc:
                print(json.dumps({"ok": False, "error": str(exc)},
                                 ensure_ascii=False, indent=2))
                return 3
            print(json.dumps({"ok": True, "decision": decision},
                             ensure_ascii=False, indent=2))
            return 0
        if args.tool_cmd == "import-audits":
            from repoproof.runner.tool_release import (
                ReleaseLedgerError,
                import_audit_decisions,
            )

            try:
                result = import_audit_decisions(args.audits, args.dest_root)
            except (ReleaseLedgerError, OSError, ValueError) as exc:
                print(json.dumps({"ok": False, "error": str(exc)},
                                 ensure_ascii=False, indent=2))
                return 3
            print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
            return 0

    if args.cmd == "tool-draft":
        from repoproof.adoption.intake.tool_drafter import (
            DraftError,
            FakeDrafter,
            draft_into_bundle,
            online_drafter,
        )
        from repoproof.adoption.intake.tool_intake import run_tool_intake

        draft_rep = run_tool_intake(
            args.repo or "", args.capability,
            cache_root=PROJECT_ROOT / "upstream-cache",
            revision=args.revision, local_path=args.local_path)
        try:
            drafter = FakeDrafter() if args.fake else online_drafter()
            out = draft_into_bundle(draft_rep, args.draft_dir, drafter)
        except DraftError as exc:
            print(json.dumps({"ok": False, "error": str(exc)},
                             ensure_ascii=False, indent=2))
            return 3
        print(json.dumps({"ok": True, **out}, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "tool-confirm":
        from repoproof.adoption.intake.tool_confirm import ConfirmError, confirm_tool_draft

        try:
            info = confirm_tool_draft(args.draft_dir, PROJECT_ROOT)
        except ConfirmError as exc:
            print(json.dumps({"ok": False, "problems": exc.problems},
                             ensure_ascii=False, indent=2))
            return 3
        print(json.dumps({"ok": True, **info}, ensure_ascii=False, indent=2))
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
        admission_result = decide(host, repo)
        payload = admission_result.to_dict()
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
