"""Product delivery admission is topology-driven, not task-keyword-driven."""

from __future__ import annotations

import pytest

from repoproof.adoption.delivery.product_profile import (
    ProductProfileError,
    product_delivery_profile,
    project_requirement_brief,
)


def _requirements(
    *,
    output_format_id: str = "plain_text",
    input_kind: str = "file",
    input_location: str = "local",
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
        assert profile.assert_compiled_output(
            format_id=artifact.format_id,
            format_name=format_name,
            contract=contract,
        ) == contract
        assert profile.resolve_compiled_output(
            format_name=format_name,
            contract=contract,
        ) == artifact


def test_required_fields_are_a_property_of_the_artifact_not_model_prose() -> None:
    profile = product_delivery_profile()
    fields = [{"name": "count", "type": "integer"}]

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
