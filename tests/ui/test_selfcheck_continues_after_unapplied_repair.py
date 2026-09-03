"""一次没应用上的修复不等于自检终局(incident-selfcheck-stops-at-first-unapplied-repair-*)。

现象:c6 合同修复 NO_PROGRESS、c7 合同修复 INVALID_MODEL_OUTPUT / 裁决者修复 NO_PROGRESS,
自检都在预算还剩的情况下立刻结束;`repair_target_for` 设计好的
verifier→verifier→reference 顺序根本走不到。

不变量:
  I1 修复 ROLLED_BACK/NO_PROGRESS 后,草稿没变,循环**不重跑候选生成**,直接把同一份失败
     交给路由表的下一位(同码计数 +1);
  I2 只有预算耗尽、检查通过、无人可修、或起草者离线(UNAVAILABLE)才停;
  I3 每一次修复尝试都占预算,记录逐轮保留。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.draft_selfcheck import DraftSelfCheckRepairV1, DraftSelfCheckRoundV1
from repoproof.ui.services import product_jobs

_DISAGREEMENT = "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"


def _failing(round_index: int) -> DraftSelfCheckRoundV1:
    return DraftSelfCheckRoundV1(
        round=round_index,
        check_ok=False,
        reason_codes=(_DISAGREEMENT,),
        diagnostics=("INPUT_CELLS_INVALID",),
    )


def _drive(monkeypatch, outcomes: list[str], *, bound: int = 3):
    checks: list[int] = []
    targets: list[str] = []

    def fake_round(draft_dir: Path, draft: dict, *, round_index: int):
        checks.append(round_index)
        if targets and outcomes[len(targets) - 1] == "APPLIED":
            return DraftSelfCheckRoundV1(round=round_index, check_ok=True)
        return _failing(round_index)

    def fake_repair(draft_dir, draft, *, target, failure, drafter, same_code_repairs=0, previous_targets=(), **_extra):
        targets.append(target)
        outcome = outcomes[len(targets) - 1]
        return DraftSelfCheckRepairV1(
            target=target,
            attempts=1,
            outcome=outcome,
            reason_code=None if outcome == "APPLIED" else "SEMANTIC_VERIFIER_REPAIR_NO_PROGRESS",
        )

    monkeypatch.setattr(product_jobs, "_self_check_round", fake_round)
    monkeypatch.setattr(product_jobs, "_apply_draft_control_repair", fake_repair)
    rounds = product_jobs._self_check_repair_rounds(
        Path("/nonexistent"), {}, bound=bound, repair=True, drafter=object()
    )
    return rounds, checks, targets


def test_rolled_back_repair_hands_the_same_failure_to_the_next_owner(monkeypatch) -> None:
    rounds, checks, targets = _drive(monkeypatch, ["ROLLED_BACK", "ROLLED_BACK", "APPLIED"])
    assert targets == ["verifier", "verifier", "reference"]
    # One generation before the first repair, one after the applied repair — never in between.
    assert checks == [1, 4]
    assert rounds[-1].check_ok is True
    assert [r.repair.outcome for r in rounds if r.repair is not None] == ["ROLLED_BACK", "ROLLED_BACK", "APPLIED"]


def test_budget_still_bounds_the_attempts(monkeypatch) -> None:
    rounds, checks, targets = _drive(monkeypatch, ["ROLLED_BACK"] * 5, bound=3)
    # The bound is a stall budget: the first attempt at a new failure is free,
    # every repeat of the same failure spends one (test_selfcheck_bound_counts_stalls).
    assert len(targets) == 4
    assert checks == [1]
    assert rounds[-1].check_ok is False


def test_offline_drafter_stops_immediately(monkeypatch) -> None:
    rounds, checks, targets = _drive(monkeypatch, ["UNAVAILABLE", "APPLIED"])
    assert targets == ["verifier"]
    assert rounds[-1].repair is not None and rounds[-1].repair.outcome == "UNAVAILABLE"
