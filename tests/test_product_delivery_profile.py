"""Product delivery admission is topology-driven, not task-keyword-driven."""

from __future__ import annotations

import pytest

from repoproof.adoption.delivery.product_profile import (
    WORKSPACE_BUNDLE_PROFILE_ID,
    ProductProfileError,
    delivery_requirements_json_schema,
    product_delivery_profile,
    project_requirement_brief,
    select_product_delivery_profile,
)


def _requirements(
    *,
    output_format_id: str = "plain_text",
    input_kind: str = "file",
    input_location: str = "local",
    input_representation: str = "utf8_text",
    output_kind: str = "text_artifact",
    network: str = "offline",
    credentials: str = "none",
    lifecycle: str = "per_invocation",
    runtime: str = "local_cpu",
) -> dict:
    return {
        "inputs": [{
            "kind": input_kind,
            "location": input_location,
            "representation": input_representation,
            "format_label": "Source",
            "role": "material to process",
        }],
        "outputs": [{
            "kind": output_kind,
            "format_id": output_format_id,
            "format_label": "Result",
            "role": "user-facing result",
        }],
        "network": network,
        "credentials": credentials,
        "lifecycle": lifecycle,
        "runtime": runtime,
    }


def test_every_registered_text_artifact_round_trips_through_the_profile() -> None:
    profile = product_delivery_profile()

    for artifact in profile.output_artifacts:
        requirements, admitted = profile.admit_requirements(
            _requirements(output_format_id=artifact.format_id)
        )
        assert requirements.outputs[0].format_id == artifact.format_id
        assert admitted == artifact
        format_name, contract = profile.contract_for(artifact.format_id)
        if artifact.root_type == "text":
            assert contract.validation_profile == artifact.validation_profile
            assert contract.validation_profile is not None
        else:
            assert contract.validation_profile is None
        assert profile.assert_compiled_output(
            format_id=artifact.format_id,
            format_name=format_name,
            contract=contract,
        ) == contract
        assert profile.resolve_compiled_output(
            format_name=format_name,
            contract=contract,
        ) == artifact


def test_input_representation_is_typed_not_inferred_from_format_words() -> None:
    profile = product_delivery_profile()
    text_requirements, _ = profile.admit_requirements(
        _requirements(input_representation="utf8_text")
    )
    binary_requirements, _ = profile.admit_requirements(
        _requirements(input_representation="binary")
    )
    assert text_requirements.inputs[0].representation == "utf8_text"
    assert binary_requirements.inputs[0].representation == "binary"

    # Compatibility parsing retains the historical default, while the schema
    # shown to every new drafter makes the choice explicit.
    legacy = _requirements()
    legacy["inputs"][0].pop("representation")
    parsed, _ = profile.admit_requirements(legacy)
    assert parsed.inputs[0].representation == "utf8_text"
    input_schema = delivery_requirements_json_schema()["properties"]["inputs"]["items"]
    assert "representation" in input_schema["required"]
    description = input_schema["properties"]["representation"]["description"]
    assert "file input kind alone never implies binary" in description.lower()
    assert "meaningful unicode text serialization" in description.lower()


def test_output_selection_ignores_format_and_repository_words_in_prose() -> None:
    """Only the typed format_id may select a delivery representation."""

    raw = _requirements(output_format_id="plain_text")
    raw["inputs"][0]["format_label"] = "FASTQ GraphML RIS TSV source"
    raw["inputs"][0]["role"] = "material recommended for several libraries"
    raw["outputs"][0]["format_label"] = "RIS TSV Markdown HTML JSON"
    raw["outputs"][0]["role"] = "make something useful for my work"

    requirements, artifact = product_delivery_profile().admit_requirements(raw)

    assert requirements.outputs[0].format_id == "plain_text"
    assert artifact.format_id == "plain_text"
    assert artifact.media_type == "text/plain"


def test_required_fields_are_a_property_of_the_artifact_not_model_prose() -> None:
    profile = product_delivery_profile()
    fields = [{"name": "count", "type": "integer"}]

    prompt_artifacts = {
        row["format_id"]: row
        for row in profile.prompt_context()["output"]["allowed_artifacts"]
    }
    assert prompt_artifacts["markdown"]["allows_required_fields"] is False
    assert prompt_artifacts["json_object"]["allows_required_fields"] is True

    _, object_contract = profile.contract_for(
        "json_object", required_fields=fields
    )
    assert object_contract.required == {"count": "integer"}

    with pytest.raises(ProductProfileError, match="OUTPUT_REQUIRED_FIELDS_NOT_SUPPORTED"):
        profile.contract_for("markdown", required_fields=fields)


