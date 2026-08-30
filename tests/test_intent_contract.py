"""Generic intent tracing: no repository or file-format special cases."""

from __future__ import annotations

from copy import deepcopy

import pytest

from repoproof.adoption.intake.intent_contract import (
    IntentContractError,
    confirm_intent_contract,
    frozen_semantic_fingerprint,
    install_artifact_protocol,
    install_delivery_intent_from_interface,
    install_semantic_commitments,
    new_intent_contract,
    replace_delivery_input_representation,
    replace_semantic_commitments,
    semantic_fingerprint,
    validate_frozen_intent_projection,
    validate_intent_contract,
)


def _draft(goal: str = "把我的输入整理成方便后续使用的结果") -> dict:
    draft = {
        "_intent_contract": new_intent_contract(goal),
        "tool": {
            "interface": {
                "input": {"kind": "file", "format": "user input"},
                "output": {
                    "kind": "stdout",
                    "format": "plain text",
                    "contract": {
                        "media_type": "text/plain",
                        "root_type": "text",
                        "required": {},
                        "validation_profile": "plain_text_v1",
                    },
                },
            },
        },
        "capability": {"statement": "", "output_schema": "WorkArtifact"},
    }
    install_delivery_intent_from_interface(draft, profile_id="cli_v2")
    install_semantic_commitments(draft, [{
        "commitment_id": "preserve-order",
        "public_text": "保留首次出现的顺序，对每条有效内容只输出一次。",
        "rationale": "用户需要结果能继续用于原工作流。",
    }])
    return install_artifact_protocol(draft, {
        "schema_version": 1,
        "protocol_id": "ordered-result-v1",
        "observations": [{
            "observation_id": "ordered-body",
            "commitment_ids": ["preserve-order"],
            "locator": "完整 UTF-8 文本正文中的逐行记录",
            "value_encoding": "每条记录占一行，按首次出现顺序排列",
        }],
    })


def test_vague_goal_words_cannot_create_task_semantics_by_themselves() -> None:
    """Core stores vague prose but never mines it for hidden behavior rules."""

    raw = new_intent_contract(
        "别人说这个仓库能处理 RIS、TSV、GraphML 和 FASTQ，帮我整理成好用的结果。"
    )

    assert raw["user_goal"].startswith("别人说这个仓库")
    assert raw["commitments"] == []
    assert raw["artifact_protocol"] is None
    assert raw["delivery"] is None
    assert raw["confirmation"] is None


def test_confirmation_binds_goal_commitments_and_interface() -> None:
    draft = _draft()
    confirm_intent_contract(draft, confirmed_at="2026-08-30T00:00:00Z")

    assert validate_intent_contract(draft) == []
    stored = draft["_intent_contract"]["confirmation"]["semantics_sha256"]
    assert stored == semantic_fingerprint(draft)
    assert stored == frozen_semantic_fingerprint(
        intent_contract=draft["_intent_contract"],
        compiled_statement=draft["capability"]["statement"],
        input_contract={**draft["tool"]["interface"]["input"], "contract": None},
        output_contract=draft["tool"]["interface"]["output"],
        output_schema=draft["capability"]["output_schema"],
    )


def test_frozen_projection_replays_profile_admission_not_format_keywords() -> None:
    draft = _draft("把一份输入整理成可继续使用的文档")
    confirm_intent_contract(draft, confirmed_at="2026-08-30T00:00:00Z")
    interface = draft["tool"]["interface"]

    assert validate_frozen_intent_projection(
        intent_contract=draft["_intent_contract"],
        compiled_statement=draft["capability"]["statement"],
        input_contract=interface["input"],
        output_contract=interface["output"],
        output_schema=draft["capability"]["output_schema"],
    ) == []

    # The human label still says “plain text”, so a keyword/root-only check
    # would accept this.  The explicit validation profile is part of the
    # confirmed delivery projection and its removal must fail closed.
    weakened = deepcopy(interface["output"])
    weakened["contract"].pop("validation_profile")
    assert validate_frozen_intent_projection(
        intent_contract=draft["_intent_contract"],
        compiled_statement=draft["capability"]["statement"],
        input_contract=interface["input"],
        output_contract=weakened,
        output_schema=draft["capability"]["output_schema"],
    ) == ["DELIVERY_INTENT_INTERFACE_MISMATCH"]


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda value: value["capability"].update(statement="绕过编译器的隐藏规则"),
            "CAPABILITY_STATEMENT_NOT_COMPILED_FROM_INTENT",
        ),
        (
            lambda value: value["tool"]["interface"]["output"].update(format="changed"),
            "DELIVERY_INTENT_INTERFACE_MISMATCH",
        ),
        (
            lambda value: value["capability"].update(output_schema="ChangedArtifact"),
            "INTENT_CONFIRMATION_STALE",
        ),
        (
            lambda value: value["_intent_contract"]["artifact_protocol"][
                "observations"
            ][0].update(locator="被篡改的隐藏位置"),
            "CAPABILITY_STATEMENT_NOT_COMPILED_FROM_INTENT",
        ),
    ],
)
def test_tampering_after_confirmation_fails_closed(mutator, reason: str) -> None:
    draft = _draft()
    confirm_intent_contract(draft, confirmed_at="2026-08-30T00:00:00Z")
    mutator(draft)

    assert validate_intent_contract(draft) == [reason]


