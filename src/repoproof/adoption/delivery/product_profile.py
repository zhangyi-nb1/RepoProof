"""Machine-executable Product Mode delivery support profile.

The profile is the single source of truth for *shape*, not task semantics.  It
is consumed before drafting user-facing advice, while normalizing an LLM draft,
and again before a draft bundle is mutated.  This keeps repository-specific
words out of the admission mechanism: a task either fits the declared delivery
topology or it does not.

``cli_v2`` currently means one local file per invocation and one deterministic
UTF-8 stdout artifact.  The final CLI may additionally persist the same bytes
through ``--out``; that is not a second output contract.  Binary outputs,
directories, services, credentials, and runtime network access require a future
profile instead of exceptions to this one.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from repoproof.domain.models import (
    OutputFieldType,
    TextValidationProfile,
    ToolOutputContract,
)

CLI_V2_PROFILE_ID = "cli_v2"
WORKSPACE_BUNDLE_PROFILE_ID = "workspace_bundle_v1"
DELIVERY_SUPPORTED = "SUPPORTED"
DELIVERY_UNSUPPORTED = "UNSUPPORTED"


class OutputArtifactSpec(BaseModel):
    """One output choice supported by a delivery profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: str
    display_name: str
    format_name: str
    extension: str
    media_type: str
    root_type: Literal["text", "json", "object", "array", "json_lines"]
    validation_profile: TextValidationProfile | None = None
    aliases: tuple[str, ...] = ()
    allows_required_fields: bool = False


class DeliveryInputRequirement(BaseModel):
    """One input the proposed workflow says it needs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["file", "url", "directory", "stdin", "other"]
    location: Literal["local", "remote", "not_applicable"]
    representation: Literal["utf8_text", "binary"] = Field(
        default="utf8_text",
        description=(
            "Choose utf8_text when the complete input bytes are a meaningful "
            "Unicode text serialization that can be authored losslessly in a "
            "text editor, even when the input is delivered as a file. Choose "
            "binary only when the original bytes are not a meaningful UTF-8 "
            "text representation and an actual file is required. The file "
            "input kind alone never implies binary."
        ),
    )
    """How sample bytes may be authored and previewed.

    This is a typed property of the requested input, not something inferred
    from a filename or format label.  Historical records default to UTF-8;
    new model advice is required by the generated response schema to state it.
    """
    format_label: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=240)


class DeliveryOutputRequirement(BaseModel):
    """One distinct user-facing output requested by the proposed workflow."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["text_artifact", "binary_artifact", "directory", "service", "other"]
    format_id: str = Field(min_length=1, max_length=80)
    format_label: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=240)


