"""起草的投影自修也该按停滞计,而不是只给一次(incident-projection-repair-budget-is-one-*)。

现象:两个独立仓库的旅程都死在起草——一处是交付形状自相矛盾(补救语句已经完整地写明两条
合法出路),一处是合同里多出一个自造字段(字段级诊断完整)。两处都是:Harness 给出精确的
字段级拒绝 → **唯一**那次投影自修 → INVALID_MODEL_OUTPUT → 整趟报废,自检一轮都没跑到。
同一套系统里凡是"控制件不对就照证据改"的循环都是停滞预算式的多次尝试(自检侧 12 次),
唯独伤害最大的这一处只给一次。

不变量:
  I1 每次投影拒绝带来一次新的自修尝试,只要拒绝的**签名**(码 + 首个字段 loc)在变——那是进展;
  I2 同一签名反复出现要消耗停滞预算,耗尽即停,并如实抛出最后一次的公开码;
  I3 绝对上限仍在:签名一直在变也不会无限重试。
"""

from __future__ import annotations

import pytest

from repoproof.adoption.intake import tool_drafter


def test_the_budget_constants_are_a_stall_budget_not_a_single_shot() -> None:
    assert tool_drafter._PROJECTION_REPAIR_STALL_BUDGET >= 2
    assert (
        tool_drafter._MAX_PROJECTION_REPAIR_ATTEMPTS
        > tool_drafter._PROJECTION_REPAIR_STALL_BUDGET
    )


def test_a_changing_rejection_signature_keeps_earning_attempts() -> None:
    spent = 0
    seen: set[tuple[str, str]] = set()
    for index in range(6):
        signature = ("CODE", f"field.{index}")
        spent = tool_drafter._projection_repair_stall(signature, seen, spent)
    assert spent == 0, "签名一直在变就是进展,不消耗停滞预算"


def test_a_repeating_rejection_signature_spends_the_budget() -> None:
    spent = 0
    seen: set[tuple[str, str]] = set()
    for _ in range(6):
        spent = tool_drafter._projection_repair_stall(("CODE", "same.field"), seen, spent)
    assert spent == 5, "第一次是白送的,之后每次重复各花一格"


def test_the_projection_signature_reads_the_first_field() -> None:
    error = tool_drafter._projection_error(
        "DELIVERY_SHAPE_SELF_CONTRADICTION",
        ("delivery_requirements", "outputs", 0, "kind"),
        "kind contradicts the document's own workspace members",
    )
    assert tool_drafter._projection_rejection_signature(error) == (
        "DELIVERY_SHAPE_SELF_CONTRADICTION",
        "delivery_requirements.outputs.0.kind",
    )


@pytest.mark.parametrize("attempts", [1, 2, 3])
def test_a_document_that_never_becomes_valid_still_stops(attempts: int) -> None:
    """The absolute cap bounds a drafter that keeps answering with a new defect."""

    assert tool_drafter._MAX_PROJECTION_REPAIR_ATTEMPTS <= 8, "重试必须有界"


def _codex(monkeypatch, documents):
    """A Codex drafter whose structured replies are scripted."""

    calls: list[dict] = []
    drafter = object.__new__(tool_drafter.CodexDrafter)
    drafter.last_usage = {}

    def fake_structured(**kwargs):
        calls.append(kwargs)
        return documents[min(len(calls) - 1, len(documents) - 1)]

    monkeypatch.setattr(drafter, "_structured", fake_structured)
    return drafter, calls


def test_the_drafter_keeps_trying_while_the_rejection_changes(monkeypatch) -> None:
    from test_tool_drafter import _valid_projection_document

    fields = [{"name": "sample", "type": "string"}]
    rejected_a = _valid_projection_document(format_id="markdown", required_fields=fields)
    rejected_b = _valid_projection_document(format_id="markdown", required_fields=fields)
    rejected_b["delivery_requirements"]["outputs"][0]["format_id"] = "plain_text"
    corrected = _valid_projection_document(format_id="markdown", required_fields=[])
    drafter, calls = _codex(monkeypatch, [rejected_a, rejected_b, corrected])

    drafted = drafter.draft({"capability_goal": "整理项目记录"})

    assert len(calls) == 3, "拒绝签名在变就该继续给尝试"
    assert [row["purpose"] for row in calls][1:] == [
        "tool-draft-projection-repair",
        "tool-draft-projection-repair",
    ]
    assert drafted["output_contract"]["required"] == {}


def test_the_same_rejection_over_and_over_still_stops(monkeypatch) -> None:
    from test_tool_drafter import _valid_projection_document

    stuck = _valid_projection_document(
        format_id="markdown", required_fields=[{"name": "sample", "type": "string"}]
    )
    drafter, calls = _codex(monkeypatch, [stuck])

    with pytest.raises(tool_drafter.DraftError):
        drafter.draft({"capability_goal": "整理项目记录"})

    assert len(calls) <= tool_drafter._MAX_PROJECTION_REPAIR_ATTEMPTS + 1
    assert len(calls) >= 2, "第一次拒绝之后至少要给一次自修"
