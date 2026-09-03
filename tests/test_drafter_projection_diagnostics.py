"""合同投影修复必须有证据(incident-drafter-projection-repair-blind-*)。

不变量:Core 拒绝一份模型合同时,拒绝的**公开字段级诊断**(位置/类型/信息,
不含模型原文之外的任何私有数据)必须 (a) 进入第二次起草的修复上下文,
(b) 随最终 DraftError 一起对外投影,让 CLI/autopilot/Studio 能记录;
只给一个 reason code 的修复是盲修,两个独立仓库已证明它成功率靠运气。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from repoproof.adoption.intake.tool_drafter import (
    DraftError,
    DraftProjectionError,
    _invalid_model_output_error,
    _projection_repair_context,
    public_validation_diagnostics,
)
from repoproof.domain.models import WorkspaceArtifactContractV1

_DELIVERY = {
    "inputs": [
        {"kind": "directory", "location": "local", "representation": "utf8_text", "format_label": "CSV", "role": "r"}
    ],
    "outputs": [{"kind": "directory", "format_id": "workspace_bundle", "format_label": "workspace", "role": "r"}],
    "network": "offline",
    "credentials": "none",
    "lifecycle": "per_invocation",
    "runtime": "local_cpu",
    "browser": "none",
    "external_side_effects": "none",
}


def _invalid_contract_error() -> DraftProjectionError:
    bad = {
        "schema_version": 1,
        "rules": [{"path_pattern": "book.xlsx", "role": "r", "media_type": "x", "validation_profile": "excel_v9"}],
    }
    try:
        WorkspaceArtifactContractV1.model_validate(bad)
    except ValidationError as exc:
        error = DraftProjectionError("tool-draft:WORKSPACE_CONTRACT_INVALID")
        error.__cause__ = exc
        return error
    raise AssertionError("contract unexpectedly valid")


def test_public_validation_diagnostics_project_location_and_type_only() -> None:
    error = _invalid_contract_error()
    diagnostics = public_validation_diagnostics(error)
    assert diagnostics, "field-level diagnostics must be extracted from the pydantic cause"
    first = diagnostics[0]
    assert first["loc"].startswith("rules.0.validation_profile")
    assert first["type"] in {"literal_error", "enum"}
    assert "excel_v9" not in first["loc"]
    assert set(first) == {"loc", "type", "msg"}


def test_projection_repair_context_carries_diagnostics() -> None:
    error = _invalid_contract_error()
    context = _projection_repair_context(
        {
            "delivery_requirements": _DELIVERY,
            "workspace_contract": {"rules": []},
            "fixture_builder": "x",
            "fixture_blueprints": [],
        },
        error,
    )
    assert context["reason_code"] == "WORKSPACE_CONTRACT_INVALID"
    assert context["public_validation_errors"][0]["loc"].startswith("rules.0.validation_profile")


def test_final_draft_error_carries_diagnostics_for_the_caller() -> None:
    error = _invalid_contract_error()
    final = _invalid_model_output_error(error)
    assert isinstance(final, DraftError)
    assert str(final) == "tool-draft:INVALID_MODEL_OUTPUT:WORKSPACE_CONTRACT_INVALID"
    assert final.diagnostics and final.diagnostics[0]["loc"].startswith("rules.0.validation_profile")


def test_plain_value_error_cause_is_projected_as_a_stable_code() -> None:
    error = DraftProjectionError("tool-draft:WORKSPACE_CONTRACT_INVALID")
    error.__cause__ = ValueError("WORKSPACE_RUNTIME_ENTRYPOINT_MISSING")
    diagnostics = public_validation_diagnostics(error)
    assert diagnostics == [{"loc": "", "type": "value_error", "msg": "WORKSPACE_RUNTIME_ENTRYPOINT_MISSING"}]


def test_no_cause_yields_empty_diagnostics() -> None:
    assert public_validation_diagnostics(DraftProjectionError("tool-draft:X")) == []
    with pytest.raises(AttributeError):
        _ = DraftError("plain").diagnostics_missing  # 属性名不存在;仅验证类可实例化
