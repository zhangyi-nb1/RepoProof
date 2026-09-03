"""草稿 schema 拒绝也要点名字段、进有据修复(incident-projection-repair-blind-invalid-document-*)。

现象:起草在第一份模型文档就以 `tool-draft:INVALID_MODEL_OUTPUT:INVALID_DOCUMENT` 结束,
`draft_error_diagnostics=[]`——jsonschema 的拒绝被包成裸 DraftError:没有 json path、没有消息,
也不是 DraftProjectionError,所以有据的一次投影修复根本不跑。

不变量:
  I1 schema 拒绝是 DraftProjectionError(`tool-draft:INVALID_DOCUMENT`),公开诊断带 json path 与
     schema 消息(不含被拒文档本身);
  I2 投影修复上下文的 `public_validation_errors` 由同一诊断投影,修复者知道改哪个字段;
  I3 合法文档照旧编译。
"""

from __future__ import annotations

import copy

import pytest
from test_delivery_shape_contradiction import _GOAL, _WORKSPACE_DOC

from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    _projection_repair_context,
    normalize_draft_document,
    public_validation_diagnostics,
)


def _broken() -> dict:
    doc = copy.deepcopy(_WORKSPACE_DOC)
    doc["fixture_blueprints"] = "not-a-list"
    return doc


def test_schema_rejection_is_a_projection_error_with_the_json_path() -> None:
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(_broken(), capability_goal=_GOAL)
    assert str(caught.value) == "tool-draft:INVALID_DOCUMENT"
    rows = public_validation_diagnostics(caught.value)
    assert rows and rows[0]["loc"] == "fixture_blueprints"
    assert rows[0]["msg"] and "not-a-list" not in rows[0]["msg"]  # message, never the rejected value


def test_projection_repair_context_names_the_field() -> None:
    try:
        normalize_draft_document(_broken(), capability_goal=_GOAL)
    except DraftProjectionError as exc:
        context = _projection_repair_context(_broken(), exc)
    else:
        raise AssertionError("broken document must be rejected")
    errors = context["public_validation_errors"]
    assert errors and errors[0]["loc"] == "fixture_blueprints"


def test_valid_document_still_compiles() -> None:
    assert normalize_draft_document(copy.deepcopy(_WORKSPACE_DOC), capability_goal=_GOAL)["workspace_contract"]
