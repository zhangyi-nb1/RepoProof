"""Direct-adoption baseline runner — a DETERMINISTIC scripted sequence.

Explicitly NOT an agent (design P9): no model call, no planning, no
autonomous loop. It exists to prove the external evidence chain works
before any agent does, and it emits a scripted ``agent.claim_complete``
event precisely so tests can prove the completion gate ignores it.

Gate 2.5 hardening implemented here:
  * runner REFUSES unfrozen contracts (sidecar required) and only
    VERIFIES the committed TaskPackageManifest — never regenerates it;
  * source evidence: pinned HEAD, HEAD^{tree}, clean worktree, content
    tree hash; wheel(house) built ONCE from the pinned source, then
    both passes install OFFLINE (network=none) from the same
    content-addressed wheelhouse;
  * containers run non-root, cap-drop ALL, no-new-privileges, by IMAGE
    DIGEST; network=none is proven by docker inspect AND an in-container
    socket probe, not a catch-all HTTP exception;
  * every action carries an action_id; policy.decision / action.start /
    action.end / action.denied share it (causality verified);
  * the adaptation zone is FROZEN (AdaptationManifest + read-only)
    after the (empty) agent phase; verifiers consume the frozen
    manifest and the tree hash is re-checked before and after;
  * replay runs in mode=baseline_failure_reproduction — it reproduces
    the failing baseline and can never ground a final PASS;
  * budget exhaustion with unmet hard goals is FAIL/BUDGET_EXHAUSTED
    (BLOCKED is reserved for missing external facts/resources);
  * ``run.end`` is written BEFORE the final chain verification; the
    final trace sha256 + event count land in run_manifest.json.
"""

from __future__ import annotations

import json
import os
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
    sha256_file,
)
from repoproof.execution.docker_backend import DockerExecutionBackend, Mount
from repoproof.execution.profiles import verifier_profile
from repoproof.harness import task_package
from repoproof.harness.adaptation import PatchBudgetExceeded, freeze_adaptation, verify_frozen
from repoproof.harness.budget import BudgetExceeded, BudgetMeter
from repoproof.harness.oracle_guard import hash_tree, make_read_only
from repoproof.harness.policy import evaluate_argv
from repoproof.harness.trace import verify_chain
from repoproof.harness.wheelhouse import select_wheel, verify_wheelhouse
from repoproof.persistence.run_store import FileRunStore
from repoproof.verification import completion_gate
from repoproof.verification.junit import check_test_completion, parse_junit_xml
from repoproof.verification.verifiers import (
    REPLAY_MODE_BASELINE,
    capability_result,
    parse_pytest,
    policy_result,
    regression_result,
    replay_result,
)

IMAGE = "python:3.12-slim-bookworm"

_UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _normalize_probe(payload: object) -> object:
    """Strip volatile fields (per-call upstream ids) so replay
    comparison targets deterministic content. RAW probe is kept — the
    id churn is itself recorded evidence."""
    if isinstance(payload, dict):
        return {k: _normalize_probe(v) for k, v in payload.items() if k not in ("id",)}
    if isinstance(payload, list):
        return [_normalize_probe(v) for v in payload]
    if isinstance(payload, str) and _UUID4_RE.match(payload):
        return "<uuid4-stripped>"
    return payload


def ensure_upstream(cache_root: Path, source: SourceRepo) -> tuple[Path, RepoManifest]:
    """Pinned clone + full source evidence: HEAD, HEAD^{tree}, clean
    worktree status, content tree hash; snapshot made read-only."""
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

    def _git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(dest), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    head = _git("rev-parse", "HEAD")
    if head != source.resolved_commit:
        raise AdmissionError(f"upstream pin mismatch: HEAD={head} contract={source.resolved_commit}")
    git_tree = _git("rev-parse", "HEAD^{tree}")
    porcelain = _git("status", "--porcelain")
    if porcelain:
        raise AdmissionError(
            f"upstream worktree not clean (dirty/tracked-mod/untracked): {porcelain.splitlines()[:3]}"
        )
    worktree_clean = True
    content_tree = _content_tree_sha(dest)
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
        git_tree_hash=git_tree,
        worktree_clean=worktree_clean,
        content_tree_sha256=content_tree,
    )
    make_read_only(dest)
    return dest, manifest


