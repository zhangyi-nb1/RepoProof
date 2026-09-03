"""修复预算按"停滞"计,不按"次数"计(incident-selfcheck-bound-monotone-progress-*)。

现象:两个仓库上自检四轮四种缺陷各修一次、无一复发,却在固定的 3 次修复上限处停下——
上限是为单文件任务定的,多文件可运行工作区暴露的独立缺陷本来就多于三个。每一步都是进展的
过程被计数器杀掉,不是被证据杀掉。

不变量:
  I1 一次修复只有在它面对的失败签名(首个原因码 + 首行诊断)此前出现过时才消耗停滞预算;
     签名全新的修复不消耗;
  I2 仍有硬上限(`MAX_TOTAL_REPAIR_ROUNDS`)封顶总修复次数;
  I3 停滞预算与硬上限任一耗尽即停,记录逐轮保留。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.draft_selfcheck import (
    MAX_REPAIR_ROUNDS,
    MAX_TOTAL_REPAIR_ROUNDS,
    DraftSelfCheckRepairV1,
    DraftSelfCheckRoundV1,
)
from repoproof.ui.services import product_jobs


def _drive(monkeypatch, failures: list[tuple[str, str] | None]):
    """``failures[i]`` is the (code, diagnostic) the i-th check reports; None = pass."""

    checks: list[int] = []
    repairs: list[str] = []

    def fake_round(draft_dir, draft, *, round_index, **_extra):
        checks.append(round_index)
        item = failures[min(len(checks) - 1, len(failures) - 1)]
        if item is None:
            return DraftSelfCheckRoundV1(round=round_index, check_ok=True)
        code, diag = item
        return DraftSelfCheckRoundV1(round=round_index, check_ok=False, reason_codes=(code,), diagnostics=(diag,))

    def fake_repair(draft_dir, draft, *, target, failure, drafter, **_extra):
        repairs.append(target)
        return DraftSelfCheckRepairV1(target=target, attempts=1, outcome="APPLIED")

    monkeypatch.setattr(product_jobs, "_self_check_round", fake_round)
    monkeypatch.setattr(product_jobs, "_apply_draft_control_repair", fake_repair)
    rounds = product_jobs._self_check_repair_rounds(
        Path("/nonexistent"), {}, bound=MAX_REPAIR_ROUNDS, repair=True, drafter=object()
    )
    return rounds, repairs


def test_distinct_failures_do_not_spend_the_stall_budget(monkeypatch) -> None:
    assert MAX_REPAIR_ROUNDS == 3 and MAX_TOTAL_REPAIR_ROUNDS > MAX_REPAIR_ROUNDS
    failures = [
        ("WORKSPACE_REFERENCE_SMOKE_FAILED", "import placeholder"),
        ("WORKSPACE_REFERENCE_NOT_REPRODUCIBLE", "charts/a.svg=BYTES_DIFFER@line 2"),
        ("WORKSPACE_REFERENCE_EXECUTION_FAILED", "AttributeError"),
        ("WORKSPACE_REFERENCE_CONTRACT_FAILED", "WORKSPACE_FORMAT_INVALID"),
        None,
    ]
    rounds, repairs = _drive(monkeypatch, failures)
    assert len(repairs) == 4  # a fourth distinct defect still gets its repair
    assert rounds[-1].check_ok is True


def test_repeated_failures_still_stop_at_the_stall_bound(monkeypatch) -> None:
    same = ("WORKSPACE_REFERENCE_NOT_REPRODUCIBLE", "charts/a.svg=BYTES_DIFFER@line 2")
    rounds, repairs = _drive(monkeypatch, [same] * 10)
    assert len(repairs) == MAX_REPAIR_ROUNDS + 1  # first sight is free; every repeat spends one
    assert rounds[-1].check_ok is False


def test_hard_cap_bounds_even_monotone_progress(monkeypatch) -> None:
    failures = [("WORKSPACE_REFERENCE_EXECUTION_FAILED", f"Error {i}") for i in range(20)]  # distinct signatures
    rounds, repairs = _drive(monkeypatch, failures)
    assert len(repairs) == MAX_TOTAL_REPAIR_ROUNDS