class DeliveryRequirements(BaseModel):
    """Model-described delivery needs, before support admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inputs: tuple[DeliveryInputRequirement, ...] = Field(min_length=1, max_length=4)
    outputs: tuple[DeliveryOutputRequirement, ...] = Field(min_length=1, max_length=4)
    network: Literal["offline", "required"]
    credentials: Literal["none", "required"]
    lifecycle: Literal["per_invocation", "long_running"]
    runtime: Literal["local_cpu", "gpu", "remote_service"]
    browser: Literal["none", "required"] = "none"
    external_side_effects: Literal["none", "reversible", "irreversible"] = "none"


class ProductDeliveryProfile(BaseModel):
    """Immutable topology and artifact registry for Product Mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = 1
    profile_id: str
    input_kind: Literal["file", "file_or_directory"] = "file"
    input_cardinality: Literal[1] = 1
    output_kind: Literal["stdout", "directory"] = "stdout"
    output_cardinality: Literal[1] = 1
    output_transport: Literal["utf8_text", "filesystem"] = "utf8_text"
    network: Literal["offline"] = "offline"
    credentials: Literal["none"] = "none"
    lifecycle: Literal["per_invocation"] = "per_invocation"
    runtime: Literal["local_cpu"] = "local_cpu"
    browser: Literal["none"] = "none"
    external_side_effects: Literal["none"] = "none"
    output_artifacts: tuple[OutputArtifactSpec, ...] = Field(min_length=1)

    def artifact(self, format_id: str) -> OutputArtifactSpec:
        for artifact in self.output_artifacts:
            if artifact.format_id == format_id:
                return artifact
        raise ProductProfileError("OUTPUT_FORMAT_NOT_IN_PROFILE")

    def artifact_for_label(self, format_label: str) -> OutputArtifactSpec:
        """Resolve UI/user spelling from registry data, not inference code."""

        normalized = _normalize_artifact_label(format_label)
        matches = [
            artifact
            for artifact in self.output_artifacts
            if normalized in {
                _normalize_artifact_label(value)
                for value in (
                    artifact.format_id,
                    artifact.format_name,
                    artifact.display_name,
                    *artifact.aliases,
                )
            }
        ]
        if len(matches) != 1:
            raise ProductProfileError("OUTPUT_FORMAT_NOT_IN_PROFILE")
        return matches[0]

    def format_ids(self) -> tuple[str, ...]:
        return tuple(artifact.format_id for artifact in self.output_artifacts)

    def admit_requirements(
        self,
        raw: DeliveryRequirements | dict,
    ) -> tuple[DeliveryRequirements, OutputArtifactSpec]:
        """Admit a proposed workflow by topology, never by task vocabulary."""

        try:
            requirements = (
                raw
                if isinstance(raw, DeliveryRequirements)
                else DeliveryRequirements.model_validate(raw)
            )
        except ValueError as exc:
            raise ProductProfileError("DELIVERY_REQUIREMENTS_INVALID") from exc
        if len(requirements.inputs) != self.input_cardinality:
            raise ProductProfileError("INPUT_CARDINALITY_MISMATCH")
        input_requirement = requirements.inputs[0]
        allowed_input_kinds = (
            {"file", "directory"}
            if self.input_kind == "file_or_directory"
            else {"file"}
        )
        if (
            input_requirement.kind not in allowed_input_kinds
            or input_requirement.location != "local"
        ):
            raise ProductProfileError("INPUT_SOURCE_MISMATCH")
        if len(requirements.outputs) != self.output_cardinality:
            raise ProductProfileError("OUTPUT_CARDINALITY_MISMATCH")
        output_requirement = requirements.outputs[0]
        expected_output_kind = (
            "directory" if self.output_kind == "directory" else "text_artifact"
        )
        if output_requirement.kind != expected_output_kind:
            raise ProductProfileError("OUTPUT_TRANSPORT_MISMATCH")
        artifact = self.artifact(output_requirement.format_id)
        if requirements.network != self.network:
            raise ProductProfileError("NETWORK_MODE_MISMATCH")
        if requirements.credentials != self.credentials:
            raise ProductProfileError("CREDENTIAL_MODE_MISMATCH")
        if requirements.lifecycle != self.lifecycle:
            raise ProductProfileError("LIFECYCLE_MISMATCH")
        if requirements.runtime != self.runtime:
            raise ProductProfileError("RUNTIME_MODE_MISMATCH")
        if requirements.browser != self.browser:
            raise ProductProfileError("BROWSER_MODE_MISMATCH")
        if requirements.external_side_effects != self.external_side_effects:
            raise ProductProfileError("EXTERNAL_SIDE_EFFECT_MISMATCH")
        return requirements, artifact

    def prompt_context(self) -> dict:
        """Public, deterministic context safe to send to a drafting model."""

        from repoproof.adoption.assembly.output_contract import public_validation_profile_spec

        if self.output_kind == "directory":
            return {
                "schema_version": self.schema_version,
                "profile_id": self.profile_id,
                "input": {
                    "kind": "file_or_directory",
                    "cardinality": self.input_cardinality,
                    "supported_representations": ["utf8_text", "binary"],
                },
                "output": {
                    "kind": "directory",
                    "cardinality": self.output_cardinality,
                    "transport": self.output_transport,
                    "workspace_contract_required": True,
                    "allowed_artifacts": [{
                        "format_id": "workspace_bundle",
                        "display_name": "离线多文件工作区",
                        "extension": "",
                        "media_type": "application/vnd.repoproof.workspace",
                    }],
                },
                "network": self.network,
                "credentials": self.credentials,
                "lifecycle": self.lifecycle,
                "runtime": self.runtime,
                "browser": self.browser,
                "external_side_effects": self.external_side_effects,
            }

        return {
            "schema_version": self.schema_version,
            "profile_id": self.profile_id,
            "input": {
                "kind": self.input_kind,
                "cardinality": self.input_cardinality,
                "supported_representations": ["utf8_text", "binary"],
            },
            "output": {
                "kind": self.output_kind,
                "cardinality": self.output_cardinality,
                "transport": self.output_transport,
                "allowed_artifacts": [
                    {
                        "format_id": artifact.format_id,
                        "display_name": artifact.display_name,
                        "extension": artifact.extension,
                        "media_type": artifact.media_type,
                        "root_type": artifact.root_type,
                        "allows_required_fields": artifact.allows_required_fields,
                        "validation_profile": artifact.validation_profile,
                        "validation_profile_spec": (
                            public_validation_profile_spec(
                                artifact.validation_profile
                            )
                            if artifact.root_type == "text"
                            else None
                        ),
                    }
                    for artifact in self.output_artifacts
                ],
            },
            "network": self.network,
            "credentials": self.credentials,
            "lifecycle": self.lifecycle,
            "runtime": self.runtime,
            "browser": self.browser,
            "external_side_effects": self.external_side_effects,
        }

    def contract_for(
        self,
        format_id: str,
        *,
        required_fields: list[dict[str, str]] | None = None,
    ) -> tuple[str, ToolOutputContract]:
        """Compile a model's format choice into the canonical Core contract."""

        if self.output_kind == "directory":
            raise ProductProfileError("WORKSPACE_CONTRACT_REQUIRED")
        artifact = self.artifact(format_id)
        required: dict[str, OutputFieldType] = {}
        for field in required_fields or []:
            name = str(field.get("name") or "").strip()
            field_type = str(field.get("type") or "").strip()
            if not name or field_type not in {
                "any", "string", "integer", "number", "boolean",
                "object", "array", "null",
            }:
                raise ProductProfileError("OUTPUT_REQUIRED_FIELD_INVALID")
            if name in required:
                raise ProductProfileError("OUTPUT_REQUIRED_FIELD_DUPLICATE")
            required[name] = cast(OutputFieldType, field_type)
        if required and not artifact.allows_required_fields:
            raise ProductProfileError("OUTPUT_REQUIRED_FIELDS_NOT_SUPPORTED")
        contract = ToolOutputContract(
            media_type=artifact.media_type,
            root_type=artifact.root_type,
            required=required,
            validation_profile=artifact.validation_profile,
        )
        return artifact.format_name, contract

    def contract_for_label(self, format_label: str) -> tuple[str, ToolOutputContract]:
        artifact = self.artifact_for_label(format_label)
        return self.contract_for(artifact.format_id)

    def assert_compiled_output(
        self,
        *,
        format_id: str,
        format_name: str,
        contract: ToolOutputContract | dict,
    ) -> ToolOutputContract:
        """Re-check the compiled artifact without trusting drafter provenance."""

        if self.output_kind == "directory":
            raise ProductProfileError("WORKSPACE_CONTRACT_REQUIRED")
        artifact = self.artifact(format_id)
        try:
            parsed = (
                contract
                if isinstance(contract, ToolOutputContract)
                else ToolOutputContract.model_validate(contract)
            )
        except ValueError as exc:
            raise ProductProfileError("OUTPUT_CONTRACT_INVALID") from exc
        if format_name != artifact.format_name:
            raise ProductProfileError("OUTPUT_FORMAT_PROJECTION_MISMATCH")
        if (
            parsed.media_type != artifact.media_type
            or parsed.root_type != artifact.root_type
            or parsed.validation_profile != artifact.validation_profile
        ):
            raise ProductProfileError("OUTPUT_CONTRACT_PROFILE_MISMATCH")
        if parsed.required and not artifact.allows_required_fields:
            raise ProductProfileError("OUTPUT_REQUIRED_FIELDS_NOT_SUPPORTED")
        return parsed

    def resolve_compiled_output(
        self,
        *,
        format_name: str,
        contract: ToolOutputContract | dict,
    ) -> OutputArtifactSpec:
        """Resolve an editable final draft back to one profile artifact."""

        if self.output_kind == "directory":
            raise ProductProfileError("WORKSPACE_CONTRACT_REQUIRED")
        try:
            parsed = (
                contract
                if isinstance(contract, ToolOutputContract)
                else ToolOutputContract.model_validate(contract)
            )
        except ValueError as exc:
            raise ProductProfileError("OUTPUT_CONTRACT_INVALID") from exc
        matches = [
            artifact
            for artifact in self.output_artifacts
            if artifact.format_name == format_name
            and artifact.media_type == parsed.media_type
            and artifact.root_type == parsed.root_type
            and artifact.validation_profile == parsed.validation_profile
            and (artifact.allows_required_fields or not parsed.required)
        ]
        if len(matches) != 1:
            raise ProductProfileError("OUTPUT_NOT_COMPILED_FROM_PROFILE")
        return matches[0]

    def assert_interface(self, interface: dict) -> OutputArtifactSpec:
        """Validate the complete editable interface against this profile."""

        input_spec = interface.get("input") or {}
        output_spec = interface.get("output") or {}
        input_kind = input_spec.get("kind")
        if self.input_kind == "file_or_directory":
            input_ok = input_kind in {"file", "directory"}
        else:
            input_ok = input_kind == self.input_kind
        if not input_ok:
            raise ProductProfileError("INPUT_TOPOLOGY_MISMATCH")
        if output_spec.get("kind") != self.output_kind:
            raise ProductProfileError("OUTPUT_TOPOLOGY_MISMATCH")
        if self.output_kind == "directory":
            if output_spec.get("contract") is not None:
                raise ProductProfileError("WORKSPACE_STDOUT_CONTRACT_FORBIDDEN")
            return self.artifact("workspace_bundle")
        return self.resolve_compiled_output(
            format_name=str(output_spec.get("format") or ""),
            contract=output_spec.get("contract") or {},
        )


