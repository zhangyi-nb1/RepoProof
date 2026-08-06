"""Direct-adoption baseline runner — a DETERMINISTIC scripted sequence.

Explicitly NOT an agent (design P9): no model call, no planning, no
autonomous loop — a fixed order of actions used to prove the external
evidence chain works before any agent exists. It emits a scripted
``agent.claim_complete`` event precisely so tests can prove the
completion gate ignores self-claims.

Flow (baseline pass, then a clean-room replay pass):
  contract freeze-check → upstream pin → oracle snapshot+hash →
  install container (network per contract) with the arm64 install
  preflight → run container (network=none): ephemeral execution copy,
  direct-adoption probe, capability pytest, regression pytest →
  hashes re-checked → four verifiers → completion gate → report.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from repoproof.domain.models import (
    AdmissionError,
    EnvironmentManifest,
    RepoManifest,
    SourceRepo,
    TaskContract,
    VerificationResult,
    sha256_bytes,
)
from repoproof.execution.docker_backend import DockerExecutionBackend, Mount
from repoproof.harness.budget import BudgetExceeded, BudgetMeter
from repoproof.harness.oracle_guard import hash_tree, make_read_only
from repoproof.harness.policy import evaluate_argv
from repoproof.harness.trace import verify_chain
from repoproof.persistence.run_store import FileRunStore
from repoproof.verification import completion_gate
from repoproof.verification.verifiers import (
    capability_result,
    parse_pytest,
    policy_result,
    replay_result,
)

IMAGE = "python:3.12-slim-bookworm"

_UUID4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def _normalize_probe(payload: object) -> object:
    """Strip volatile fields (uuid ids) so replay comparison targets
    deterministic content. The RAW probe (with uuids) is kept as its
    own artifact — the uuid churn is itself recorded evidence."""
    if isinstance(payload, dict):
        return {
            k: _normalize_probe(v)
            for k, v in payload.items()
            if k not in ("id",)
        }
    if isinstance(payload, list):
        return [_normalize_probe(v) for v in payload]
    if isinstance(payload, str) and _UUID4_RE.match(payload):
        return "<uuid4-stripped>"
    return payload


def ensure_upstream(cache_root: Path, source: SourceRepo) -> tuple[Path, RepoManifest]:
    """Clone the candidate repo pinned to the contract commit; verify
    the pin; hash the tree; make the snapshot physically read-only."""
    cache_root.mkdir(parents=True, exist_ok=True)
    dest = cache_root / f"upstream-{source.resolved_commit[:12]}"
    if not dest.exists():
        tmp = cache_root / f".tmp-{uuid.uuid4().hex[:8]}"
        subprocess.run(["git", "clone", "--quiet", source.url, str(tmp)], check=True, timeout=600)
        subprocess.run(
            ["git", "-C", str(tmp), "-c", "advice.detachedHead=false", "checkout", "--quiet", source.resolved_commit],
            check=True,
            timeout=120,
        )
        tmp.rename(dest)
    head = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if head != source.resolved_commit:
        raise AdmissionError(f"upstream pin mismatch: HEAD={head} contract={source.resolved_commit}")
    license_sha = None
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
        lp = dest / name
        if lp.exists():
            license_sha = sha256_bytes(lp.read_bytes())
            break
    manifest = RepoManifest(
        url=source.url,
        resolved_commit=head,
        license_spdx=source.license,
        license_file_sha256=license_sha,
    )
    make_read_only(dest)
    return dest, manifest


@dataclass
class PassOutcome:
    label: str
    steps_used: int
    capability_exit: int | None
    capability_failed: list[str]
    capability_stdout_sha: str
    regression_exit: int | None
    regression_failed: list[str]
    probe_raw_sha: str
    probe_normalized_sha: str

    def summary(self) -> dict:
        return {
            "capability_exit": self.capability_exit,
            "capability_failed": self.capability_failed,
            "regression_exit": self.regression_exit,
            "regression_failed": self.regression_failed,
            "probe_normalized_sha": self.probe_normalized_sha,
        }


class _Runner:
    def __init__(self, contract_path: Path, project_root: Path, runs_root: Path | None) -> None:
        self.project_root = Path(project_root)
        self.contract, self.contract_sha = TaskContract.load_frozen(Path(contract_path))
        self.run_id = f"{self.contract.task_id}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.store = FileRunStore((runs_root or self.project_root / "runs") / self.run_id)
        self.meter = BudgetMeter(self.contract.budgets)
        self.backend = DockerExecutionBackend(image=IMAGE)
        self.oracle_src = self.project_root / "oracle" / self.contract.task_id
        self.consumer_src = self.project_root / "fixtures" / "consumer_rag"
        self.probes_src = self.project_root / "src" / "repoproof" / "probes"

    # ------------------------------------------------------------ helpers
    def _exec_step(
        self, container: str, argv: list[str], *, label: str, meter: BudgetMeter, workdir: str | None = None
    ) -> tuple:
        """Policy-checked, budget-metered, trace-logged container exec.

        ``meter`` counts steps PER EXECUTION PASS — the contract's
        max_agent_steps bounds one execution, and the clean-room replay
        is a fresh execution with a fresh step budget. The run-level
        meter still enforces the global wall-time budget.
        """
        meter.note_step(label)
        self.meter.check_wall(label)
        decision = evaluate_argv(argv)
        self.store.append_event(
            "policy.decision",
            actor="harness",
            payload={"label": label, "argv": argv, "allowed": decision.allowed, "reasons": decision.reasons},
        )
        if not decision.allowed:
            # Denied actions are never executed; the trace proves it.
            self.store.append_event(
                "action.denied", actor="harness", payload={"label": label, "reasons": decision.reasons}
            )
            raise AdmissionError(f"policy denied scripted step {label}: {decision.reasons}")
        self.store.append_event("action.start", actor="runner", payload={"label": label, "argv": argv})
        res = self.backend.exec(
            container, argv, timeout_s=meter.command_timeout_seconds, workdir=workdir
        )
        out_ref = self.store.store_artifact(
            res.stdout, media_type="text/plain", producer=label, name_hint=f"{label}.stdout"
        )
        err_ref = self.store.store_artifact(
            res.stderr, media_type="text/plain", producer=label, name_hint=f"{label}.stderr"
        )
        self.store.append_event(
            "action.end",
            actor="runner",
            payload={
                "label": label,
                "exit_code": res.exit_code,
                "timed_out": res.timed_out,
                "duration_ms": res.duration_ms,
                "budget": meter.snapshot(),
            },
            artifact_refs=[out_ref.sha256, err_ref.sha256],
        )
        return res, out_ref

    # ------------------------------------------------------------ passes
    def one_pass(self, label: str, upstream: Path, oracle_snap: Path, adaptation: Path) -> PassOutcome:
        meter = BudgetMeter(self.contract.budgets)
        pass_dir = self.store.run_dir / label
        venv_dir = pass_dir / "venv"
        venv_dir.mkdir(parents=True, exist_ok=True)

        install_net = "bridge" if self.contract.environment.network_install else "none"
        c_install = self.backend.start(
            name_prefix=f"rp-{label}-install",
            network=install_net,
            mounts=[Mount(upstream, "/upstream", True), Mount(venv_dir, "/venv", False)],
        )
        try:
            self._exec_step(c_install, ["python3", "-m", "venv", "/venv/env"], meter=meter, label=f"{label}.venv")
            self._exec_step(
                c_install,
                [
                    "sh",
                    "-c",
                    "cp -r /upstream /tmp/build && rm -rf /tmp/build/.git && chmod -R u+w /tmp/build",
                ],
                meter=meter, label=f"{label}.stage-build-copy",
            )
            res, _ = self._exec_step(
                c_install,
                ["/venv/env/bin/pip", "install", "--no-cache-dir", "--disable-pip-version-check", "/tmp/build"],
                meter=meter, label=f"{label}.preflight-install-arm64",
            )
            if res.exit_code != 0:
                self.store.append_event(
                    "env.admission_failure",
                    actor="harness",
                    payload={
                        "kind": "arm64_install_path_failed",
                        "policy": "no silent amd64 switch / no commit change / no contract dilution",
                    },
                )
                raise AdmissionError("arm64 install preflight failed — see preflight-install artifacts")
            self._exec_step(
                c_install,
                ["/venv/env/bin/pip", "install", "--no-cache-dir", "--disable-pip-version-check", "pytest"],
                meter=meter, label=f"{label}.install-pytest",
            )
            self._exec_step(c_install, ["/venv/env/bin/pip", "freeze"], meter=meter, label=f"{label}.pip-freeze")
            self._exec_step(
                c_install,
                [
                    "/venv/env/bin/python",
                    "-c",
                    "import chonkie, platform, sys;"
                    "print(getattr(chonkie,'__version__','?'), platform.machine(), sys.version.split()[0])",
                ],
                meter=meter, label=f"{label}.import-chonkie",
            )
        finally:
            self.backend.destroy(c_install)

        run_env = {
            "PYTHONPATH": "/execution/consumer/src",
            "REPOPROOF_ADAPTATION_DIR": "/adaptation",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        c_run = self.backend.start(
            name_prefix=f"rp-{label}-run",
            network="none",
            mounts=[
                Mount(upstream, "/upstream", True),
                Mount(oracle_snap, "/oracle", True),
                Mount(adaptation, "/adaptation", False),
                Mount(venv_dir, "/venv", False),
                Mount(self.consumer_src, "/consumer_src", True),
                Mount(self.probes_src, "/probes", True),
            ],
            env=run_env,
        )
        try:
            # Ephemeral execution tree: container-local copy, destroyed
            # with the container — never persisted.
            self._exec_step(
                c_run,
                [
                    "sh",
                    "-c",
                    "mkdir -p /execution && cp -r /consumer_src /execution/consumer && chmod -R u+w /execution",
                ],
                meter=meter, label=f"{label}.execution-copy",
            )
            self._exec_step(
                c_run,
                [
                    "/venv/env/bin/python",
                    "-c",
                    (
                        "import urllib.request,sys\n"
                        "try:\n"
                        "    urllib.request.urlopen('https://pypi.org', timeout=5); sys.exit(1)\n"
                        "except Exception:\n"
                        "    print('network-none-confirmed')"
                    ),
                ],
                meter=meter, label=f"{label}.network-none-check",
            )
            probe_res, probe_ref = self._exec_step(
                c_run,
                ["/venv/env/bin/python", "/probes/direct_chonkie_probe.py", "/oracle/fixtures/input_documents.json"],
                meter=meter, label=f"{label}.direct-probe",
                workdir="/execution",
            )
            try:
                normalized = _normalize_probe(json.loads(probe_res.stdout.decode("utf-8", errors="replace")))
                norm_bytes = json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()
            except json.JSONDecodeError:
                norm_bytes = b"<probe-not-json>"
            norm_ref = self.store.store_artifact(
                norm_bytes,
                media_type="application/json",
                producer=f"{label}.direct-probe",
                name_hint="probe.normalized.json",
            )
            cap_res, cap_ref = self._exec_step(
                c_run,
                ["/venv/env/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "/oracle/test_capability.py"],
                meter=meter, label=f"{label}.capability-pytest",
                workdir="/execution",
            )
            reg_res, _reg_ref = self._exec_step(
                c_run,
                ["/venv/env/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "/oracle/test_regression.py"],
                meter=meter, label=f"{label}.regression-pytest",
                workdir="/execution",
            )
        finally:
            self.backend.destroy(c_run)

        cap_stdout = cap_res.stdout.decode("utf-8", errors="replace")
        reg_stdout = reg_res.stdout.decode("utf-8", errors="replace")
        return PassOutcome(
            label=label,
            steps_used=meter.steps_used,
            capability_exit=cap_res.exit_code,
            capability_failed=parse_pytest(cap_stdout)["failed_tests"],
            capability_stdout_sha=cap_ref.sha256,
            regression_exit=reg_res.exit_code,
            regression_failed=parse_pytest(reg_stdout)["failed_tests"],
            probe_raw_sha=probe_ref.sha256,
            probe_normalized_sha=norm_ref.sha256,
        )

    # ------------------------------------------------------------ full run
    def run(self) -> dict:
        ev = self.store.append_event
        ev(
            "run.start",
            actor="runner",
            payload={
                "run_id": self.run_id,
                "mode": "direct-adoption-baseline",
                "scripted_sequence": True,
                "agent": None,
                "llm_calls": 0,
            },
        )
        ev("contract.frozen", actor="harness", payload={"task_id": self.contract.task_id, "sha256": self.contract_sha})

        ok, server = self.backend.available()
        if not ok:
            raise AdmissionError(f"docker unavailable: {server}")
        self.backend.pull()

        upstream, repo_manifest = ensure_upstream(self.project_root / "upstream-cache", self.contract.source_repo)
        ev("upstream.pinned", actor="harness", payload=repo_manifest.model_dump())

        oracle_snap = self.store.run_dir / "oracle_snapshot"
        shutil.copytree(self.oracle_src, oracle_snap)
        make_read_only(oracle_snap)
        adaptation = self.store.run_dir / "adaptation"
        adaptation.mkdir(exist_ok=True)

        oracle_before = hash_tree(oracle_snap)
        upstream_before = _hash_tree_skip_symlinks(upstream)
        ora_ref = self.store.store_artifact(
            json.dumps(oracle_before, sort_keys=True).encode(), media_type="application/json",
            producer="oracle-guard", name_hint="oracle.before.json",
        )
        ev("oracle.hashed", actor="harness", payload={"files": len(oracle_before)}, artifact_refs=[ora_ref.sha256])

        env_manifest = EnvironmentManifest(
            host_os=platform.system(),
            host_os_version=platform.mac_ver()[0] or platform.release(),
            host_arch=platform.machine(),
            docker_client=_docker_fmt("{{.Client.Version}}"),
            docker_server=server,
            runtime_provider=_colima_version(),
            image=IMAGE,
            image_digest=self.backend.image_digest(),
            network_install="bridge" if self.contract.environment.network_install else "none",
            network_run="none",
            agent_model=None,
            notes=["Gate 2: no agent, no LLM calls; scripted deterministic sequence only"],
        )
        self.store.save_json("environment_manifest.json", env_manifest.model_dump())
        ev("env.manifest", actor="harness", payload={"image": IMAGE, "digest": env_manifest.image_digest})

        blocked: list[str] = []
        first = replay = None
        try:
            first = self.one_pass("baseline", upstream, oracle_snap, adaptation)
            # Scripted claim — the gate MUST ignore this (tested).
            ev(
                "agent.claim_complete",
                actor="scripted-fixture",
                payload={"note": "scripted self-claim; completion gate must not honor this"},
            )
            replay = self.one_pass("replay", upstream, oracle_snap, adaptation)
        except AdmissionError as exc:
            blocked.append(str(exc))
        except BudgetExceeded as exc:
            ev("budget.exhausted", actor="harness", payload={"kind": exc.kind, "detail": exc.detail})
            blocked.append(f"budget exhausted: {exc.kind} ({exc.detail})")

        oracle_after = hash_tree(oracle_snap)
        upstream_after = _hash_tree_skip_symlinks(upstream)
        adaptation_files = sorted(str(p.relative_to(adaptation)) for p in adaptation.rglob("*") if p.is_file())

        if first is not None:
            cap = capability_result(
                exit_code=first.capability_exit,
                stdout=self.store.artifacts.read(first.capability_stdout_sha).decode("utf-8", errors="replace"),
                evidence=[first.capability_stdout_sha],
            )
            reg_ok = first.regression_exit == 0
            reg = VerificationResult(
                verifier="HostRegressionVerifier",
                passed=reg_ok,
                detail=(
                    "host fixture regression intact"
                    if reg_ok
                    else f"host regression broken: {first.regression_failed[:8]}"
                ),
                extra={"exit_code": first.regression_exit, "failed_tests": first.regression_failed},
            )
        else:
            cap = VerificationResult(
                verifier="CapabilityVerifier", passed=False, detail="not run (admission failure)"
            )
            reg = VerificationResult(
                verifier="HostRegressionVerifier", passed=False, detail="not run (admission failure)"
            )

        pol = policy_result(
            trace_path=self.store.trace_path,
            oracle_before=oracle_before,
            oracle_after=oracle_after,
            upstream_before=upstream_before,
            upstream_after=upstream_after,
            adaptation_files=adaptation_files,
            max_patch_files=self.contract.budgets.max_patch_files,
            evidence=[ora_ref.sha256],
        )
        rep = None
        if first is not None and replay is not None:
            rep = replay_result(first=first.summary(), replay=replay.summary(), evidence=[first.probe_normalized_sha])

        for r in (cap, reg, pol) + ((rep,) if rep else ()):
            self.store.save_verification(r)
            ev("verification.result", actor=r.verifier, payload={"passed": r.passed, "detail": r.detail})

        gate = completion_gate.decide(
            capability=cap,
            regression=reg,
            policy=pol,
            replay=rep,
            adaptation_present=bool(adaptation_files),
            blocked_conditions=blocked,
        )
        ev("gate.verdict", actor="completion-gate", payload=gate.model_dump(mode="json"))

        chain_ok, n_events, chain_err = verify_chain(self.store.trace_path)
        report = {
            "run_id": self.run_id,
            "task_id": self.contract.task_id,
            "contract_sha256": self.contract_sha,
            "mode": "direct-adoption-baseline (scripted, no agent, no LLM)",
            "verdict": gate.verdict.value,
            "gate_reasons": gate.reasons,
            "capability_failed_tests": first.capability_failed if first else [],
            "regression_failed_tests": first.regression_failed if first else [],
            "replay_consistent": (rep.passed if rep else None),
            "trace_chain": {"ok": chain_ok, "events": n_events, "error": chain_err},
            "budget_wall": self.meter.snapshot(),
            "steps_per_pass": {
                "baseline": first.steps_used if first else None,
                "replay": replay.steps_used if replay else None,
            },
            "adaptation_files": adaptation_files,
        }
        self.store.save_json("report.json", report)
        ev("run.end", actor="runner", payload={"verdict": gate.verdict.value, "events": n_events})
        return report


def _hash_tree_skip_symlinks(root: Path) -> dict[str, str]:
    import hashlib

    out: dict[str, str] = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _docker_fmt(fmt: str) -> str:
    proc = subprocess.run(["docker", "version", "--format", fmt], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "?"


def _colima_version() -> str:
    proc = subprocess.run(["colima", "version"], capture_output=True, text=True)
    first = proc.stdout.strip().splitlines()[:1]
    return f"colima ({first[0]})" if first else "colima (?)"


def run_baseline(contract_path: Path, project_root: Path, runs_root: Path | None = None) -> dict:
    runner = _Runner(contract_path, project_root, runs_root)
    try:
        return runner.run()
    finally:
        runner.backend.destroy_all()
