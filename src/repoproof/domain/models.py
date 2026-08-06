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


class TargetProject(BaseModel):
    kind: str = "consumer_fixture"
    path: str


class Capability(BaseModel):
    statement: str
    output_schema: str


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
    def load_frozen(cls, contract_path: Path) -> tuple[TaskContract, str]:
        """Load a contract and verify it against its ``.sha256`` sidecar.

        Returns (contract, contract_sha256). Raises ``ContractTampered``
        when the sidecar exists and does not match the file bytes.
        """
        raw = Path(contract_path).read_bytes()
        digest = sha256_bytes(raw)
        sidecar = Path(str(contract_path) + ".sha256")
        if sidecar.exists():
            pinned = sidecar.read_text(encoding="utf-8").split()[0].strip()
            if pinned != digest:
                raise ContractTampered(
                    f"contract hash mismatch: file={digest} sidecar={pinned}"
                )
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
    tree_sha256: str | None = None


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


class GateResult(BaseModel):
    verdict: Verdict
    reasons: list[str]
    capability_passed: bool | None = None
    regression_passed: bool | None = None
    policy_passed: bool | None = None
    replay_passed: bool | None = None
    adaptation_present: bool = False
