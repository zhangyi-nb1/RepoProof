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
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class FrozenSemanticCommitment(BaseModel):
    """One public behaviour bound before a Product task is frozen."""

    model_config = ConfigDict(extra="forbid")

    commitment_id: str
    public_text: str
    rationale: str
    origin: Literal["MODEL_PROPOSED", "USER_EDITED"]


class FrozenArtifactObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str
    commitment_ids: list[str]
    locator: str
    value_encoding: str


class FrozenArtifactProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    protocol_id: str
    observations: list[FrozenArtifactObservation]


class FrozenIntentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_by: Literal["USER"]
    confirmed_at: str
    semantics_sha256: str


class FrozenDeliveryInputRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["file", "url", "directory", "stdin", "other"]
    location: Literal["local", "remote", "not_applicable"]
    representation: Literal["utf8_text", "binary"] = "utf8_text"
    format_label: str
    role: str


class FrozenDeliveryOutputRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["text_artifact", "binary_artifact", "directory", "service", "other"]
    format_id: str
    format_label: str
    role: str


class FrozenDeliveryRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputs: list[FrozenDeliveryInputRequirement]
    outputs: list[FrozenDeliveryOutputRequirement]
    network: Literal["offline", "required"]
    credentials: Literal["none", "required"]
    lifecycle: Literal["per_invocation", "long_running"]
    runtime: Literal["local_cpu", "gpu", "remote_service"]
    browser: Literal["none", "required"] = "none"
    external_side_effects: Literal[
        "none", "reversible", "irreversible"
    ] = "none"


class FrozenDeliveryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    support_status: Literal["SUPPORTED"]
    origin: Literal["MODEL_PROPOSED", "USER_EDITED"]
    requirements: FrozenDeliveryRequirements
    admitted_output_format_id: str


