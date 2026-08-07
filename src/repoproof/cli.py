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

    p_trace = sub.add_parser("verify-trace", help="verify the tamper-evident trace chain of a run")
    p_trace.add_argument("--run-dir", required=True, type=Path)

    p_agent = sub.add_parser("agent-run", help="Gate 3C/4A: provider admission + ONE real agent run")
    p_agent.add_argument("--contract", required=True, type=Path)
    p_agent.add_argument("--budget-visibility", action="store_true", help="Gate 4A ablation variable")
    p_agent.add_argument("--coverage-ledger", action="store_true", help="Gate 4B ablation variable")

    p_bundle = sub.add_parser("verify-bundle", help="verify hash/reference integrity of a run bundle")
    p_bundle.add_argument("--run-dir", required=True, type=Path)
    p_bundle.add_argument("--contract", type=Path, default=None)

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
            env_constraints = {
                "machine": "aarch64" if contract.environment.arch == "arm64" else contract.environment.arch,
                "python": contract.environment.python,
                "chonkie": "1.7.0",
            }
        manifest = task_package.freeze(
            PROJECT_ROOT,
            args.contract,
            upstream_dir=upstream,
            collection=collection,
            wheelhouse_manifest=wheelhouse_manifest,
            image_digest=image_digest,
            environment_constraints=env_constraints,
        )
        print(json.dumps(manifest.model_dump(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.cmd == "agent-run":
        from repoproof.runner.agent_run import provider_from_env, run_gate3c

        out = run_gate3c(
            args.contract,
            PROJECT_ROOT,
            provider_from_env(),
            budget_visibility=args.budget_visibility,
            coverage_ledger=args.coverage_ledger,
        )
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
