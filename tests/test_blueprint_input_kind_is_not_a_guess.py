"""夹具输入种类不是模型的选择题(incident-blueprint-input-kind-guessable-*)。

现象:两个独立仓库的起草都因 `WORKSPACE_FIXTURE_INPUT_KIND_MISMATCH` 整趟作废——
蓝图写 input_kind='file',而已准入的交付输入是 'directory'。Core 的规则是"每个蓝图都
必须构建那一种输入",也就是说这个字段**只有一个合法值**;可交给提供方强制的 JSON
schema 里它却是 file/directory 二选一。让提供方放行一个 Core 必拒的文档,猜错就是
整趟旅程死在起草阶段。

不变量:
  I1 已知交付输入种类时,起草面的 schema 把 blueprint.input_kind 钉成那**一个**值;
  I2 夹具重生成/修复面同样只钉那一个值;
  I3 尺子不变松:Core 仍然拒绝种类不符的蓝图(schema 是加固,不是替代)。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake import tool_drafter


def _blueprint_enum(schema: dict) -> list[str]:
    node = schema["properties"]["fixture_blueprints"]["items"]["properties"]["input_kind"]
    return list(node["enum"])


def test_draft_schema_pins_the_admitted_input_kind() -> None:
    pinned = tool_drafter._schema_with_pinned_input_kind(tool_drafter._DRAFT_SCHEMA, "directory")
    assert _blueprint_enum(pinned) == ["directory"]
    # The shared constant is untouched: pinning is per call, never global.
    assert _blueprint_enum(tool_drafter._DRAFT_SCHEMA) == ["file", "directory"]


def test_unknown_input_kind_leaves_the_choice_open() -> None:
    same = tool_drafter._schema_with_pinned_input_kind(tool_drafter._DRAFT_SCHEMA, "")
    assert _blueprint_enum(same) == ["file", "directory"]


def test_fixture_regeneration_surface_pins_it_too() -> None:
    schema = tool_drafter._workspace_fixture_inputs_schema(3, input_kind="file")
    assert _blueprint_enum(schema) == ["file"]
    assert schema["properties"]["fixture_blueprints"]["minItems"] == 3


def test_the_drafter_hands_the_pinned_schema_to_the_provider(monkeypatch) -> None:
    drafter = object.__new__(tool_drafter.LiteLLMDrafter)
    drafter.last_usage = {}
    seen: list[dict] = []

    class _Stop(Exception):
        pass

    def fake_once_with_system(system, user_msg, *, schema, schema_name):
        seen.append({"schema": schema, "schema_name": schema_name})
        raise _Stop()

    monkeypatch.setattr(drafter, "_once_with_system", fake_once_with_system)

    with pytest.raises(_Stop):
        drafter.draft(
            {
                "capability_goal": "把一个目录整理成可离线打开的产物",
                "authoritative_delivery_requirements": {
                    "inputs": [{"kind": "directory", "format": "dir"}]
                },
            }
        )

    assert seen and seen[0]["schema_name"] == "tool_draft"
    assert _blueprint_enum(seen[0]["schema"]) == ["directory"]


def test_core_still_rejects_a_mismatched_blueprint() -> None:
    document = {
        "fixture_blueprints": [
            {
                "blueprint_id": "one",
                "title": "One",
                "scenario": "s",
                "input_kind": "file",
                "parameters_json": '{"k": 1}',
            }
        ]
    }
    with pytest.raises(tool_drafter.DraftProjectionError) as excinfo:
        tool_drafter._normalize_fixture_blueprints(
            document, input_kind="directory", minimum=1, maximum=4
        )
    assert "WORKSPACE_FIXTURE_INPUT_KIND_MISMATCH" in str(excinfo.value)
