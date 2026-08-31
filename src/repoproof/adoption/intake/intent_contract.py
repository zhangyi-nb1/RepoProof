"""Trace a vague user goal into public, user-confirmed task semantics.

This module closes a boundary that delivery-profile admission cannot close.
The delivery profile answers *whether the requested topology is supported*;
it cannot decide what task-specific behaviour the user meant.  Conversely,
held-out verification may hide inputs, but it must never introduce a rule that
was absent from the public contract.

The drafting model therefore proposes small, public semantic commitments.  Core
compiles the capability statement from those commitments and the exact user
goal.  A human confirmation binds the semantic payload by SHA-256.  Any later
edit invalidates that confirmation and freeze fails closed.

There are deliberately no repository names, file-format keywords, or
task-specific policies in this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from repoproof.adoption.delivery.product_profile import (
    DeliveryRequirements,
    ProductProfileError,
    product_delivery_profile,
)

INTENT_CONTRACT_SCHEMA_VERSION = 1
_COMMITMENT_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_OBSERVATION_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


class SemanticCommitmentV1(BaseModel):
    """One normative behaviour that will be visible before freeze."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    commitment_id: str = Field(min_length=1, max_length=64)
    public_text: str = Field(min_length=1, max_length=800)
    rationale: str = Field(min_length=1, max_length=800)
    origin: Literal["MODEL_PROPOSED", "USER_EDITED"] = "MODEL_PROPOSED"

    @field_validator("commitment_id")
    @classmethod
    def _valid_commitment_id(cls, value: str) -> str:
        value = value.strip().lower()
        if _COMMITMENT_ID_RE.fullmatch(value) is None:
            raise ValueError("commitment_id must be lowercase kebab-case")
        return value

    @field_validator("public_text", "rationale")
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("semantic commitment text must not be blank")
        return value