def test_human_edit_preserves_provenance_and_invalidates_confirmation() -> None:
    draft = _draft()
    confirm_intent_contract(draft, confirmed_at="2026-08-30T00:00:00Z")

    replace_semantic_commitments(draft, ["输入的每条内容都保留，不联网补全。"])

    commitment = draft["_intent_contract"]["commitments"][0]
    assert commitment["origin"] == "USER_EDITED"
    assert commitment["rationale"] == "用户在合同审核阶段补充或修改。"
    assert draft["_intent_contract"]["confirmation"] is None
    assert validate_intent_contract(draft) == ["INTENT_CONFIRMATION_MISSING"]


def test_input_representation_is_explicit_reviewed_contract_state() -> None:
    draft = _draft()
    confirm_intent_contract(draft, confirmed_at="2026-08-30T00:00:00Z")

    replace_delivery_input_representation(draft, "binary")

    delivery = draft["_intent_contract"]["delivery"]
    assert delivery["requirements"]["inputs"][0]["representation"] == "binary"
    assert delivery["origin"] == "USER_EDITED"
    assert draft["_intent_contract"]["confirmation"] is None
    assert validate_intent_contract(draft) == ["INTENT_CONFIRMATION_MISSING"]
    with pytest.raises(
        IntentContractError,
        match="DELIVERY_INPUT_REPRESENTATION_INVALID",
    ):
        replace_delivery_input_representation(draft, "PDF")


def test_goal_digest_tamper_and_duplicate_ids_are_rejected() -> None:
    draft = _draft()
    draft["_intent_contract"]["user_goal"] = "被篡改的目标"
    assert validate_intent_contract(draft) == ["INTENT_CONTRACT_INVALID"]

    duplicate = _draft()
    item = deepcopy(duplicate["_intent_contract"]["commitments"][0])
    with pytest.raises(IntentContractError, match="SEMANTIC_COMMITMENT_ID_DUPLICATE"):
        install_semantic_commitments(duplicate, [item, item])


def test_public_artifact_protocol_covers_every_commitment_without_hidden_values() -> None:
    draft = _draft()
    protocol = draft["_intent_contract"]["artifact_protocol"]

    assert "公开产物协议" in draft["capability"]["statement"]
    assert protocol["observations"][0]["commitment_ids"] == ["preserve-order"]

    install_semantic_commitments(draft, [
        {
            "commitment_id": "preserve-order",
            "public_text": "保留首次出现的顺序，对每条有效内容只输出一次。",
            "rationale": "用户需要结果能继续用于原工作流。",
        },
        {
            "commitment_id": "mark-invalid",
            "public_text": "无法处理的条目需要明确标记。",
            "rationale": "用户需要知道哪些内容没有被处理。",
        },
    ])
    with pytest.raises(
        IntentContractError,
        match="ARTIFACT_PROTOCOL_COMMITMENT_UNCOVERED",
    ):
        install_artifact_protocol(draft, {
            "schema_version": 1,
            "protocol_id": "incomplete-v1",
            "observations": [{
                "observation_id": "ordered-body",
                "commitment_ids": ["preserve-order"],
                "locator": "正文",
                "value_encoding": "UTF-8 文本",
            }],
        })


@pytest.mark.parametrize(
    "goal",
    [
        "整理一份实验记录，给同事继续检查",
        "把一份阅读笔记变成浏览器可打开的页面",
        "把关系数据整理成项目纪要",
    ],
)
def test_trace_mechanism_is_vocabulary_agnostic(goal: str) -> None:
    draft = _draft(goal)
    assert goal in draft["capability"]["statement"]
    assert "preserve-order" in draft["capability"]["statement"]
    assert validate_intent_contract(draft, require_confirmation=False) == []
