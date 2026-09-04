"""Harness 自己写的补救语句不能比它自己的通道还宽。

现象:一份自相矛盾的交付形状被精确命名了——loc 指到字段、msg 写明"必须改成
kind='directory' 配 format_id='workspace_bundle'"——可这句 303 字符的话经过公开诊断投影
时被 240 字符的上限**从中间切断**,恰好停在 `format_id='work`。模型拿到的是一句没说完的
指令,一次投影自修当然修不好,整趟旅程死在起草阶段。冲突成员列得越全,话被切得越早。

这条不靠"两个仓库各一起"来立案:它是 Harness 内部的自相矛盾——**写的话比自己的通道宽**
——不碰任何病例就能证明。既有测试之所以一直绿,是因为它构造的冲突列表短,恰好没超宽。

不变量:
  I1 Harness 自己写的补救语句能完整通过公开诊断投影(结尾不被切断);
  I2 真的超宽时截断**可见**,不把半句话当整句话交出去;
  I3 边界没放松:输入值仍然不进诊断。
"""

from __future__ import annotations

import copy

import pytest
from test_delivery_shape_contradiction import _GOAL, _WORKSPACE_DOC

from repoproof.adoption.intake.tool_drafter import (
    DraftProjectionError,
    normalize_draft_document,
    public_validation_diagnostics,
)


def _worst_case_contradiction() -> dict:
    """Every workspace member present, so the conflict list is at its longest."""

    doc = copy.deepcopy(_WORKSPACE_DOC)
    doc["delivery_requirements"]["outputs"][0]["kind"] = "binary_artifact"
    doc["delivery_requirements"]["outputs"][0]["format_id"] = "workspace_bundle"
    return doc


def test_the_whole_remediation_sentence_survives_the_projection() -> None:
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(_worst_case_contradiction(), capability_goal=_GOAL)
    rows = public_validation_diagnostics(caught.value)
    assert rows, "矛盾必须被命名"
    msg = rows[0]["msg"]
    assert "format_id='workspace_bundle'" in msg, "补救值不能被切掉"
    assert msg.rstrip().endswith("tool"), f"补救语句被截断:...{msg[-40:]!r}"


def test_a_genuinely_oversized_message_is_visibly_truncated() -> None:
    from repoproof.adoption.intake import tool_drafter

    class _Oversized(ValueError):
        pass

    holder = DraftProjectionError("tool-draft:X")
    holder.__cause__ = _Oversized("x" * (tool_drafter._MAX_PUBLIC_DIAGNOSTIC_MSG + 500))
    rows = public_validation_diagnostics(holder)
    assert rows and len(rows[0]["msg"]) <= tool_drafter._MAX_PUBLIC_DIAGNOSTIC_MSG
    assert rows[0]["msg"].endswith("…"), "被截断就要看得出来"


def test_input_values_still_never_enter_diagnostics() -> None:
    with pytest.raises(DraftProjectionError) as caught:
        normalize_draft_document(_worst_case_contradiction(), capability_goal=_GOAL)
    blob = " ".join(row["msg"] for row in public_validation_diagnostics(caught.value))
    assert _GOAL not in blob
