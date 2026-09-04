"""兜底额度按"退掉的缺陷"长,不按固定次数(incident-selfcheck-hard-cap-stops-progress-*)。

现象:把绝对上限从 6 抬到 12 之后,一趟**每一轮都在退掉缺陷**的自检又在 12 处被截断——
规则重叠、条目基数、外部资源、站内断链、格式非法、构建日期漂移、上游调用未观测、两个绑定
对照、三处判别力缺口逐个解决,最后停在一个全新的缺陷上。数字换了,角色没换:不读证据的
那个界仍然在替收敛中的旅程判死。

只把数字再调大就是照着一个仓库调参。改成按进展发额度:每退掉一个此前存在的子失败,就多
挣一格;原地打转的旅程拿不到额外额度,停滞预算照旧当判官,另有一个绝对天花板兜住灾难。

不变量:
  I1 一轮退掉了此前存在的子失败 = 进展,额度 +1;
  I2 没退掉任何东西的轮次不挣额度(超集或原样);
  I3 额度有天花板,收敛再久也不会无限跑。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.draft_selfcheck import (
    ABSOLUTE_REPAIR_CEILING,
    MAX_REPAIR_ROUNDS,
    MAX_TOTAL_REPAIR_ROUNDS,
    DraftSelfCheckRepairV1,
    DraftSelfCheckRoundV1,
    retired_any_defect,
)
from repoproof.ui.services import product_jobs


def test_retiring_a_subfailure_is_progress() -> None:
    assert retired_any_defect(("A,B,C",), ("A,B",)) is True
    assert retired_any_defect(("A,B",), ("A,B,C",)) is False
    assert retired_any_defect(("A,B",), ("A,B",)) is False
    assert retired_any_defect((), ("A",)) is False
    assert retired_any_defect(("A",), ()) is True


def test_the_ceiling_is_bounded() -> None:
    assert MAX_TOTAL_REPAIR_ROUNDS < ABSOLUTE_REPAIR_CEILING <= 40


def _drive(monkeypatch, failures):
    repairs: list[str] = []
    seen: list[int] = []

    def fake_round(draft_dir, draft, *, round_index, **_extra):
        seen.append(round_index)
        item = failures[min(len(seen) - 1, len(failures) - 1)]
        if item is None:
            return DraftSelfCheckRoundV1(round=round_index, check_ok=True)
        return DraftSelfCheckRoundV1(
            round=round_index,
            check_ok=False,
            reason_codes=("WORKSPACE_REFERENCE_EXECUTION_FAILED",),
            diagnostics=(item,),
        )

    def fake_repair(draft_dir, draft, *, target, failure, drafter, **_extra):
        repairs.append(target)
        return DraftSelfCheckRepairV1(target=target, attempts=1, outcome="APPLIED")

    monkeypatch.setattr(product_jobs, "_self_check_round", fake_round)
    monkeypatch.setattr(product_jobs, "_apply_draft_control_repair", fake_repair)
    rounds = product_jobs._self_check_repair_rounds(
        Path("/nonexistent"), {}, bound=MAX_REPAIR_ROUNDS, repair=True, drafter=object()
    )
    return rounds, repairs


def test_a_journey_that_keeps_retiring_defects_earns_more_than_the_base(monkeypatch) -> None:
    # Each round carries one fewer sub-failure than the last: pure convergence.
    codes = [f"D{i}" for i in range(ABSOLUTE_REPAIR_CEILING + 4)]
    failures = [",".join(codes[i:]) for i in range(len(codes))]
    _rounds, repairs = _drive(monkeypatch, failures)
    assert len(repairs) > MAX_TOTAL_REPAIR_ROUNDS, "退掉缺陷就该挣到额度"
    assert len(repairs) <= ABSOLUTE_REPAIR_CEILING, "天花板仍在"


def test_a_journey_that_retires_nothing_stays_at_the_base(monkeypatch) -> None:
    # The code set only ever grows: every round is a fresh signature (so the
    # stall budget never fires) yet nothing is ever actually retired.
    codes = [f"D{i}" for i in range(ABSOLUTE_REPAIR_CEILING + 4)]
    failures = [",".join(codes[: i + 1]) for i in range(len(codes))]
    _rounds, repairs = _drive(monkeypatch, failures)
    assert len(repairs) == MAX_TOTAL_REPAIR_ROUNDS, "原地打转不挣额度"
