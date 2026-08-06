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

from repoproof.domain.models import AdaptationManifest, TaskContract, sha256_bytes, sha256_file
from repoproof.harness import task_package
from repoproof.harness.adaptation import verify_frozen
from repoproof.harness.trace import scan_events, verify_chain


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

    # adaptation manifest vs frozen zone
    am_path = run_dir / "adaptation_manifest.json"
    zone = run_dir / "adaptation"
    if am_path.exists() and zone.exists():
        manifest = AdaptationManifest.model_validate(json.loads(am_path.read_text(encoding="utf-8")))
        ok_a, detail_a = verify_frozen(zone, manifest)
        add("adaptation", ok_a, detail_a)
    else:
        detail = (
            "manifest present, zone gone (containers destroyed)"
            if am_path.exists()
            else "adaptation_manifest.json missing"
        )
        add("adaptation", am_path.exists(), detail)

    return {"ok": all(c["ok"] for c in checks), "checks": checks}