class ArtifactObservationV1(BaseModel):
    """One public, value-free rule for locating a delivered claim.

    The locator and encoding describe presentation only.  They must not contain
    sample values or expected results: both the reference and the independent
    verifier receive this same user-reviewable protocol before any example is
    proposed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str = Field(min_length=1, max_length=64)
    commitment_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    locator: str = Field(min_length=1, max_length=800)
    value_encoding: str = Field(min_length=1, max_length=800)

    @field_validator("observation_id")
    @classmethod
    def _valid_observation_id(cls, value: str) -> str:
        value = value.strip().lower()
        if _OBSERVATION_ID_RE.fullmatch(value) is None:
            raise ValueError("observation_id must be lowercase kebab-case")
        return value

    @field_validator("commitment_ids")
    @classmethod
    def _valid_commitment_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(item.strip().lower() for item in value)
        if (
            not cleaned
            or len(cleaned) != len(set(cleaned))
            or any(_COMMITMENT_ID_RE.fullmatch(item) is None for item in cleaned)
        ):
            raise ValueError("commitment_ids must be unique lowercase kebab-case")
        return cleaned

    @field_validator("locator", "value_encoding")
    @classmethod
    def _nonblank_protocol_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("artifact protocol text must not be blank")
        return value


class ArtifactProtocolV1(BaseModel):
    """Public presentation grammar shared by producer and independent judge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    protocol_id: str = Field(min_length=1, max_length=64)
    observations: tuple[ArtifactObservationV1, ...] = Field(
        min_length=1,
        max_length=24,
    )

    @field_validator("protocol_id")
    @classmethod
    def _valid_protocol_id(cls, value: str) -> str:
        value = value.strip().lower()
        if _OBSERVATION_ID_RE.fullmatch(value) is None:
            raise ValueError("protocol_id must be lowercase kebab-case")
        return value

    @model_validator(mode="after")
    def _observation_ids_are_unique(self) -> ArtifactProtocolV1:
        ids = [item.observation_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("artifact observation ids must be unique")
        return self

class IntentConfirmationV1(BaseModel):
    """Human confirmation of one exact semantic payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmed_by: Literal["USER"] = "USER"
    confirmed_at: str
    semantics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DeliveryIntentV1(BaseModel):
    """Truthful delivery needs plus Core's deterministic admission result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str
    support_status: Literal["SUPPORTED"] = "SUPPORTED"
    origin: Literal["MODEL_PROPOSED", "USER_EDITED"] = "MODEL_PROPOSED"
    requirements: DeliveryRequirements
    admitted_output_format_id: str


class IntentContractDraftV1(BaseModel):
    """Editable intent record stored beside a Product draft."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    user_goal: str = Field(min_length=1, max_length=8000)
    user_goal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    commitments: tuple[SemanticCommitmentV1, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    artifact_protocol: ArtifactProtocolV1 | None = None
    delivery: DeliveryIntentV1 | None = None
    confirmation: IntentConfirmationV1 | None = None

    @field_validator("user_goal")
    @classmethod
    def _clean_user_goal(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("user_goal must not be blank")
        return value

    @model_validator(mode="after")
    def _goal_digest_and_ids_are_consistent(self) -> IntentContractDraftV1:
        if self.user_goal_sha256 != sha256_text(self.user_goal):
            raise ValueError("user_goal_sha256 does not bind user_goal")
        ids = [item.commitment_id for item in self.commitments]
        if len(ids) != len(set(ids)):
            raise ValueError("semantic commitment ids must be unique")
        return self


class IntentContractError(ValueError):
    """Stable public reason code for an invalid intent trace."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_intent_contract(user_goal: str) -> dict:
    """Create an unconfirmed trace at deterministic intake time."""

    cleaned = user_goal.strip()
    try:
        contract = IntentContractDraftV1(
            user_goal=cleaned,
            user_goal_sha256=sha256_text(cleaned),
        )
    except ValueError as exc:
        raise IntentContractError("INTENT_USER_GOAL_INVALID") from exc
    return contract.model_dump(mode="json")


def normalize_semantic_commitments(raw: object) -> tuple[SemanticCommitmentV1, ...]:
    """Validate model/user commitments without interpreting task vocabulary."""

    if not isinstance(raw, (list, tuple)) or not raw:
        raise IntentContractError("SEMANTIC_COMMITMENTS_MISSING")
    try:
        commitments = tuple(SemanticCommitmentV1.model_validate(item) for item in raw)
    except ValueError as exc:
        raise IntentContractError("SEMANTIC_COMMITMENTS_INVALID") from exc
    ids = [item.commitment_id for item in commitments]
    if len(ids) != len(set(ids)):
        raise IntentContractError("SEMANTIC_COMMITMENT_ID_DUPLICATE")
    return commitments


def normalize_artifact_protocol(
    raw: object,
    commitments: tuple[SemanticCommitmentV1, ...],
) -> ArtifactProtocolV1:
    """Validate a format-neutral public grammar and its semantic coverage."""

    try:
        protocol = ArtifactProtocolV1.model_validate(raw)
    except ValueError as exc:
        raise IntentContractError("ARTIFACT_PROTOCOL_INVALID") from exc
    commitment_ids = {item.commitment_id for item in commitments}
    observed_ids = {
        commitment_id
        for observation in protocol.observations
        for commitment_id in observation.commitment_ids
    }
    if observed_ids - commitment_ids:
        raise IntentContractError("ARTIFACT_PROTOCOL_UNKNOWN_COMMITMENT")
    if commitment_ids - observed_ids:
        raise IntentContractError("ARTIFACT_PROTOCOL_COMMITMENT_UNCOVERED")
    return protocol


def install_artifact_protocol(draft: dict, raw: object) -> dict:
    """Install the shared public grammar and invalidate older confirmation."""

    try:
        current = IntentContractDraftV1.model_validate(draft.get("_intent_contract"))
    except ValueError as exc:
        raise IntentContractError("INTENT_CONTRACT_INVALID") from exc
    protocol = normalize_artifact_protocol(raw, current.commitments)
    updated = current.model_copy(
        update={"artifact_protocol": protocol, "confirmation": None}
    )
    draft["_intent_contract"] = updated.model_dump(mode="json")
    draft.setdefault("capability", {})["statement"] = compile_capability_statement(
        updated.user_goal,
        updated.commitments,
        updated.artifact_protocol,
    )
    return draft


def install_delivery_intent(
    draft: dict,
    *,
    raw_requirements: DeliveryRequirements | dict,
    profile_id: str,
    admitted_output_format_id: str,
    origin: Literal["MODEL_PROPOSED", "USER_EDITED"] = "MODEL_PROPOSED",
) -> dict:
    """Persist the admitted topology and invalidate any prior confirmation."""

    try:
        current = IntentContractDraftV1.model_validate(draft.get("_intent_contract"))
        profile = product_delivery_profile(profile_id)
        requirements, artifact = profile.admit_requirements(raw_requirements)
    except ProductProfileError as exc:
        raise IntentContractError(f"DELIVERY_INTENT_{exc}") from exc
    except ValueError as exc:
        raise IntentContractError("DELIVERY_INTENT_INVALID") from exc
    if artifact.format_id != admitted_output_format_id:
        raise IntentContractError("DELIVERY_INTENT_OUTPUT_PROJECTION_MISMATCH")
    delivery = DeliveryIntentV1(
        profile_id=profile.profile_id,
        origin=origin,
        requirements=requirements,
        admitted_output_format_id=artifact.format_id,
    )
    draft["_intent_contract"] = current.model_copy(
        update={"delivery": delivery, "confirmation": None}
    ).model_dump(mode="json")
    return draft


def install_delivery_intent_from_interface(
    draft: dict,
    *,
    profile_id: str,
) -> dict:
    """Compile an explicit human-edited interface into a typed delivery intent."""

    profile = product_delivery_profile(profile_id)
    interface = ((draft.get("tool") or {}).get("interface") or {})
    try:
        artifact = profile.assert_interface(interface)
    except ProductProfileError as exc:
        raise IntentContractError(f"DELIVERY_INTENT_INTERFACE_{exc}") from exc
    input_format = str((interface.get("input") or {}).get("format") or "").strip()
    if not input_format:
        raise IntentContractError("DELIVERY_INTENT_INPUT_FORMAT_MISSING")
    try:
        current_intent = IntentContractDraftV1.model_validate(
            draft.get("_intent_contract")
        )
    except ValueError as exc:
        raise IntentContractError("INTENT_CONTRACT_INVALID") from exc
    prior_representation = "utf8_text"
    if current_intent.delivery is not None:
        prior_representation = (
            current_intent.delivery.requirements.inputs[0].representation
        )
    requirements = DeliveryRequirements.model_validate({
        "inputs": [{
            "kind": str((interface.get("input") or {}).get("kind") or "file"),
            "location": "local",
            "representation": prior_representation,
            "format_label": input_format,
            "role": "user-confirmed primary input",
        }],
        "outputs": [{
            "kind": (
                "directory"
                if profile.profile_id == "workspace_bundle_v1"
                else "text_artifact"
            ),
            "format_id": artifact.format_id,
            "format_label": artifact.display_name,
            "role": "user-confirmed primary artifact",
        }],
        "network": "offline",
        "credentials": "none",
        "lifecycle": "per_invocation",
        "runtime": "local_cpu",
    })
    return install_delivery_intent(
        draft,
        raw_requirements=requirements,
        profile_id=profile.profile_id,
        admitted_output_format_id=artifact.format_id,
        origin="USER_EDITED",
    )


def replace_delivery_input_representation(
    draft: dict,
    representation: str,
) -> dict:
    """Apply one explicit human correction to the typed input contract.

    Representation is not derivable from a suffix, MIME label, repository or
    qualification case.  It therefore needs its own review path.  Reusing
    :func:`install_delivery_intent` keeps support admission authoritative and
    invalidates any confirmation that bound the previous representation.
    """

    try:
        current = IntentContractDraftV1.model_validate(draft.get("_intent_contract"))
    except ValueError as exc:
        raise IntentContractError("INTENT_CONTRACT_INVALID") from exc
    if current.delivery is None or len(current.delivery.requirements.inputs) != 1:
        raise IntentContractError("DELIVERY_INPUT_REPRESENTATION_MISSING")
    normalized: Literal["utf8_text", "binary"]
    if representation == "utf8_text":
        normalized = "utf8_text"
    elif representation == "binary":
        normalized = "binary"
    else:
        raise IntentContractError("DELIVERY_INPUT_REPRESENTATION_INVALID")
    original = current.delivery.requirements.inputs[0]
    requirements = current.delivery.requirements.model_copy(
        update={
            "inputs": (
                original.model_copy(update={"representation": normalized}),
            ),
        }
    )
    return install_delivery_intent(
        draft,
        raw_requirements=requirements,
        profile_id=current.delivery.profile_id,
        admitted_output_format_id=current.delivery.admitted_output_format_id,
        origin="USER_EDITED",
    )


def compile_capability_statement(
    user_goal: str,
    commitments: tuple[SemanticCommitmentV1, ...],
    artifact_protocol: ArtifactProtocolV1 | None = None,
) -> str:
    """Compile all normative task prose from traceable public inputs."""

    if not commitments:
        raise IntentContractError("SEMANTIC_COMMITMENTS_MISSING")
    lines: list[str] = [
        f"用户目标：{user_goal.strip()}",
        "公开行为承诺：",
        *[
            f"- [{item.commitment_id}] {item.public_text}"
            for item in commitments
        ],
    ]
    if artifact_protocol is not None:
        lines.extend([
            "公开产物协议：",
            *[
                (
                    f"- [{item.observation_id} -> "
                    f"{','.join(item.commitment_ids)}] 定位：{item.locator}；"
                    f"值表示：{item.value_encoding}"
                )
                for item in artifact_protocol.observations
            ],
        ])
    lines.append(
        "统一运行语义：当输入不属于公开承诺定义的有效域时抛 "
        "UserInputError（CLI exit 1）；"
        "相同输入重复运行得到逐字节一致的结果；运行期完全离线。"
    )
    return "\n".join(lines)


def install_semantic_commitments(draft: dict, raw: object) -> dict:
    """Install model-proposed semantics and invalidate any older confirmation."""

    try:
        current = IntentContractDraftV1.model_validate(draft.get("_intent_contract"))
    except ValueError as exc:
        raise IntentContractError("INTENT_CONTRACT_INVALID") from exc
    commitments = normalize_semantic_commitments(raw)
    updated = current.model_copy(
        update={"commitments": commitments, "confirmation": None}
    )
    draft["_intent_contract"] = updated.model_dump(mode="json")
    draft.setdefault("capability", {})["statement"] = compile_capability_statement(
        updated.user_goal,
        updated.commitments,
        updated.artifact_protocol,
    )
    return draft


def replace_semantic_commitments(draft: dict, texts: list[str]) -> dict:
    """Apply a human edit while preserving stable IDs where possible."""

    try:
        current = IntentContractDraftV1.model_validate(draft.get("_intent_contract"))
    except ValueError as exc:
        raise IntentContractError("INTENT_CONTRACT_INVALID") from exc
    cleaned = [" ".join(str(value).split()) for value in texts]
    if not cleaned or any(not value for value in cleaned):
        raise IntentContractError("SEMANTIC_COMMITMENTS_MISSING")
    if len(cleaned) > 16:
        raise IntentContractError("SEMANTIC_COMMITMENTS_TOO_MANY")
    commitments: list[SemanticCommitmentV1] = []
    for index, public_text in enumerate(cleaned):
        previous = current.commitments[index] if index < len(current.commitments) else None
        commitments.append(SemanticCommitmentV1(
            commitment_id=(
                previous.commitment_id if previous is not None else f"behavior-{index + 1}"
            ),
            public_text=public_text,
            rationale=(
                previous.rationale
                if previous is not None and previous.public_text == public_text
                else "用户在合同审核阶段补充或修改。"
            ),
            origin=(
                previous.origin
                if previous is not None and previous.public_text == public_text
                else "USER_EDITED"
            ),
        ))
    updated = current.model_copy(
        update={"commitments": tuple(commitments), "confirmation": None}
    )
    draft["_intent_contract"] = updated.model_dump(mode="json")
    draft.setdefault("capability", {})["statement"] = compile_capability_statement(
        updated.user_goal,
        updated.commitments,
        updated.artifact_protocol,
    )
    return draft


def _without_none(value: object) -> object:
    """Canonicalize draft and Pydantic projections to the same JSON shape."""

    if isinstance(value, dict):
        return {
            str(key): _without_none(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple)):
        return [_without_none(item) for item in value]
    return value


def _semantic_payload(draft: dict) -> dict:
    try:
        intent = IntentContractDraftV1.model_validate(draft.get("_intent_contract"))
    except ValueError as exc:
        raise IntentContractError("INTENT_CONTRACT_INVALID") from exc
    tool = draft.get("tool") or {}
    interface = tool.get("interface") or {}
    capability = draft.get("capability") or {}
    return {
        "schema_version": intent.schema_version,
        "user_goal": intent.user_goal,
        "user_goal_sha256": intent.user_goal_sha256,
        "commitments": [
            item.model_dump(mode="json") for item in intent.commitments
        ],
        "artifact_protocol": (
            intent.artifact_protocol.model_dump(mode="json")
            if intent.artifact_protocol is not None
            else None
        ),
        "delivery": (
            intent.delivery.model_dump(mode="json")
            if intent.delivery is not None
            else None
        ),
        "compiled_statement": str(capability.get("statement") or ""),
        "input": _without_none(interface.get("input") or {}),
        "output": _without_none(interface.get("output") or {}),
        "output_schema": str(capability.get("output_schema") or ""),
    }


def semantic_fingerprint(draft: dict) -> str:
    payload = json.dumps(
        _semantic_payload(draft),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def frozen_semantic_fingerprint(
    *,
    intent_contract: object,
    compiled_statement: str,
    input_contract: object,
    output_contract: object,
    output_schema: str,
) -> str:
    """Recompute the confirmation binding from a frozen contract projection."""

    try:
        intent = IntentContractDraftV1.model_validate(intent_contract)
    except ValueError as exc:
        raise IntentContractError("INTENT_CONTRACT_INVALID") from exc
    payload = {
        "schema_version": intent.schema_version,
        "user_goal": intent.user_goal,
        "user_goal_sha256": intent.user_goal_sha256,
        "commitments": [
            item.model_dump(mode="json") for item in intent.commitments
        ],
        "artifact_protocol": (
            intent.artifact_protocol.model_dump(mode="json")
            if intent.artifact_protocol is not None
            else None
        ),
        "delivery": (
            intent.delivery.model_dump(mode="json")
            if intent.delivery is not None
            else None
        ),
        "compiled_statement": compiled_statement,
        "input": _without_none(input_contract),
        "output": _without_none(output_contract),
        "output_schema": output_schema,
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_frozen_intent_projection(
    *,
    intent_contract: object,
    compiled_statement: str,
    input_contract: object,
    output_contract: object,
    output_schema: str,
) -> list[str]:
    """Re-run admission and confirmation binding for a frozen projection.

    A Product draft is not authoritative merely because it carries an intent
    blob and a digest.  Every boundary that consumes current Product semantics
    must independently prove that the exact interface still belongs to the
    declared delivery profile, that the public statement was compiled from the
    confirmed commitments, and that the human digest binds those exact bytes.

    This validation deliberately knows nothing about repositories, libraries,
    file-format words, or qualification cases.  It checks topology and
    provenance only; task semantics remain in public commitments and their
    independently bound examples/verifiers.
    """

    try:
        intent = IntentContractDraftV1.model_validate(intent_contract)
    except ValueError:
        return ["INTENT_CONTRACT_INVALID"]
    if not intent.commitments:
        return ["SEMANTIC_COMMITMENTS_MISSING"]
    if intent.artifact_protocol is not None:
        try:
            normalize_artifact_protocol(intent.artifact_protocol, intent.commitments)
        except IntentContractError as exc:
            return [str(exc)]
    if intent.delivery is None:
        return ["DELIVERY_INTENT_MISSING"]
    if intent.confirmation is None:
        return ["INTENT_CONFIRMATION_MISSING"]
    try:
        profile = product_delivery_profile(intent.delivery.profile_id)
        _, admitted_artifact = profile.admit_requirements(
            intent.delivery.requirements
        )
        interface_artifact = profile.assert_interface({
            "input": input_contract,
            "output": output_contract,
        })
    except ProductProfileError:
        return ["DELIVERY_INTENT_INTERFACE_MISMATCH"]
    if admitted_artifact.format_id != intent.delivery.admitted_output_format_id:
        return ["DELIVERY_INTENT_OUTPUT_PROJECTION_MISMATCH"]
    if interface_artifact.format_id != admitted_artifact.format_id:
        return ["DELIVERY_INTENT_INTERFACE_MISMATCH"]
    if compiled_statement != compile_capability_statement(
        intent.user_goal,
        intent.commitments,
        intent.artifact_protocol,
    ):
        return ["CAPABILITY_STATEMENT_NOT_COMPILED_FROM_INTENT"]
    try:
        frozen_hash = frozen_semantic_fingerprint(
            intent_contract=intent.model_dump(mode="json"),
            compiled_statement=compiled_statement,
            input_contract=input_contract,
            output_contract=output_contract,
            output_schema=output_schema,
        )
    except IntentContractError:
        return ["INTENT_CONTRACT_INVALID"]
    if intent.confirmation.semantics_sha256 != frozen_hash:
        return ["INTENT_CONFIRMATION_STALE"]
    return []


def confirm_intent_contract(draft: dict, *, confirmed_at: str | None = None) -> dict:
    """Bind the exact public semantics after an explicit human action."""

    problems = validate_intent_contract(draft, require_confirmation=False)
    if problems:
        raise IntentContractError(problems[0])
    intent = IntentContractDraftV1.model_validate(draft["_intent_contract"])
    if intent.delivery is None:
        raise IntentContractError("DELIVERY_INTENT_MISSING")
    confirmation = IntentConfirmationV1(
        confirmed_at=(
            confirmed_at
            or datetime.now(UTC).isoformat().replace("+00:00", "Z")
        ),
        semantics_sha256=semantic_fingerprint(draft),
    )
    draft["_intent_contract"] = intent.model_copy(
        update={"confirmation": confirmation}
    ).model_dump(mode="json")
    return draft


def invalidate_intent_confirmation(draft: dict) -> None:
    """Invalidate confirmation after any semantic contract edit."""

    try:
        intent = IntentContractDraftV1.model_validate(draft.get("_intent_contract"))
    except ValueError as exc:
        raise IntentContractError("INTENT_CONTRACT_INVALID") from exc
    if intent.confirmation is not None:
        draft["_intent_contract"] = intent.model_copy(
            update={"confirmation": None}
        ).model_dump(mode="json")


def validate_intent_contract(
    draft: dict,
    *,
    require_confirmation: bool = True,
) -> list[str]:
    """Return stable problems; never infer semantic equivalence from keywords."""

    try:
        intent = IntentContractDraftV1.model_validate(draft.get("_intent_contract"))
    except ValueError:
        return ["INTENT_CONTRACT_INVALID"]
    if not intent.commitments:
        return ["SEMANTIC_COMMITMENTS_MISSING"]
    if intent.artifact_protocol is None:
        return ["ARTIFACT_PROTOCOL_MISSING"]
    try:
        normalize_artifact_protocol(intent.artifact_protocol, intent.commitments)
    except IntentContractError as exc:
        return [str(exc)]
    if intent.delivery is None:
        return ["DELIVERY_INTENT_MISSING"]
    try:
        profile = product_delivery_profile(intent.delivery.profile_id)
        _, admitted_artifact = profile.admit_requirements(intent.delivery.requirements)
        if admitted_artifact.format_id != intent.delivery.admitted_output_format_id:
            return ["DELIVERY_INTENT_OUTPUT_PROJECTION_MISMATCH"]
        tool = draft.get("tool") or {}
        interface = tool.get("interface") or {}
        interface_artifact = profile.assert_interface(interface)
        if interface_artifact.format_id != admitted_artifact.format_id:
            return ["DELIVERY_INTENT_INTERFACE_MISMATCH"]
    except ProductProfileError:
        return ["DELIVERY_INTENT_INTERFACE_MISMATCH"]
    expected_statement = compile_capability_statement(
        intent.user_goal,
        intent.commitments,
        intent.artifact_protocol,
    )
    actual_statement = str((draft.get("capability") or {}).get("statement") or "")
    if actual_statement != expected_statement:
        return ["CAPABILITY_STATEMENT_NOT_COMPILED_FROM_INTENT"]
    if not require_confirmation:
        return []
    confirmation = intent.confirmation
    if confirmation is None:
        return ["INTENT_CONFIRMATION_MISSING"]
    if confirmation.semantics_sha256 != semantic_fingerprint(draft):
        return ["INTENT_CONFIRMATION_STALE"]
    return []


def frozen_intent_snapshot(draft: dict) -> dict:
    """Return the exact confirmed trace for inclusion in a frozen contract."""

    problems = validate_intent_contract(draft, require_confirmation=True)
    if problems:
        raise IntentContractError(problems[0])
    intent = IntentContractDraftV1.model_validate(draft["_intent_contract"])
    return intent.model_dump(mode="json")
