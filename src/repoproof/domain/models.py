"""Minimal domain models for the Gate 2 evidence chain.

Design rules:
  * The contract is FROZEN by hashing the exact YAML bytes — any edit
    changes the hash, and the sidecar ``.sha256`` pins it.
  * A verdict is produced ONLY by the completion gate from structured
    verification results; nothing in these models lets an agent (or a
    scripted fixture) self-declare success.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


class Verdict(StrEnum):
    PASS_DIRECT = "PASS_DIRECT"
    PASS_ADAPTED = "PASS_ADAPTED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"
    # Intermediate state only: capability/regression/policy passed but a
    # clean-room replay has not happened. Never a final PASS.
    READY_FOR_REPLAY = "READY_FOR_REPLAY"


class SourceRepo(BaseModel):
    url: str
    revision: str
    resolved_commit: str
    license: str
    distribution: str = "chonkie"
    """Installed python distribution name (portability: probe/env
    admission/wheel selection derive from this, not from hardcoded
    names). Default keeps the frozen v1–v3 contracts valid."""
    import_module: str | None = None
    """Importable module name when it differs from the distribution
    (e.g. distribution python-frontmatter -> module frontmatter).
    Discovered as a real portability gap by the third task's blocked
    baseline; None keeps the prior derivation for older contracts."""

    @property
    def import_name(self) -> str:
        return self.import_module or self.distribution.replace("-", "_")


class TargetProject(BaseModel):
    kind: str = "consumer_fixture"
    path: str
    package: str = "rag_consumer"
    entry_point: str = "chunk_documents"
    """Host package + delegating callable the adapter must serve.
    Defaults keep the frozen chonkie contracts valid. Added after the
    Gate 6 run exposed AGENT_PROMPT_TEMPLATE carrying hardcoded
    chonkie deliverable text into other tasks' prompts
    (HARNESS_PROMPT_CONTAMINATION)."""


class CapabilityParams(BaseModel):
    """Parameters FROZEN from the pinned upstream API — never invented.
    (chonkie@0a6baea: SentenceChunker/RecursiveChunker both accept
    tokenizer + chunk_size; sentence additionally chunk_overlap.)"""

    strategies: list[str] = Field(default_factory=lambda: ["sentence"])
    tokenizer: str = "character"
    chunk_size: int = 2048
    chunk_overlap: int = 0


class Capability(BaseModel):
    statement: str
    output_schema: str
    params: CapabilityParams | None = None
    units_semantics: str | None = None
    coverage_requirements: list[dict] | None = None
    """PUBLIC coverage-ledger requirements ({id, source_field,
    source_quote}); quotes must be verbatim public-contract text.
    None -> the frozen chonkie-task fallback list."""


class Environment(BaseModel):
    os: str = "linux"
    arch: str = "arm64"
    python: str = "3.12"
    cpu_only: bool = True
    network_install: bool = True
    network_test: bool = False


class Constraints(BaseModel):
    forbidden: list[str] = Field(default_factory=list)
    editable_zones: list[str] = Field(default_factory=lambda: ["adaptation"])
    forbidden_install_extras: list[str] = Field(default_factory=list)


class Budgets(BaseModel):
    max_agent_steps: int = 20
    max_wall_time_minutes: int = 30
    max_command_minutes: int = 5
    max_semantic_recoveries: int = 3
    max_same_action: int = 2
    max_patch_files: int = 8
    max_patch_lines: int = 400
    max_input_tokens_total: int = 250_000
    max_output_tokens_total: int = 30_000
    monetary_soft_cap_usd: float = 5.0


class Acceptance(BaseModel):
    capability_command: list[str]
    regression_command: list[str]
    probe_script: str = "direct_chonkie_probe.py"
    """Diagnostic direct-adoption probe under src/repoproof/probes/
    (portability: task-selected, defaulting to the v1–v3 probe)."""


class TaskContract(BaseModel):
    """Frozen adoption contract. The agent (Gate 3) may change its
    SOLUTION, never the problem, the hard constraints, or the oracle.

    Deliberately absent: any ``expected_verdict`` field — the human
    benchmark label is never visible to the runner or a future agent.
    """

    task_id: str
    source_repo: SourceRepo
    target_project: TargetProject
    capability: Capability
    environment: Environment
    constraints: Constraints
    budgets: Budgets
    acceptance: Acceptance

    @classmethod
    def load_frozen(
        cls, contract_path: Path, *, require_sidecar: bool = False
    ) -> tuple[TaskContract, str]:
        """Load a contract and verify it against its ``.sha256`` sidecar.

        Official runs pass ``require_sidecar=True``: a missing sidecar
        is refused outright — an unfrozen contract is not runnable.
        """
        raw = Path(contract_path).read_bytes()
        digest = sha256_bytes(raw)
        sidecar = Path(str(contract_path) + ".sha256")
        if not sidecar.exists():
            if require_sidecar:
                raise ContractTampered(f"contract not frozen: missing sidecar {sidecar.name}")
        else:
            pinned = sidecar.read_text(encoding="utf-8").split()[0].strip()
            if pinned != digest:
                raise ContractTampered(f"contract hash mismatch: file={digest} sidecar={pinned}")
        data = yaml.safe_load(raw.decode("utf-8"))
        return cls.model_validate(data), digest


class ContractTampered(RuntimeError):
    pass


class AdmissionError(RuntimeError):
    """Environment admission failure (e.g. no arm64 install path).

    Policy: never silently switch arch, commit, or contract — record
    evidence, stop, and wait for a user decision.
    """


class RepoManifest(BaseModel):
    url: str
    resolved_commit: str
    license_spdx: str
    license_file_sha256: str | None = None
    git_tree_hash: str | None = None
    worktree_clean: bool | None = None
    content_tree_sha256: str | None = None


class EnvironmentManifest(BaseModel):
    host_os: str
    host_os_version: str
    host_arch: str
    docker_client: str
    docker_server: str
    runtime_provider: str
    image: str
    image_digest: str | None = None
    container_arch: str | None = None
    container_python: str | None = None
    network_install: str = "bridge"
    network_run: str = "none"
    # Gate 2 runs no model. Gate 3 will record the model name and a
    # provider config SUMMARY here — never an API key.
    agent_model: str | None = None
    notes: list[str] = Field(default_factory=list)


class ArtifactRef(BaseModel):
    sha256: str
    size: int
    media_type: str
    producer: str
    name_hint: str = ""
    stored_path: str = ""


class RunEvent(BaseModel):
    seq: int
    ts: str
    event: str
    actor: str
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    prev_sha256: str | None = None


class VerificationResult(BaseModel):
    verifier: str
    passed: bool
    detail: str
    evidence: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class AdaptationManifest(BaseModel):
    """Frozen inventory of the adaptation zone. ``adaptation_present``
    is DERIVED from this (file count + root hash), never a caller bool."""

    files: list[dict[str, Any]] = Field(default_factory=list)
    total_files: int = 0
    total_lines: int = 0
    tree_root_sha256: str = ""
    frozen: bool = False

    @property
    def present(self) -> bool:
        return self.frozen and self.total_files > 0


class TaskPackageManifest(BaseModel):
    """Immutable binding of everything a run depends on. Built ONCE by
    the freeze CLI and committed; the runner only VERIFIES it — never
    regenerates it after start.

    v3 additions (optional so v1/v2 manifests stay valid history):
    test-collection manifest binding, wheelhouse root, image digest and
    environment constraints. ``held_out_fixture_sha256`` refers to the
    runtime-held-out fixture set (not visible to the agent at run
    time)."""

    task_id: str
    contract_sha256: str
    oracle_tree_sha256: str
    public_fixture_sha256: str
    held_out_fixture_sha256: str | None = None
    consumer_fixture_tree_sha256: str
    source_commit: str
    source_git_tree_hash: str
    acceptance_capability_command: list[str]
    acceptance_regression_command: list[str]
    collection_manifest_sha256: str | None = None
    expected_capability_nodes: int | None = None
    expected_regression_nodes: int | None = None
    wheelhouse_root: str | None = None
    wheelhouse_wheels: dict[str, str] | None = None
    image_digest: str | None = None
    environment_constraints: dict[str, str] | None = None
    root_hash: str = ""

    def compute_root_hash(self) -> str:
        import json as _json

        payload = self.model_dump()
        payload.pop("root_hash", None)
        return sha256_bytes(_json.dumps(payload, sort_keys=True, ensure_ascii=False).encode())


class GateResult(BaseModel):
    verdict: Verdict
    reasons: list[str]
    capability_passed: bool | None = None
    regression_passed: bool | None = None
    policy_passed: bool | None = None
    replay_passed: bool | None = None
    adaptation_present: bool = False
