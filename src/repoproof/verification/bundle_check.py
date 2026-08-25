"""verify-bundle — hash & reference integrity of one run's evidence.

Checks (each reported individually):
  contract      file bytes match the frozen .sha256 sidecar
  task_package  committed manifest root hash + all bindings verify
  trace         append-only sha256 chain intact
  final_sha     run_manifest.final_trace_sha256 matches the trace file
  artifacts     every artifact_ref in the trace exists in the store and
                its content re-hashes to its name
  verification  every VerificationResult json parses and its evidence
                refs exist in the artifact store
  adaptation    adaptation_manifest.json matches a re-inventory of the
                frozen zone (when the zone is still present)

Honest scope: this proves the bundle is INTERNALLY consistent and
tamper-EVIDENT — not unforgeable (an author controlling every file
could regenerate a consistent bundle; the git history and the public
evidence commit are the anchors against that).
"""

from __future__ import annotations

import json
from pathlib import Path

from repoproof.domain.models import (
    AdaptationManifest,
    TaskContract,
    VerificationResult,
    sha256_bytes,
    sha256_file,
)
from repoproof.harness import task_package
from repoproof.harness.adaptation import verify_frozen
from repoproof.harness.trace import scan_events, verify_chain
from repoproof.verification import completion_gate


def verify_bundle(run_dir: Path, project_root: Path, contract_path: Path | None) -> dict:
    run_dir = Path(run_dir)
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    # contract + task package
    if contract_path is not None:
        try:
            TaskContract.load_frozen(contract_path, require_sidecar=True)
            add("contract", True, "bytes match frozen sidecar")
        except Exception as exc:  # noqa: BLE001 — report, don't crash
            add("contract", False, str(exc)[:200])
        try:
            manifest = task_package.load_and_verify(project_root, contract_path)
            add("task_package", True, f"root_hash={manifest.root_hash[:16]}… all bindings verify")
        except Exception as exc:  # noqa: BLE001
            add("task_package", False, str(exc)[:200])

    # trace chain
    trace_path = run_dir / "trace.jsonl"
    ok, n, err = verify_chain(trace_path)
    add("trace_chain", ok, f"{n} events" if ok else err)

    # final trace sha recorded in run manifest
    rm_path = run_dir / "run_manifest.json"
    if rm_path.exists():
        rm = json.loads(rm_path.read_text(encoding="utf-8"))
        actual = sha256_file(trace_path)
        recorded = rm.get("final_trace_sha256")
        add(
            "final_trace_sha256",
            actual == recorded,
            "matches run_manifest" if actual == recorded else f"trace={actual[:12]} recorded={str(recorded)[:12]}",
        )
    else:
        add("final_trace_sha256", False, "run_manifest.json missing")

    # artifacts referenced by the trace
    objects = run_dir / "artifacts" / "objects"
    missing = corrupted = 0
    total_refs = 0
    for event in scan_events(trace_path):
        for ref in event.get("artifact_refs", []):
            total_refs += 1
            obj = objects / ref
            if not obj.exists():
                missing += 1
            elif sha256_bytes(obj.read_bytes()) != ref:
                corrupted += 1
    add(
        "artifacts",
        missing == 0 and corrupted == 0,
        f"{total_refs} refs, {missing} missing, {corrupted} corrupted",
    )

    # verification results + their evidence
    bad = 0
    vdir = run_dir / "verification"
    vcount = 0
    for vf in sorted(vdir.glob("*.json")) if vdir.exists() else []:
        vcount += 1
        try:
            data = json.loads(vf.read_text(encoding="utf-8"))
            for ref in data.get("evidence", []):
                if not (objects / ref).exists():
                    bad += 1
        except json.JSONDecodeError:
            bad += 1
    add("verification_results", bad == 0 and vcount > 0, f"{vcount} results, {bad} broken evidence refs")

    # Gate 3A.E — hash closure: VR file hashes, trace refs, gate-input
    # hashes, deterministic gate recomputation, root cross-consistency.
    rm = json.loads(rm_path.read_text(encoding="utf-8")) if rm_path.exists() else {}
    vr_recorded: dict = rm.get("verification_result_hashes") or {}
    vrs: dict[str, VerificationResult] = {}
    vr_problems: list[str] = []
    trace_vr_events = {
        e["actor"]: e for e in scan_events(trace_path, "verification.result")
    }
    for vf in sorted(vdir.glob("*.json")) if vdir.exists() else []:
        actual_sha = sha256_file(vf)
        vr = VerificationResult.model_validate(json.loads(vf.read_text(encoding="utf-8")))
        vrs[vr.verifier] = vr
        if vr_recorded:
            if vr_recorded.get(vr.verifier) != actual_sha:
                vr_problems.append(f"{vr.verifier}: file sha != run_manifest record")
            tev = trace_vr_events.get(vr.verifier)
            if not tev or tev["payload"].get("result_sha256") != actual_sha:
                vr_problems.append(f"{vr.verifier}: trace event does not reference file sha")
            if not (objects / actual_sha).exists():
                vr_problems.append(f"{vr.verifier}: result artifact object missing")
    if vr_recorded:
        gate_events = scan_events(trace_path, "gate.verdict")
        gate_inputs = (gate_events[-1]["payload"].get("verification_input_hashes") if gate_events else None) or {}
        if gate_inputs != vr_recorded:
            vr_problems.append("gate input hashes != run_manifest verification_result_hashes")
        add(
            "verification_hash_closure",
            not vr_problems,
            "; ".join(vr_problems[:4]) or "VR hashes bind file/trace/gate",
        )

        # deterministic gate recomputation
        am_path0 = run_dir / "adaptation_manifest.json"
        adaptation0 = (
            AdaptationManifest.model_validate(json.loads(am_path0.read_text(encoding="utf-8")))
            if am_path0.exists()
            else None
        )
        needed = {"CapabilityVerifier", "HostRegressionVerifier", "PolicyVerifier"}
        if needed.issubset(vrs):
            recomputed = completion_gate.decide(
                capability=vrs["CapabilityVerifier"],
                regression=vrs["HostRegressionVerifier"],
                policy=vrs["PolicyVerifier"],
                replay=vrs.get("ReplayVerifier"),
                adaptation=adaptation0,
                missing_external=rm.get("missing_external") or [],
                budget_exhausted=rm.get("budget_exhausted"),
            )
            recorded_verdicts = {
                "run_manifest": rm.get("final_verdict"),
                "trace": (gate_events[-1]["payload"].get("verdict") if gate_events else None),
            }
            rp_path = run_dir / "report.json"
            if rp_path.exists():
                recorded_verdicts["report"] = json.loads(rp_path.read_text(encoding="utf-8")).get("verdict")
            mismatch = {k: v for k, v in recorded_verdicts.items() if v != recomputed.verdict.value}
            add(
                "gate_recompute",
                not mismatch,
                f"recomputed={recomputed.verdict.value}"
                + ("" if not mismatch else f" but recorded {mismatch}"),
            )
        else:
            add("gate_recompute", False, f"missing verification results: {sorted(needed - set(vrs))}")

        # root cross-consistency
        root_problems: list[str] = []
        if contract_path is not None:
            try:
                pkg = task_package.load_and_verify(project_root, contract_path)
                if rm.get("task_package_root_hash") != pkg.root_hash:
                    root_problems.append("run_manifest.task_package_root_hash != package")
                if pkg.wheelhouse_root and rm.get("wheelhouse_root") != pkg.wheelhouse_root:
                    root_problems.append("run_manifest.wheelhouse_root != package")
            except Exception as exc:  # noqa: BLE001
                root_problems.append(f"package unavailable: {str(exc)[:80]}")
        if adaptation0 is not None and rm.get("adaptation_root") != adaptation0.tree_root_sha256:
            root_problems.append("run_manifest.adaptation_root != adaptation manifest")
        add("root_cross_consistency", not root_problems, "; ".join(root_problems[:3]) or "all roots agree")

    # adaptation manifest vs frozen zone
    am_path = run_dir / "adaptation_manifest.json"
    zone = run_dir / "adaptation"
    if am_path.exists() and zone.exists():
        adaptation = AdaptationManifest.model_validate(
            json.loads(am_path.read_text(encoding="utf-8")))
        ok_a, detail_a = verify_frozen(zone, adaptation)
        add("adaptation", ok_a, detail_a)
    else:
        detail = (
            "manifest present, zone gone (containers destroyed)"
            if am_path.exists()
            else "adaptation_manifest.json missing"
        )
        add("adaptation", am_path.exists(), detail)

    return {"ok": all(c["ok"] for c in checks), "checks": checks}