def _content_tree_sha(root: Path) -> str:
    entries: dict[str, str] = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_symlink() or not p.is_file() or ".git" in p.parts:
            continue
        entries[str(p.relative_to(root))] = sha256_bytes(p.read_bytes())
    return sha256_bytes(json.dumps(entries, sort_keys=True).encode())


@dataclass
class PassOutcome:
    label: str
    steps_used: int
    capability_exit: int | None
    capability_failed: list[str]
    capability_stdout_sha: str
    regression_exit: int | None
    regression_stdout_sha: str
    regression_failed: list[str]
    probe_raw_sha: str
    probe_normalized_sha: str
    capability_completion: object | None = None
    regression_completion: object | None = None

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
        self.contract_path = Path(contract_path)
        # Official runs REQUIRE the frozen sidecar and the committed
        # task package manifest; both verified, neither regenerated.
        self.contract, self.contract_sha = TaskContract.load_frozen(self.contract_path, require_sidecar=True)
        self.package = task_package.load_and_verify(self.project_root, self.contract_path)
        self.run_id = f"{self.contract.task_id}-{time.strftime('%Y%m%d-%H%M%S')}"
        self.store = FileRunStore((runs_root or self.project_root / "runs") / self.run_id)
        self.meter = BudgetMeter(self.contract.budgets)  # global wall clock
        self.backend = DockerExecutionBackend(image=IMAGE)
        self.image_ref: str = IMAGE
        self.oracle_src = self.project_root / "oracle" / self.contract.task_id
        self.consumer_src = self.project_root / Path(self.contract.target_project.path)
        self.probes_src = self.project_root / "src" / "repoproof" / "probes"
        self.user = f"{os.getuid()}:{os.getgid()}"
        self.expected_nodes: dict | None = None
        if self.package.collection_manifest_sha256:
            cpath = task_package.collection_path_for(self.contract_path)
            self.expected_nodes = json.loads(cpath.read_text(encoding="utf-8"))
        self._action_seq = 0
        self.timings: dict[str, float] = {
            "system_setup_s": 0.0,
            "verification_s": 0.0,
            "replay_s": 0.0,
            "agent_model_call_s": 0.0,
            "agent_command_s": 0.0,
        }

    # ------------------------------------------------------------ helpers
    def _next_action_id(self) -> str:
        self._action_seq += 1
        return f"a{self._action_seq:04d}"

    def _exec_step(
        self,
        container: str,
        argv: list[str],
        *,
        label: str,
        meter: BudgetMeter,
        workdir: str | None = None,
        actor_kind: str = "harness_setup",
    ) -> tuple:
        """Policy-checked, budget-metered, causally-traced container exec.

        One action_id threads policy.decision → action.start →
        action.end (or action.denied). ``meter`` counts steps PER
        EXECUTION PASS; the run-level meter enforces global wall time.
        """
        action_id = self._next_action_id()
        meter.note_step(label)
        self.meter.check_wall(label)
        decision = evaluate_argv(argv, actor_kind=actor_kind)
        self.store.append_event(
            "policy.decision",
            actor="harness",
            payload={
                "action_id": action_id,
                "label": label,
                "argv": argv,
                "actor_kind": actor_kind,
                "allowed": decision.allowed,
                "reasons": decision.reasons,
            },
        )
        if not decision.allowed:
            self.store.append_event(
                "action.denied",
                actor="harness",
                payload={"action_id": action_id, "label": label, "reasons": decision.reasons},
            )
            raise AdmissionError(f"policy denied scripted step {label}: {decision.reasons}")
        self.store.append_event(
            "action.start",
            actor="runner",
            payload={"action_id": action_id, "label": label, "argv": argv},
        )
        res = self.backend.exec(container, argv, timeout_s=meter.command_timeout_seconds, workdir=workdir)
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
                "action_id": action_id,
                "label": label,
                "exit_code": res.exit_code,
                "timed_out": res.timed_out,
                "duration_ms": res.duration_ms,
                "budget": meter.snapshot(),
            },
            artifact_refs=[out_ref.sha256, err_ref.sha256],
        )
        return res, out_ref

    # ------------------------------------------------------------ wheelhouse
    def ensure_wheelhouse(self, upstream: Path, meter: BudgetMeter) -> tuple[Path, dict]:
        """Build wheels ONCE from the pinned source (network allowed per
        contract.network_install); both passes then install offline from
        this content-addressed wheelhouse."""
        wh = self.project_root / "upstream-cache" / f"wheelhouse-{self.contract.source_repo.resolved_commit[:12]}"
        manifest_path = wh / "wheelhouse_manifest.json"
        if not manifest_path.exists():
            wh.mkdir(parents=True, exist_ok=True)
            net = "bridge" if self.contract.environment.network_install else "none"
            stage = self.store.run_dir / "_src_stage"
            stage.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "-C", str(upstream), "archive", "--format=tar",
                 "-o", str(stage / "source.tar"), self.contract.source_repo.resolved_commit],
                check=True,
                timeout=300,
            )
            c = self.backend.start(
                name_prefix="rp-wheelhouse",
                network=net,
                mounts=[Mount(stage, "/src_stage", True), Mount(wh, "/wheels", False)],
                user=self.user,
                image_ref=self.image_ref,
            )
            try:
                self._exec_step(
                    c,
                    ["sh", "-c", "mkdir -p /tmp/build && tar -xf /src_stage/source.tar -C /tmp/build"],
                    label="wheelhouse.stage-source-git-archive",
                    meter=meter,
                )
                res, _ = self._exec_step(
                    c,
                    ["python3", "-m", "pip", "wheel", "--no-cache-dir",
                     "--disable-pip-version-check", "/tmp/build", "-w", "/wheels"],
                    label="wheelhouse.build-chonkie",
                    meter=meter,
                )
                if res.exit_code != 0:
                    raise AdmissionError("wheel build failed on arm64 — see wheelhouse.build-chonkie artifacts")
                self._exec_step(
                    c,
                    ["python3", "-m", "pip", "wheel", "--no-cache-dir",
                     "--disable-pip-version-check", "pytest", "-w", "/wheels"],
                    label="wheelhouse.build-pytest",
                    meter=meter,
                )
            finally:
                self.backend.destroy(c)
            wheels = {p.name: sha256_file(p) for p in sorted(wh.glob("*.whl"))}
            manifest = {"wheels": wheels, "root": sha256_bytes(json.dumps(wheels, sort_keys=True).encode())}
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return wh, manifest

    # ------------------------------------------------------------ passes
    def _install_phase(self, label: str, wheelhouse: Path, meter: BudgetMeter) -> Path:
        """Wheelhouse admission + offline venv provisioning + env
        admission for one pass (shared by verifier passes and the agent
        phase — the agent gets the IDENTICAL pinned environment)."""
        venv_dir = self.store.run_dir / label / "venv"
        venv_dir.mkdir(parents=True, exist_ok=True)

        # -------- wheelhouse admission BEFORE every pass (D)
        if self.package.wheelhouse_root and self.package.wheelhouse_wheels:
            verified = verify_wheelhouse(
                wheelhouse,
                expected_wheels=self.package.wheelhouse_wheels,
                expected_root=self.package.wheelhouse_root,
            )
            sel_name, sel_sha = select_wheel(self.package.wheelhouse_wheels, "chonkie")
            expected_names = sorted(self.package.wheelhouse_wheels)
        else:  # legacy (v1/v2 packages without wheelhouse binding)
            local = json.loads((wheelhouse / "wheelhouse_manifest.json").read_text())
            verified = local
            sel_name, sel_sha = select_wheel(local["wheels"], "chonkie")
            expected_names = sorted(local["wheels"])
        self.store.append_event(
            "wheelhouse.verified",
            actor="harness",
            payload={
                "pass": label,
                "root": verified["root"],
                "wheels": len(expected_names),
                "selected_chonkie_wheel": sel_name,
                "selected_chonkie_sha256": sel_sha,
            },
        )

        # -------- offline install phase (network=none, wheelhouse only)
        c_install = self.backend.start(
            name_prefix=f"rp-{label}-install",
            network="none",
            mounts=[Mount(wheelhouse, "/wheels", True), Mount(venv_dir, "/venv", False)],
            user=self.user,
            image_ref=self.image_ref,
        )
        try:
            self._exec_step(c_install, ["python3", "-m", "venv", "/venv/env"], label=f"{label}.venv", meter=meter)
            res, _ = self._exec_step(
                c_install,
                [
                    "/venv/env/bin/pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    "--no-cache-dir",
                    "--disable-pip-version-check",
                ]
                + [f"/wheels/{name}" for name in expected_names],
                label=f"{label}.offline-install-explicit-wheels",
                meter=meter,
            )
            if res.exit_code != 0:
                raise AdmissionError(f"offline install from wheelhouse failed in {label}")
            self._exec_step(c_install, ["/venv/env/bin/pip", "freeze"], label=f"{label}.pip-freeze", meter=meter)
            self._exec_step(
                c_install,
                [
                    "/venv/env/bin/python",
                    "-c",
                    (
                        "import json,glob;"
                        "p=glob.glob('/venv/env/lib/python3*/site-packages/chonkie-*.dist-info/direct_url.json');"
                        "print(open(p[0]).read() if p else 'no-direct_url')"
                    ),
                ],
                label=f"{label}.direct-url",
                meter=meter,
            )
            probe_env, _ = self._exec_step(
                c_install,
                [
                    "/venv/env/bin/python",
                    "-c",
                    (
                        "import json, platform, sys, chonkie;"
                        "print(json.dumps({'machine': platform.machine(),"
                        "'python': '%d.%d' % sys.version_info[:2],"
                        "'chonkie': getattr(chonkie, '__version__', '?')}))"
                    ),
                ],
                label=f"{label}.env-probe",
                meter=meter,
            )
            try:
                env_probe = json.loads(probe_env.stdout.decode("utf-8", errors="replace").strip())
            except json.JSONDecodeError as exc:
                raise AdmissionError(f"env probe unparseable in {label}: {exc}") from exc
            expected_env = self.package.environment_constraints or {}
            for key, want in expected_env.items():
                got = str(env_probe.get(key))
                if got != str(want):
                    raise AdmissionError(
                        f"environment admission failed in {label}: {key}={got!r} != contract {want!r}"
                    )
            self.store.append_event(
                "environment.admitted",
                actor="harness",
                payload={"pass": label, **env_probe, "checked_against": expected_env},
            )
        finally:
            self.backend.destroy(c_install)
        return venv_dir

    def one_pass(
        self, label: str, upstream: Path, oracle_snap: Path, adaptation: Path, wheelhouse: Path
    ) -> PassOutcome:
        meter = BudgetMeter(self.contract.budgets)
        venv_dir = self._install_phase(label, wheelhouse, meter)

        # -------- verification phase (verifier profile, network=none)
        profile = verifier_profile(
            upstream=upstream,
            consumer_clean=self.consumer_src,
            adaptation=adaptation,
            oracle_snapshot=oracle_snap,
            venv=venv_dir,
            probes=self.probes_src,
        )
        kwargs = profile.start_kwargs()
        kwargs["user"] = self.user
        c_run = self.backend.start(name_prefix=f"rp-{label}-verify", image_ref=self.image_ref, **kwargs)
        try:
            security = self.backend.inspect_security(c_run)
            self.store.append_event(
                "container.security",
                actor="harness",
                payload={"label": f"{label}.verify", "profile": profile.name, **security},
            )
            if str(security.get("network_mode")) != "none":
                raise AdmissionError(f"verifier container network_mode={security.get('network_mode')} != none")
            self._exec_step(
                c_run,
                ["sh", "-c", "mkdir -p /tmp/execution && cp -r /consumer_src /tmp/execution/consumer"],
                label=f"{label}.execution-copy",
                meter=meter,
            )
            self._exec_step(
                c_run,
                [
                    "/venv/env/bin/python",
                    "-c",
                    (
                        "import socket\n"
                        "try:\n"
                        "    socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
                        "    print('UNEXPECTED-NETWORK-ACCESS'); raise SystemExit(1)\n"
                        "except OSError as exc:\n"
                        "    print('socket-probe-blocked:', type(exc).__name__)"
                    ),
                ],
                label=f"{label}.socket-probe",
                meter=meter,
            )
            probe_res, probe_ref = self._exec_step(
                c_run,
                ["/venv/env/bin/python", "/probes/direct_chonkie_probe.py", "/oracle/fixtures/public_documents.json"],
                label=f"{label}.direct-probe",
                meter=meter,
                workdir="/tmp/execution",
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
            cap_cmd = ["/venv/env/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                       "/oracle/test_capability.py", "--junitxml=/tmp/execution/junit_cap.xml"]
            cap_res, cap_ref = self._exec_step(
                c_run, cap_cmd, label=f"{label}.capability-pytest", meter=meter, workdir="/tmp/execution"
            )
            cap_junit_res = self.backend.exec(c_run, ["cat", "/tmp/execution/junit_cap.xml"], timeout_s=30)
            reg_cmd = ["/venv/env/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                       "/oracle/test_regression.py", "--junitxml=/tmp/execution/junit_reg.xml"]
            reg_res, reg_ref = self._exec_step(
                c_run, reg_cmd, label=f"{label}.regression-pytest", meter=meter, workdir="/tmp/execution"
            )
            reg_junit_res = self.backend.exec(c_run, ["cat", "/tmp/execution/junit_reg.xml"], timeout_s=30)
        finally:
            self.backend.destroy(c_run)

        cap_junit = parse_junit_xml(cap_junit_res.stdout if cap_junit_res.exit_code == 0 else None)
        reg_junit = parse_junit_xml(reg_junit_res.stdout if reg_junit_res.exit_code == 0 else None)
        for name, data in (("junit_cap.xml", cap_junit_res), ("junit_reg.xml", reg_junit_res)):
            if data.exit_code == 0:
                self.store.store_artifact(
                    data.stdout, media_type="application/xml", producer=f"{label}.junit", name_hint=name
                )

        cap_stdout = cap_res.stdout.decode("utf-8", errors="replace")
        reg_stdout = reg_res.stdout.decode("utf-8", errors="replace")
        cap_completion = reg_completion = None
        if self.expected_nodes is not None:
            cap_completion = check_test_completion(
                exit_code=cap_res.exit_code, junit=cap_junit,
                expected_node_ids=self.expected_nodes["capability_nodes"],
            )
            reg_completion = check_test_completion(
                exit_code=reg_res.exit_code, junit=reg_junit,
                expected_node_ids=self.expected_nodes["regression_nodes"],
            )
        def _junit_failed(junit: dict, stdout: str) -> list[str]:
            if junit.get("junit_present") and not junit.get("junit_parse_error"):
                return sorted(n["node_id"] for n in junit.get("nodes", []) if n["outcome"] != "passed")
            return parse_pytest(stdout)["failed_tests"]

        cap_failed = _junit_failed(cap_junit, cap_stdout)
        reg_failed = _junit_failed(reg_junit, reg_stdout)
        return PassOutcome(
            label=label,
            steps_used=meter.steps_used,
            capability_exit=cap_res.exit_code,
            capability_failed=cap_failed,
            capability_stdout_sha=cap_ref.sha256,
            capability_completion=cap_completion,
            regression_exit=reg_res.exit_code,
            regression_stdout_sha=reg_ref.sha256,
            regression_failed=reg_failed,
            regression_completion=reg_completion,
            probe_raw_sha=probe_ref.sha256,
            probe_normalized_sha=norm_ref.sha256,
        )

    # ------------------------------------------------------------ full run
    def run(self) -> dict:
        ev = self.store.append_event
        t0 = time.monotonic()
        ev(
            "run.start",
            actor="runner",
            payload={
                "run_id": self.run_id,
                "mode": "direct-adoption-baseline",
                "scripted_sequence": True,
                "agent": None,
                "llm_calls": 0,
                "task_package_root_hash": self.package.root_hash,
            },
        )
        ev("contract.frozen", actor="harness", payload={"task_id": self.contract.task_id, "sha256": self.contract_sha})
        ev("task_package.verified", actor="harness", payload={"root_hash": self.package.root_hash})

        missing_external: list[str] = []
        budget_exhausted: str | None = None
        first = replay = None
        adaptation_manifest = None
        setup_meter = BudgetMeter(self.contract.budgets)

        ok, server = self.backend.available()
        if not ok:
            missing_external.append(f"docker unavailable: {server}")
        upstream = oracle_snap = adaptation = wheelhouse = None
        oracle_before: dict = {}
        upstream_before: dict = {}
        env_manifest = None

        if not missing_external:
            self.backend.pull()
            digest = self.backend.image_digest()
            if digest:
                self.image_ref = digest
            upstream, repo_manifest = ensure_upstream(
                self.project_root / "upstream-cache", self.contract.source_repo
            )
            if repo_manifest.git_tree_hash != self.package.source_git_tree_hash:
                raise AdmissionError("upstream git tree hash != task package binding")
            ev("upstream.pinned", actor="harness", payload=repo_manifest.model_dump())

            wheelhouse, wh_manifest = self.ensure_wheelhouse(upstream, setup_meter)
            ev(
                "wheelhouse.frozen",
                actor="harness",
                payload={"root": wh_manifest["root"], "wheels": len(wh_manifest["wheels"])},
            )

            oracle_snap = self.store.run_dir / "oracle_snapshot"
            shutil.copytree(self.oracle_src, oracle_snap)
            make_read_only(oracle_snap)
            adaptation = self.store.run_dir / "adaptation"
            adaptation.mkdir(exist_ok=True)
            oracle_before = hash_tree(oracle_snap)
            upstream_before = _skip_symlink_tree(upstream)
            ora_ref = self.store.store_artifact(
                json.dumps(oracle_before, sort_keys=True).encode(),
                media_type="application/json",
                producer="oracle-guard",
                name_hint="oracle.before.json",
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
                image_digest=digest,
                network_install="none (offline wheelhouse)",
                network_run="none",
                agent_model=None,
                notes=[
                    "Gate 2.5: no agent, no LLM calls; scripted deterministic sequence",
                    f"containers run as user {self.user}, cap-drop ALL, no-new-privileges",
                ],
            )
            self.store.save_json("environment_manifest.json", env_manifest.model_dump())
            ev("env.manifest", actor="harness", payload={"image": IMAGE, "digest": digest})

            # Agent phase would run HERE (Gate 3). It is empty in the
            # baseline; the adaptation zone is frozen immediately after.
            try:
                adaptation_manifest = freeze_adaptation(adaptation, self.contract.budgets)
            except PatchBudgetExceeded as exc:
                budget_exhausted = str(exc)
                adaptation_manifest = None
            if adaptation_manifest is not None:
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
        self.timings["system_setup_s"] = round(time.monotonic() - t0, 1)

        if not missing_external and budget_exhausted is None:
            try:
                t1 = time.monotonic()
                first = self.one_pass("baseline", upstream, oracle_snap, adaptation, wheelhouse)
                self.timings["verification_s"] = round(time.monotonic() - t1, 1)
                ev(
                    "agent.claim_complete",
                    actor="scripted-fixture",
                    payload={"note": "scripted self-claim; completion gate must not honor this"},
                )
                t2 = time.monotonic()
                replay = self.one_pass("replay", upstream, oracle_snap, adaptation, wheelhouse)
                self.timings["replay_s"] = round(time.monotonic() - t2, 1)
            except AdmissionError as exc:
                missing_external.append(str(exc))
            except BudgetExceeded as exc:
                ev("budget.exhausted", actor="harness", payload={"kind": exc.kind, "detail": exc.detail})
                budget_exhausted = f"{exc.kind} ({exc.detail})"

        # ---------------- verification results
        if adaptation_manifest is not None and adaptation is not None:
            recheck_ok, recheck_detail = verify_frozen(adaptation, adaptation_manifest)
        else:
            recheck_ok, recheck_detail = False, "adaptation never frozen"
        def _completion_vr(verifier: str, completion, exit_code, evidence_sha) -> VerificationResult:
            x = completion.extra
            return VerificationResult(
                verifier=verifier,
                passed=completion.ok,
                detail=(
                    f"passed_checks={x['passed_count']}, "
                    f"failed_checks={len(x['failed_nodes'])}, "
                    f"total_checks={x['expected_count']}; {completion.detail}"
                ),
                evidence=[evidence_sha],
                extra={"exit_code": exit_code, **x},
            )

        if first is not None:
            if first.capability_completion is not None:
                cap = _completion_vr(
                    "CapabilityVerifier", first.capability_completion,
                    first.capability_exit, first.capability_stdout_sha,
                )
            else:
                cap = capability_result(
                    exit_code=first.capability_exit,
                    stdout=self.store.artifacts.read(first.capability_stdout_sha).decode("utf-8", errors="replace"),
                    evidence=[first.capability_stdout_sha],
                )
            if first.regression_completion is not None:
                reg = _completion_vr(
                    "HostRegressionVerifier", first.regression_completion,
                    first.regression_exit, first.regression_stdout_sha,
                )
            else:
                reg = regression_result(
                    exit_code=first.regression_exit,
                    stdout=self.store.artifacts.read(first.regression_stdout_sha).decode("utf-8", errors="replace"),
                    evidence=[first.regression_stdout_sha],
                )
        else:
            cap = VerificationResult(verifier="CapabilityVerifier", passed=False, detail="not run")
            reg = VerificationResult(verifier="HostRegressionVerifier", passed=False, detail="not run")

        from repoproof.domain.models import AdaptationManifest as _AM

        pol = policy_result(
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
        rep = None
        if first is not None and replay is not None:
            rep = replay_result(
                first=first.summary(),
                replay=replay.summary(),
                mode=REPLAY_MODE_BASELINE,
                evidence=[first.probe_normalized_sha],
            )
        vr_hashes: dict[str, str] = {}
        for r in (cap, reg, pol) + ((rep,) if rep else ()):
            path = self.store.save_verification(r)
            ref = self.store.store_artifact(
                path.read_bytes(), media_type="application/json",
                producer="verification", name_hint=path.name,
            )
            vr_hashes[r.verifier] = ref.sha256
            ev(
                "verification.result",
                actor=r.verifier,
                payload={"passed": r.passed, "detail": r.detail, "result_sha256": ref.sha256},
                artifact_refs=[ref.sha256],
            )

        gate = completion_gate.decide(
            capability=cap,
            regression=reg,
            policy=pol,
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
        ev(
            "run.end",
            actor="runner",
            payload={"verdict": gate.verdict.value, "timings": self.timings},
        )

        # ---- FINAL verification happens AFTER run.end (no off-by-one)
        chain_ok, n_events, chain_err = verify_chain(self.store.trace_path)
        final_trace_sha = sha256_file(self.store.trace_path)
        run_manifest = {
            "run_id": self.run_id,
            "task_id": self.contract.task_id,
            "task_package_root_hash": self.package.root_hash,
            "contract_sha256": self.contract_sha,
            "source_commit": self.contract.source_repo.resolved_commit,
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
            "mode": "direct-adoption-baseline (scripted, no agent, no LLM)",
            "gate_reasons": gate.reasons,
            "capability": cap.detail,
            "capability_failed_tests": first.capability_failed if first else [],
            "regression": reg.detail,
            "policy": pol.detail,
            "replay": rep.detail if rep else None,
            "trace_chain_error": chain_err,
            "steps_per_pass": {
                "setup": setup_meter.steps_used,
                "baseline": first.steps_used if first else None,
                "replay": replay.steps_used if replay else None,
            },
            "adaptation_files": adaptation_manifest.total_files if adaptation_manifest else None,
        }
        self.store.save_json("report.json", report)
        return report


def _skip_symlink_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        out[str(p.relative_to(root))] = sha256_bytes(p.read_bytes())
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
