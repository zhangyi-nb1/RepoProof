"""每一个 Core 投影拒绝都必须带字段级公开诊断,且修复上下文不能因文档矛盾而崩
(incident-projection-repair-blind-fixture-kind-*, incident-delivery-shape-repair-context-crash-*)。

不变量:
  I1 `_projection_repair_context` 面对一份 delivery requirements 不可准入的文档(正是需要
     修复的那种)必须返回上下文而不是抛 ProductProfileError——否则 CLI 以回溯退出、
     autopilot 只看到 CLI_PAYLOAD_MISSING;
  I2 fixture blueprint 的投影拒绝(input_kind 与交付输入不符等)携带 loc/msg,修复不再盲修。
"""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    _projection_repair_context,
    normalize_draft_document,
    public_validation_diagnostics,
)

_spec = importlib.util.spec_from_file_location(
    "_shape_fixtures", Path(__file__).with_name("test_delivery_shape_contradiction.py")
)
_fx = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fx)


def test_repair_context_survives_inadmissible_requirements() -> None:
    doc = _fx._with_output("text_artifact", "workspace_bundle")
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(doc, capability_goal=_fx._GOAL)
    context = _projection_repair_context(doc, caught.value)
    assert context["reason_code"] == "DELIVERY_SHAPE_SELF_CONTRADICTION"
    assert context["public_validation_errors"][0]["loc"] == "delivery_requirements.outputs.0.kind"
    assert context["preserve_delivery_requirements"]["outputs"][0]["kind"] == "text_artifact"
    assert context["selected_artifact"] is None


def test_fixture_input_kind_mismatch_names_the_blueprint_field() -> None:
    doc = copy.deepcopy(_fx._WORKSPACE_DOC)
    doc["fixture_blueprints"][1]["input_kind"] = "file"
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(doc, capability_goal=_fx._GOAL)
    assert str(caught.value) == "tool-draft:WORKSPACE_FIXTURE_INPUT_KIND_MISMATCH"
    rows = public_validation_diagnostics(caught.value)
    assert rows and rows[0]["loc"] == "fixture_blueprints.1.input_kind"
    assert "directory" in rows[0]["msg"] and "file" in rows[0]["msg"]


def test_missing_fixture_builder_names_the_field() -> None:
    doc = copy.deepcopy(_fx._WORKSPACE_DOC)
    doc["fixture_builder"] = "   "  # passes the schema's minLength, carries no source
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(doc, capability_goal=_fx._GOAL)
    assert str(caught.value) == "tool-draft:WORKSPACE_FIXTURE_BUILDER_REQUIRED"
    rows = public_validation_diagnostics(caught.value)
    assert rows and rows[0]["loc"] == "fixture_builder"