class FrozenIntentContract(BaseModel):
    """Trace from the exact user goal to the public frozen semantics."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    user_goal: str
    user_goal_sha256: str
    commitments: list[FrozenSemanticCommitment]
    artifact_protocol: FrozenArtifactProtocol | None = None
    delivery: FrozenDeliveryIntent | None = None
    confirmation: FrozenIntentConfirmation


class Capability(BaseModel):
    statement: str
    output_schema: str
    params: CapabilityParams | None = None
    units_semantics: str | None = None
    coverage_requirements: list[dict] | None = None
    """PUBLIC coverage-ledger requirements ({id, source_field,
    source_quote}); quotes must be verbatim public-contract text.
    None -> the frozen chonkie-task fallback list."""
    intent_contract: FrozenIntentContract | None = None
    """Product-mode provenance for task semantics. Historical contracts omit it;
    new traced drafts must bind it before freeze."""


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


class SemanticVerifierSpec(BaseModel):
    """Frozen identity of a task-authored semantic oracle.

    Domain logic belongs to the task file named here. Core only freezes its
    identity and enforces the repository-agnostic execution/evidence protocol.
    """

    model_config = ConfigDict(extra="forbid")

    protocol: Literal[
        "repoproof-semantic-verifier-v1",
        "repoproof-workspace-semantic-verifier-v2",
    ]
    verifier_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,255}$")
    source_file: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required_for_operational_active: Literal[True] = True

    @field_validator("source_file")
    @classmethod
    def _safe_source_file(cls, value: str) -> str:
        candidate = Path(value)
        if (
            candidate.is_absolute()
            or not candidate.parts
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or candidate.suffix != ".py"
        ):
            raise ValueError(
                "semantic verifier source_file must be a safe relative .py path"
            )
        return candidate.as_posix()


class Acceptance(BaseModel):
    capability_command: list[str]
    regression_command: list[str]
    probe_script: str = "direct_chonkie_probe.py"
    semantic_verifier: SemanticVerifierSpec | None = None
    """Diagnostic direct-adoption probe under src/repoproof/probes/
    (portability: task-selected, defaulting to the v1–v3 probe)."""


OutputFieldType = Literal[
    "any", "string", "integer", "number", "boolean", "object", "array", "null"
]
TextValidationProfile = Literal[
    "plain_text_v1",
    "csv_table_v1",
    "tsv_table_v1",
    "markdown_document_v1",
    "safe_self_contained_xhtml_v1",
    "ris_interchange_v1",
]

_TEXT_PROFILE_MEDIA_TYPES: dict[str, set[str]] = {
    "plain_text_v1": {"text/plain"},
    "csv_table_v1": {"text/csv"},
    "tsv_table_v1": {"text/tab-separated-values"},
    "markdown_document_v1": {"text/markdown"},
    "safe_self_contained_xhtml_v1": {"text/html", "application/xhtml+xml"},
    "ris_interchange_v1": {"application/x-research-info-systems"},
}


class ToolOutputContract(BaseModel):
    """Machine-executable stdout contract (RFC-011 M5-a).

    ``root_type`` is canonicalized so drafts may use the human-friendly
    ``json_object`` / ``json_array`` spellings while every consumer sees one
    deterministic representation.  ``required`` intentionally covers only
    top-level JSON fields and primitive JSON types in v2; richer JSON Schema
    semantics would pretend to prove more than this gate actually checks.
    """

    model_config = ConfigDict(extra="forbid")

    media_type: str
    root_type: Literal["text", "json", "object", "array", "json_lines"]
    required: dict[str, OutputFieldType] = Field(default_factory=dict)
    validation_profile: TextValidationProfile | None = None
    """Explicit executable rules for a text artifact.

    ``media_type`` identifies the representation; it must not silently select
    policy or producer-specific behavior.  Historical contracts omit this
    field and retain the legacy root-only text check.  New Product contracts
    compile a versioned profile from the delivery support registry.
    """

    @field_validator("media_type")
    @classmethod
    def _media_type_nonempty(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("media_type must not be empty")
        return value

    @field_validator("root_type", mode="before")
    @classmethod
    def _normalize_root_type(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        return {"json_object": "object", "json_array": "array",
                "jsonl": "json_lines", "ndjson": "json_lines"}.get(
                    normalized, normalized)

    @model_validator(mode="after")
    def _required_only_for_object_values(self) -> ToolOutputContract:
        if self.root_type in {"text", "array"} and self.required:
            raise ValueError(
                f"required fields need object values, not root_type={self.root_type!r}")
        json_media = "json" in self.media_type or "ndjson" in self.media_type
        if self.root_type == "text" and json_media:
            raise ValueError("text root_type cannot declare a JSON media_type")
        if self.root_type != "text" and not json_media:
            raise ValueError("JSON root_type requires a JSON media_type")
        if self.root_type != "text" and self.validation_profile is not None:
            raise ValueError("validation_profile is only valid for text output")
        if self.validation_profile is not None:
            allowed_media = _TEXT_PROFILE_MEDIA_TYPES[self.validation_profile]
            if self.media_type not in allowed_media:
                raise ValueError(
                    "validation_profile does not match the declared media_type"
                )
        if any(not field.strip() for field in self.required):
            raise ValueError("required field names must not be empty")
        return self


# Short public alias for consumers that do not need the ToolSpec context.
OutputContract = ToolOutputContract


class ToolInterfaceIO(BaseModel):
    """LOCAL-TOOL 谱系(RFC-010 [D1]):工具接口的一端。

    kind: file | stdin | stdout | out_file;format 是人读格式名
    (PDF / markdown-table / csv / json …),进 tool.json manifest。"""

    kind: str
    format: str
    contract: ToolOutputContract | None = None
    """v2 machine contract. ``None`` is the frozen v1 compatibility default."""


class ToolInterface(BaseModel):
    """CLI 接口契约 —— 三个消费者的单一事实源(TOOL_CONTRACT_SCHEMA §三):
    骨架 argparse 与 tool.json 的生成、接口契约测试(regression 新所指)
    的生成、交付期 manifest 一致性静态检查。"""

    usage: str
    input: ToolInterfaceIO
    output: ToolInterfaceIO
    exit_codes: dict[str, str]
    """至少含 "0"/"1"/"2";语义冻结:0=成功;1=用户错误(输入不存在/
    格式坏);2=内部错误。充分性由 ContractAdequacyGate T1 执法,
    不在模型层拒——模型层拒会把旧谱系契约的加载路径复杂化。"""


WorkspaceValidationProfile = Literal[
    "binary_v1",
    "csv_v1",
    "html_v1",
    "ics_v1",
    "ipynb_v1",
    "mo_v1",
    "png_v1",
    "pptx_v1",
    "xlsx_v1",
    "json_v1",
    "python_compile_v1",
    "shell_v1",
    "sqlite_v1",
    "svg_xml_v1",
    "text_utf8_v1",
    "toml_v1",
    "tsv_v1",
    "wheel_v1",
    "xml_v1",
    "yaml_v1",
    "zip_v1",
]

_WORKSPACE_LITERAL_PATH_RE = re.compile(r"[A-Za-z0-9._@+\-/]+")


def _validate_workspace_relative_path(value: str, *, pattern: bool) -> str:
    """Validate one portable output path without touching the filesystem.

    Workspace contracts deliberately use a small glob language. ``*`` may
    match within one path segment and ``**`` may appear only as an entire
    segment. Character classes, brace expansion and platform separators are
    excluded so every consumer implements exactly the same matching rules.
    """

    value = value.strip()
    if not value or len(value.encode("utf-8")) > 240:
        raise ValueError("workspace path must contain 1..240 UTF-8 bytes")
    if value.startswith(("/", "\\")) or "\\" in value or "\x00" in value:
        raise ValueError("workspace path must be a relative POSIX path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("workspace path contains an unsafe segment")
    if len(parts) > 12:
        raise ValueError("workspace path exceeds the profile depth limit")
    if any(char in value for char in "?[]{}"):
        raise ValueError("workspace path uses an unsupported glob token")
    if not pattern and "*" in value:
        raise ValueError("literal workspace path cannot contain globs")
    for part in parts:
        if part == "**":
            if not pattern:
                raise ValueError("literal workspace path cannot contain globs")
            continue
        if "**" in part:
            raise ValueError("** is valid only as a complete path segment")
        probe = part.replace("*", "a")
        if _WORKSPACE_LITERAL_PATH_RE.fullmatch(probe) is None:
            raise ValueError("workspace path contains a non-portable character")
    return value


def validate_workspace_relative_path(value: str) -> str:
    """Validate one literal path against the public workspace portability rules."""

    return _validate_workspace_relative_path(value, pattern=False)


class WorkspaceArtifactRule(BaseModel):
    """One public structural rule for a generated workspace file set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path_pattern: str
    role: str = Field(min_length=1, max_length=160)
    media_type: str = Field(min_length=1, max_length=120)
    validation_profile: WorkspaceValidationProfile
    min_count: int = Field(default=1, ge=0, le=512)
    max_count: int = Field(default=1, ge=1, le=512)
    executable: bool = False

    @field_validator("path_pattern")
    @classmethod
    def _safe_pattern(cls, value: str) -> str:
        return _validate_workspace_relative_path(value, pattern=True)

    @field_validator("media_type")
    @classmethod
    def _normalise_media_type(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def _valid_cardinality(self) -> WorkspaceArtifactRule:
        if self.max_count < self.min_count:
            raise ValueError("workspace rule max_count is below min_count")
        return self


class WorkspaceArtifactLimits(BaseModel):
    """Hard profile limits, with conservative M6.2 defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_files: int = Field(default=512, ge=1, le=512)
    max_total_bytes: int = Field(default=256 * 1024 * 1024, ge=1,
                                 le=256 * 1024 * 1024)
    max_file_bytes: int = Field(default=64 * 1024 * 1024, ge=1,
                                le=64 * 1024 * 1024)
    max_depth: int = Field(default=12, ge=1, le=12)
    max_path_bytes: int = Field(default=240, ge=1, le=240)


class WorkspaceArtifactContractV1(BaseModel):
    """Machine-executable contract for one offline directory artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    rules: tuple[WorkspaceArtifactRule, ...] = Field(min_length=1, max_length=128)
    allow_extra_files: bool = False
    entrypoints: tuple[str, ...] = Field(default_factory=tuple, max_length=16)
    runnable: bool = False
    smoke_command: tuple[str, ...] = Field(default_factory=tuple, max_length=32)
    smoke_timeout_seconds: int = Field(default=30, ge=1, le=120)
    require_offline_wheelhouse: bool = False
    runtime_python_entrypoint: str | None = None
    limits: WorkspaceArtifactLimits = Field(default_factory=WorkspaceArtifactLimits)
    # Whole-tree profiles (e.g. static_site_v1: index.html present, internal
    # links closed); per-file profiles cannot see across files.  Optional and
    # absent from every earlier frozen contract.
    directory_profiles: tuple[str, ...] = Field(default_factory=tuple, max_length=4)

    @field_validator("directory_profiles")
    @classmethod
    def _known_directory_profiles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        from repoproof.adoption.delivery.portable_workspace_runtime import (
            KNOWN_DIRECTORY_PROFILES,
        )

        for item in value:
            if item not in KNOWN_DIRECTORY_PROFILES:
                raise ValueError(f"unknown directory profile: {item!r}")
        if len(value) != len(set(value)):
            raise ValueError("directory profiles must be unique")
        return value

    @field_validator("entrypoints")
    @classmethod
    def _safe_entrypoints(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(
            _validate_workspace_relative_path(item, pattern=False) for item in value
        )
        if len(checked) != len(set(checked)):
            raise ValueError("workspace entrypoints must be unique")
        return checked

    @field_validator("runtime_python_entrypoint")
    @classmethod
    def _safe_runtime_python_entrypoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_workspace_relative_path(value, pattern=False)

    @field_validator("smoke_command")
    @classmethod
    def _safe_smoke_command(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for argument in value:
            if not argument or len(argument.encode("utf-8")) > 256 or "\0" in argument:
                raise ValueError("workspace smoke argv contains an unsafe argument")
        return value

    @model_validator(mode="after")
    def _coherent_workspace_contract(self) -> WorkspaceArtifactContractV1:
        patterns = [rule.path_pattern for rule in self.rules]
        if len(patterns) != len(set(patterns)):
            raise ValueError("workspace path rules must be unique")
        literal_rules = [rule for rule in self.rules if "*" not in rule.path_pattern]
        if any(rule.min_count > 1 for rule in literal_rules):
            raise ValueError("literal workspace rule cannot require multiple files")
        required_literals = {
            rule.path_pattern for rule in literal_rules if rule.min_count > 0
        }
        if len(required_literals) > self.limits.max_files:
            raise ValueError("required literal files exceed workspace max_files")
        for path in required_literals:
            if len(Path(path).parts) > self.limits.max_depth:
                raise ValueError("required literal path exceeds workspace max_depth")
            if len(path.encode("utf-8")) > self.limits.max_path_bytes:
                raise ValueError("required literal path exceeds workspace max_path_bytes")
        if self.runnable and not self.entrypoints:
            raise ValueError("runnable workspace requires an entrypoint")
        if self.runnable and not self.smoke_command:
            raise ValueError("runnable workspace requires a frozen smoke command")
        if not self.runnable and self.smoke_command:
            raise ValueError("non-runnable workspace cannot declare a smoke command")
        if self.smoke_command:
            command = self.smoke_command[0]
            expected_commands = {f"./{entrypoint}" for entrypoint in self.entrypoints}
            if command not in expected_commands:
                raise ValueError(
                    "workspace smoke command must invoke a declared entrypoint"
                )
        if self.require_offline_wheelhouse and not self.runnable:
            raise ValueError("offline wheelhouse is meaningful only for runnable workspaces")
        if self.require_offline_wheelhouse:
            closure_required_literals = {
                "requirements.lock.txt",
                "THIRD_PARTY_NOTICES.md",
            }
            literal_patterns = {item for item in patterns if "*" not in item}
            if not closure_required_literals.issubset(literal_patterns):
                raise ValueError(
                    "offline runnable workspace must contract-bind lock and notices"
                )
            if not any(item.startswith("vendor/wheels/") for item in patterns):
                raise ValueError("offline runnable workspace must contract-bind wheelhouse")
            if self.runtime_python_entrypoint is None:
                raise ValueError(
                    "offline runnable workspace requires a Python application entrypoint"
                )
            if self.runtime_python_entrypoint not in required_literals:
                raise ValueError(
                    "offline Python application entrypoint must be a required literal"
                )
            if "run.sh" not in required_literals or "run.sh" not in self.entrypoints:
                raise ValueError(
                    "offline runnable workspace must use the Harness-owned run.sh launcher"
                )
            if not self.smoke_command or self.smoke_command[0] != "./run.sh":
                raise ValueError(
                    "offline runnable workspace smoke must use the sealed launcher"
                )
        elif self.runtime_python_entrypoint is not None:
            raise ValueError(
                "runtime Python entrypoint requires an offline wheelhouse closure"
            )
        return self


class ArtifactManifestEntryV1(BaseModel):
    """One immutable regular-file identity in a generated workspace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    size: int = Field(ge=0)
    mode: int = Field(ge=0, le=0o777)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def _safe_path(cls, value: str) -> str:
        return validate_workspace_relative_path(value)


class ArtifactManifestV1(BaseModel):
    """Harness-authored directory identity; never stored in Agent output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    artifact_kind: Literal["directory"] = "directory"
    file_count: int = Field(ge=0, le=512)
    total_bytes: int = Field(ge=0, le=256 * 1024 * 1024)
    tree_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[ArtifactManifestEntryV1, ...] = Field(max_length=512)

    @model_validator(mode="after")
    def _manifest_totals_match(self) -> ArtifactManifestV1:
        if self.file_count != len(self.entries):
            raise ValueError("artifact manifest file_count mismatch")
        if self.total_bytes != sum(item.size for item in self.entries):
            raise ValueError("artifact manifest total_bytes mismatch")
        paths = [item.path for item in self.entries]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("artifact manifest paths must be unique and sorted")
        return self


class ToolSpec(BaseModel):
    """LOCAL-TOOL 谱系唯一新增分节。name = CLI 命令名,必须与
    target_project.entry_point 一致(adequacy T2 执法)。"""

    schema_version: int = Field(default=1, ge=1)
    """1 = historical semantics; 2 = output-contract gates; 3 = frozen
    task-authored semantic verification required before operational ACTIVE;
    4 = offline workspace-bundle delivery with a directory contract."""
    name: str = Field(
        pattern=r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
    )
    summary: str
    interface: ToolInterface
    delivery_profile_id: str | None = None
    workspace_contract: WorkspaceArtifactContractV1 | None = None

    @model_validator(mode="after")
    def _versioned_delivery_shape(self) -> ToolSpec:
        if self.schema_version < 4:
            if self.delivery_profile_id is not None or self.workspace_contract is not None:
                raise ValueError("ToolSpec v1-v3 cannot declare workspace delivery")
            return self
        if self.delivery_profile_id != "workspace_bundle_v1":
            raise ValueError("ToolSpec v4 requires workspace_bundle_v1")
        if self.workspace_contract is None:
            raise ValueError("ToolSpec v4 requires workspace_contract")
        if self.interface.input.kind not in {"file", "directory"}:
            raise ValueError("ToolSpec v4 input must be one local path")
        if self.interface.output.kind != "directory":
            raise ValueError("ToolSpec v4 output must be a directory")
        if self.interface.output.contract is not None:
            raise ValueError("ToolSpec v4 uses workspace_contract, not stdout contract")
        if "--out-dir" not in self.interface.usage:
            raise ValueError("ToolSpec v4 usage must expose --out-dir")
        return self


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
    # 上游交付拓扑(A1)。**缺省是 in-process,即既有全部发次的行为** ——
    # 新增能力不得把老题悄悄换成另一道题。
    runtime_profile: str = "rt-inprocess-v1"
    # ---- 任务谱系(2026-08-14 用户指令:明确分叉,不要续版本号)----
    #
    # 为什么不叫 "T3v7":`T3v6 → T3v7` 读起来像同一个任务的第七版,而**能力
    # 定义已经变了**:
    #
    #   T3-INPROC   测 dependency integration + API understanding
    #               + package/runtime setup + host adaptation
    #   T3-SIDECAR  测 RPC protocol understanding + adapter implementation
    #               + upstream semantic use
    #
    # 两者的成绩**永不混合**。谱系写在这里,论文/README/实验表直接引用,
    # 不必去解读 task_id 里的版本尾巴。
    #
    # 注意 `task_id` 一律不动 —— 台账 92 行都引用着它,改名等于伪造历史。
    # 谱系是**新增的旁注**,不是重命名。
    # 命名说明:用户方案里管这个叫 `task_shape`。本仓 **`task_shape` 这个名字
    # 已被难度画像占用**(HostContract.task_shape 是个 dict:files_and_modules /
    # integration_points / … / total),直接复用会在 YAML 里静默撞键 —— 后者
    # 覆盖前者,而且不报错(实测:字符串被 165 行那个 dict 悄悄吃掉)。
    # 所以改叫 `adoption_shape`,含义与用户方案一致。
    task_family: str = ""            # 例:T3-INPROC / T3-SIDECAR / LOCAL-TOOL;空 = 未归族
    adoption_shape: str = "DEPENDENCY_INTEGRATION"
    # LOCAL-TOOL 谱系(RFC-010,2026-08-23):工具接口契约。None = 旧谱系,
    # 一切照旧 —— 加字段带默认值,12 份冻结历史契约与其 sha256 全部不动。
    tool: ToolSpec | None = None
    constraints: Constraints
    budgets: Budgets
    acceptance: Acceptance
    requirement_spec_file: str | None = None
    """Contract-relative path of the structured RequirementSpec (v2+
    tasks). When set, prompt rendering and the ContractAdequacyGate are
    requirement-driven; older contracts stay valid without it."""

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
    requirement_spec_sha256: str | None = None
    prompt_manifest_sha256: str | None = None
    public_tests_tree_sha256: str | None = None
    public_examples_sha256: str | None = None
    responsibility_matrix: dict[str, list[str]] | None = None
    controls_summary: dict[str, str] | None = None
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