class ProductProfileError(ValueError):
    """Stable reason code for a delivery-shape mismatch."""


def _normalize_artifact_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def delivery_requirements_json_schema() -> dict:
    """Return a self-contained schema generated from the Core domain model."""

    schema = DeliveryRequirements.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(value):
        if isinstance(value, list):
            return [inline(item) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.rsplit("/", 1)[-1]
            if name not in definitions:
                raise ProductProfileError("DELIVERY_SCHEMA_REFERENCE_UNKNOWN")
            merged = deepcopy(definitions[name])
            merged.update({key: item for key, item in value.items() if key != "$ref"})
            return inline(merged)
        return {key: inline(item) for key, item in value.items()}

    result = inline(schema)
    # Compatibility models accept historical rows that predate the typed input
    # representation.  New LLM advice must nevertheless state it explicitly so
    # the example workflow never guesses from words such as a suffix or MIME.
    input_items = result["properties"]["inputs"]["items"]
    required = list(input_items.get("required") or [])
    if "representation" not in required:
        required.append("representation")
    input_items["required"] = required
    return result


_CLI_V2 = ProductDeliveryProfile(
    profile_id=CLI_V2_PROFILE_ID,
    output_artifacts=(
        OutputArtifactSpec(
            format_id="plain_text",
            display_name="UTF-8 文本文件",
            format_name="plain text",
            extension=".txt",
            media_type="text/plain",
            root_type="text",
            validation_profile="plain_text_v1",
            aliases=("txt", "text", "plain text", "UTF-8 text", "UTF8 text"),
        ),
        OutputArtifactSpec(
            format_id="csv",
            display_name="CSV 表格",
            format_name="CSV",
            extension=".csv",
            media_type="text/csv",
            root_type="text",
            validation_profile="csv_table_v1",
            aliases=("CSV table",),
        ),
        OutputArtifactSpec(
            format_id="tsv",
            display_name="TSV 表格",
            format_name="TSV",
            extension=".tsv",
            media_type="text/tab-separated-values",
            root_type="text",
            validation_profile="tsv_table_v1",
            aliases=("TSV table", "tab separated values"),
        ),
        OutputArtifactSpec(
            format_id="markdown",
            display_name="Markdown 文档",
            format_name="Markdown",
            extension=".md",
            media_type="text/markdown",
            root_type="text",
            validation_profile="markdown_document_v1",
            aliases=("MD", "Markdown document", "Markdown report", "markdown-table"),
        ),
        OutputArtifactSpec(
            format_id="html",
            display_name="自包含 HTML 报告",
            format_name="HTML",
            extension=".html",
            media_type="text/html",
            root_type="text",
            validation_profile="safe_self_contained_xhtml_v1",
            aliases=("HTML report",),
        ),
        OutputArtifactSpec(
            format_id="xhtml",
            display_name="自包含 XHTML 报告",
            format_name="XHTML",
            extension=".xhtml",
            media_type="application/xhtml+xml",
            root_type="text",
            validation_profile="safe_self_contained_xhtml_v1",
            aliases=("XHTML report",),
        ),
        OutputArtifactSpec(
            format_id="ris",
            display_name="RIS 文献文件",
            format_name="RIS",
            extension=".ris",
            media_type="application/x-research-info-systems",
            root_type="text",
            validation_profile="ris_interchange_v1",
            aliases=(
                "Research Info System",
                "Research Info Systems",
                "Research Information System",
                "Research Information Systems",
            ),
        ),
        OutputArtifactSpec(
            format_id="json",
            display_name="JSON 文件",
            format_name="JSON",
            extension=".json",
            media_type="application/json",
            root_type="json",
            aliases=("arbitrary JSON",),
        ),
        OutputArtifactSpec(
            format_id="json_object",
            display_name="JSON 对象文件",
            format_name="JSON object",
            extension=".json",
            media_type="application/json",
            root_type="object",
            aliases=("JSON object",),
            allows_required_fields=True,
        ),
        OutputArtifactSpec(
            format_id="json_array",
            display_name="JSON 数组文件",
            format_name="JSON array",
            extension=".json",
            media_type="application/json",
            root_type="array",
            aliases=("JSON array", "JSON list"),
        ),
        OutputArtifactSpec(
            format_id="json_lines",
            display_name="JSON Lines 文件",
            format_name="JSON Lines",
            extension=".jsonl",
            media_type="application/x-ndjson",
            root_type="json_lines",
            aliases=("JSONL", "NDJSON"),
        ),
    ),
)

_WORKSPACE_BUNDLE_V1 = ProductDeliveryProfile(
    profile_id=WORKSPACE_BUNDLE_PROFILE_ID,
    input_kind="file_or_directory",
    output_kind="directory",
    output_transport="filesystem",
    output_artifacts=(
        OutputArtifactSpec(
            format_id="workspace_bundle",
            display_name="离线多文件工作区",
            format_name="workspace directory",
            extension="",
            media_type="application/vnd.repoproof.workspace",
            root_type="text",
            aliases=("workspace", "directory", "project folder"),
        ),
    ),
)


def product_delivery_profile(profile_id: str = CLI_V2_PROFILE_ID) -> ProductDeliveryProfile:
    profiles = {
        CLI_V2_PROFILE_ID: _CLI_V2,
        WORKSPACE_BUNDLE_PROFILE_ID: _WORKSPACE_BUNDLE_V1,
    }
    try:
        return profiles[profile_id]
    except KeyError as exc:
        raise ProductProfileError("DELIVERY_PROFILE_UNKNOWN") from exc


def select_product_delivery_profile(
    raw: DeliveryRequirements | dict,
) -> ProductDeliveryProfile:
    """Select one profile from typed topology, never repository/task words."""

    try:
        requirements = (
            raw
            if isinstance(raw, DeliveryRequirements)
            else DeliveryRequirements.model_validate(raw)
        )
    except ValueError as exc:
        raise ProductProfileError("DELIVERY_REQUIREMENTS_INVALID") from exc
    output_kinds = {item.kind for item in requirements.outputs}
    output_formats = {item.format_id for item in requirements.outputs}
    if output_kinds == {"directory"} or "workspace_bundle" in output_formats:
        selected = _WORKSPACE_BUNDLE_V1
    else:
        selected = _CLI_V2
    selected.admit_requirements(requirements)
    return selected


def project_requirement_brief(raw: dict, profile: ProductDeliveryProfile | None = None) -> dict:
    """Compile structured model advice into the only adoptable prose.

    The model does not author topology-bearing prose.  Cardinality, transport,
    network, lifecycle, and the output artifact all come from the profile.
    """

    projected = assess_requirement_brief(raw, profile)
    if projected["support_status"] != DELIVERY_SUPPORTED:
        reasons = projected.get("support_reason_codes") or ["DELIVERY_UNSUPPORTED"]
        raise ProductProfileError(str(reasons[0]))
    return projected


def assess_requirement_brief(
    raw: dict,
    profile: ProductDeliveryProfile | None = None,
) -> dict:
    """Classify a model proposal without asking the model to make it fit.

    A proposal and an admission decision are different facts.  The former may
    truthfully describe a topology Product Mode cannot deliver; the latter is a
    deterministic projection of the current profile.  Unsupported proposals
    remain visible, but never receive adoptable text.
    """

    try:
        selected = profile or select_product_delivery_profile(
            raw.get("delivery_requirements") or {}
        )
    except ProductProfileError as exc:
        return {
            **raw,
            "text": None,
            "delivery_shape": None,
            "support_status": DELIVERY_UNSUPPORTED,
            "support_reason_codes": [str(exc)],
        }
    title = str(raw.get("title") or "").strip()
    scenario = str(raw.get("scenario") or "").strip().rstrip("。.;；")
    boundary = str(raw.get("boundary") or "").strip().rstrip("。.;；")
    if not title or not scenario or not boundary:
        raise ProductProfileError("BRIEF_FIELD_EMPTY")
    try:
        requirements, artifact = selected.admit_requirements(
            raw.get("delivery_requirements") or {}
        )
    except ProductProfileError as exc:
        return {
            **raw,
            "text": None,
            "delivery_shape": None,
            "support_status": DELIVERY_UNSUPPORTED,
            "support_reason_codes": [str(exc)],
        }
    input_format = requirements.inputs[0].format_label.strip()
    if not input_format:
        raise ProductProfileError("BRIEF_FIELD_EMPTY")
    input_label = input_format if input_format.lower().endswith(("文件", "file")) else f"{input_format} 文件"
    if selected.output_kind == "directory":
        text = (
            f"{scenario}。每次输入一个本地{input_format}文件或资料目录，"
            "输出一套离线多文件工作区；每次调用独立运行。"
            f"主要边界是{boundary}。"
        )
    else:
        text = (
            f"{scenario}。每次输入一份 {input_label}，输出一份"
            f"{artifact.display_name}（{artifact.extension}）；完全离线、每次调用独立运行。"
            f"主要边界是{boundary}。"
        )
    return {
        **raw,
        "delivery_requirements": requirements.model_dump(mode="json"),
        "text": text,
        "delivery_shape": {
            "profile_id": selected.profile_id,
            "input_kind": selected.input_kind,
            "input_cardinality": selected.input_cardinality,
            "input_representation": requirements.inputs[0].representation,
            "output_kind": selected.output_kind,
            "output_cardinality": selected.output_cardinality,
            "output_format_id": artifact.format_id,
            "output_extension": artifact.extension,
            "output_media_type": artifact.media_type,
            "network": selected.network,
            "lifecycle": selected.lifecycle,
        },
        "support_status": DELIVERY_SUPPORTED,
        "support_reason_codes": [],
    }