def test_multiple_outputs_are_rejected_by_cardinality_not_by_words() -> None:
    profile = product_delivery_profile()
    raw = _requirements(output_format_id="tsv")
    raw["outputs"].append({
        "kind": "text_artifact",
        "format_id": "markdown",
        "format_label": "Notes",
        "role": "secondary result",
    })

    with pytest.raises(ProductProfileError, match="OUTPUT_CARDINALITY_MISMATCH"):
        profile.admit_requirements(raw)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"input_kind": "url", "input_location": "remote"}, "INPUT_SOURCE_MISMATCH"),
        ({"output_kind": "binary_artifact"}, "OUTPUT_TRANSPORT_MISMATCH"),
        ({"network": "required"}, "NETWORK_MODE_MISMATCH"),
        ({"credentials": "required"}, "CREDENTIAL_MODE_MISMATCH"),
        ({"lifecycle": "long_running"}, "LIFECYCLE_MISMATCH"),
        ({"runtime": "gpu"}, "RUNTIME_MODE_MISMATCH"),
    ],
)
def test_delivery_dimensions_fail_independently(change: dict, reason: str) -> None:
    with pytest.raises(ProductProfileError, match=reason):
        product_delivery_profile().admit_requirements(_requirements(**change))


def test_unknown_artifact_and_tampered_contract_fail_closed() -> None:
    profile = product_delivery_profile()

    with pytest.raises(ProductProfileError, match="OUTPUT_FORMAT_NOT_IN_PROFILE"):
        profile.admit_requirements(_requirements(output_format_id="unknown-format"))

    with pytest.raises(ProductProfileError, match="OUTPUT_NOT_COMPILED_FROM_PROFILE"):
        profile.resolve_compiled_output(
            format_name="Markdown",
            contract={"media_type": "text/html", "root_type": "text", "required": {}},
        )


def test_adoptable_text_is_compiled_from_admitted_shape() -> None:
    raw = {
        "brief_id": "example",
        "title": "presentation label not copied",
        "scenario": "I need to organize one research export",
        "delivery_requirements": _requirements(output_format_id="markdown"),
        "boundary": "keep uncertain entries visible",
        "reason": "evidence label not copied",
    }

    projected = project_requirement_brief(raw)

    assert "presentation label not copied" not in projected["text"]
    assert "evidence label not copied" not in projected["text"]
    assert "一份Markdown 文档（.md）" in projected["text"]
    assert projected["delivery_shape"]["output_cardinality"] == 1


@pytest.mark.parametrize("input_kind", ["file", "directory"])
def test_workspace_bundle_profile_admits_one_local_input_path(input_kind: str) -> None:
    profile = product_delivery_profile(WORKSPACE_BUNDLE_PROFILE_ID)
    raw = _requirements(
        output_format_id="workspace_bundle",
        input_kind=input_kind,
        output_kind="directory",
    )

    requirements, artifact = profile.admit_requirements(raw)

    assert requirements.inputs[0].kind == input_kind
    assert artifact.format_id == "workspace_bundle"
    assert profile.prompt_context()["output"] == {
        "kind": "directory",
        "cardinality": 1,
        "transport": "filesystem",
        "workspace_contract_required": True,
        "allowed_artifacts": [{
            "format_id": "workspace_bundle",
            "display_name": "离线多文件工作区",
            "extension": "",
            "media_type": "application/vnd.repoproof.workspace",
        }],
    }
    with pytest.raises(ProductProfileError, match="WORKSPACE_CONTRACT_REQUIRED"):
        profile.contract_for("workspace_bundle")


def test_workspace_bundle_profile_rejects_service_and_remote_topologies() -> None:
    profile = product_delivery_profile(WORKSPACE_BUNDLE_PROFILE_ID)
    with pytest.raises(ProductProfileError, match="OUTPUT_TRANSPORT_MISMATCH"):
        profile.admit_requirements(_requirements(
            output_format_id="workspace_bundle",
            output_kind="service",
        ))
    with pytest.raises(ProductProfileError, match="INPUT_SOURCE_MISMATCH"):
        profile.admit_requirements(_requirements(
            output_format_id="workspace_bundle",
            input_kind="url",
            input_location="remote",
            output_kind="directory",
        ))


def test_workspace_requirement_brief_is_profile_compiled() -> None:
    profile = product_delivery_profile(WORKSPACE_BUNDLE_PROFILE_ID)
    raw = {
        "brief_id": "workspace",
        "title": "Workspace",
        "scenario": "I need a reproducible research folder",
        "delivery_requirements": _requirements(
            output_format_id="workspace_bundle",
            input_kind="directory",
            output_kind="directory",
        ),
        "boundary": "do not contact remote services",
        "reason": "Useful",
    }

    projected = project_requirement_brief(raw, profile)

    assert "离线多文件工作区" in projected["text"]
    assert projected["delivery_shape"]["profile_id"] == WORKSPACE_BUNDLE_PROFILE_ID
    assert projected["delivery_shape"]["output_kind"] == "directory"


def test_typed_directory_output_selects_workspace_profile_without_keywords() -> None:
    requirements = _requirements(
        output_format_id="workspace_bundle",
        input_kind="directory",
        output_kind="directory",
    )
    requirements["inputs"][0]["format_label"] = "ordinary local material"
    selected = select_product_delivery_profile(requirements)
    assert selected.profile_id == WORKSPACE_BUNDLE_PROFILE_ID
