"""按构造只属于判官的子诊断,永远发给判官(incident-binding-control-failure-routed-to-producer-*)。

现象:两个独立仓库上,分歧的子诊断是 Harness 自己跑的**绑定对照**——它证明"判官换了输入
仍然接受同一份产物",也就是判官的判决根本没依赖输入。这按构造只可能是判官侧的缺陷。可路由
是按同码计数器发牌的:判官的两个轮次早被前几轮的内容类子失败占掉,轮到绑定对照时就落到了
生产者、再落到合同——三次修复不可能修好一个只属于判官的缺陷。

不变量:
  I1 子诊断含绑定对照(`*_BINDING_CONTROL_FAILED`)或判官自陈类(`VERIFIER_INFORMATIONAL_*`)
     时,无论同码计数走到第几轮,一律路由到判官;
  I2 没有这类子诊断时,分歧仍按既定主人序列轮转(判官、判官、生产者、生产者、合同、构建器);
  I3 停滞预算照旧兜底:判官修不好时循环仍会停,不会无限重发。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.draft_selfcheck import (
    MAX_REPAIR_ROUNDS,
    DraftSelfCheckRepairV1,
    DraftSelfCheckRoundV1,
    repair_target_for,
)
from repoproof.ui.services import product_jobs

DISAGREEMENT = "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"
BINDING = (
    "INPUT_BINDING_CONTROL_FAILED: the verifier still accepted the same artifact "
    "when given a different input",
)
UPSTREAM_BINDING = ("UPSTREAM_RESULT_BINDING_CONTROL_FAILED: pinned upstream returned changed values",)
INFORMATIONAL = ("VERIFIER_INFORMATIONAL_OK: verifier returned ok with a reason code",)
CONTENT = ("TOTAL_ROW_MISSING: expected a summary row",)


def test_binding_control_always_routes_to_the_verifier() -> None:
    for diagnostics in (BINDING, UPSTREAM_BINDING, INFORMATIONAL):
        for round_index in range(1, 9):
            assert (
                repair_target_for(DISAGREEMENT, round_index=round_index, diagnostics=diagnostics)
                == "verifier"
            ), (diagnostics[0][:30], round_index)


def test_content_subfailures_keep_the_owner_sequence() -> None:
    sequence = [
        repair_target_for(DISAGREEMENT, round_index=i, diagnostics=CONTENT) for i in range(1, 7)
    ]
    assert sequence == ["verifier", "verifier", "reference", "reference", "contract", "builder"]


def test_the_budget_still_ends_an_unfixable_binding_control(monkeypatch) -> None:
    targets: list[str] = []

    def fake_round(draft_dir, draft, *, round_index, **_extra):
        return DraftSelfCheckRoundV1(
            round=round_index,
            check_ok=False,
            reason_codes=(DISAGREEMENT,),
            diagnostics=BINDING,
        )

    def fake_repair(draft_dir, draft, *, target, failure, drafter, **_extra):
        targets.append(target)
        return DraftSelfCheckRepairV1(target=target, attempts=1, outcome="APPLIED")

    monkeypatch.setattr(product_jobs, "_self_check_round", fake_round)
    monkeypatch.setattr(product_jobs, "_apply_draft_control_repair", fake_repair)
    rounds = product_jobs._self_check_repair_rounds(
        Path("/nonexistent"), {}, bound=MAX_REPAIR_ROUNDS, repair=True, drafter=object()
    )
    assert set(targets) == {"verifier"}
    assert len(targets) == MAX_REPAIR_ROUNDS + 1, "第一次是白送的,之后每次重复各花一格"
    assert rounds[-1].check_ok is False
