"""绝对上限是兜底,不是判官(incident-selfcheck-hard-cap-stops-progress-*)。

现象:三个仓库上自检连修六个**互不相同**的缺陷、无一签名复发,停滞预算一格未动,
却在绝对上限处停下——收敛过程被计数器杀掉,不是被证据杀掉。而且被上限掐断的那一轮
与"这个码根本无处可修"的那一轮在记录里长得一模一样(都没有 repair),调用方分不清
"还在收敛只是预算用完"和"这条路走不通"。

不变量:
  I1 每轮签名全新(单调进展)的自检,允许一路修到通过,不被绝对上限提前掐断;
  I2 绝对上限仍在——新签名无穷无尽时循环必须停;
  I3 被绝对上限终止的那一轮要自报预算耗尽,与"无路可修"终止的轮次可区分。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.draft_selfcheck import (
    MAX_REPAIR_ROUNDS,
    DraftSelfCheckRepairV1,
    DraftSelfCheckRoundV1,
)
from repoproof.ui.services import product_jobs

BUDGET_EXHAUSTED = "SELF_CHECK_REPAIR_BUDGET_EXHAUSTED"


def _drive(monkeypatch, failures: list[tuple[str, str] | None]):
    """``failures[i]`` is the (code, diagnostic) the i-th check reports; None = pass."""

    seen: list[int] = []
    repairs: list[str] = []

    def fake_round(draft_dir, draft, *, round_index, **_extra):
        seen.append(round_index)
        item = failures[min(len(seen) - 1, len(failures) - 1)]
        if item is None:
            return DraftSelfCheckRoundV1(round=round_index, check_ok=True)
        code, diag = item
        return DraftSelfCheckRoundV1(
            round=round_index, check_ok=False, reason_codes=(code,), diagnostics=(diag,)
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


def test_monotone_progress_runs_until_it_passes(monkeypatch) -> None:
    """一个可运行工作区有四个控制件,独立缺陷本来就可能多于半打;每个只修一次就是进展。"""

    failures: list[tuple[str, str] | None] = [
        ("WORKSPACE_RUNTIME_APPLICATION_MISSING", "runtime_python_entrypoint=app.py 未产出"),
        ("WORKSPACE_REFERENCE_EXECUTION_FAILED", "SyntaxError: line 12"),
        ("WORKSPACE_REFERENCE_NOT_REPRODUCIBLE", "out/a.xlsx=BYTES_DIFFER@docProps/core.xml"),
        ("WORKSPACE_REFERENCE_NOT_REPRODUCIBLE", "out/b.svg=BYTES_DIFFER@line 3"),
        ("WORKSPACE_REFERENCE_CONTRACT_FAILED", "WORKSPACE_EXTRA_FILE: notes.txt"),
        ("WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT", "TOTAL_ROW_MISSING"),
        ("WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT", "UNKNOWN_ACCOUNT_NOT_FLAGGED"),
        ("WORKSPACE_REFERENCE_SMOKE_FAILED", "exit 1: module not found"),
        None,
    ]
    rounds, repairs = _drive(monkeypatch, failures)
    assert len(repairs) == 8, "签名全新的修复不该被绝对上限提前掐断"
    assert rounds[-1].check_ok is True
    assert not any(BUDGET_EXHAUSTED in row for row in rounds[-1].diagnostics)


def test_endless_new_signatures_still_stop(monkeypatch) -> None:
    failures = [("WORKSPACE_REFERENCE_EXECUTION_FAILED", f"Error {i}") for i in range(60)]
    rounds, repairs = _drive(monkeypatch, failures)
    assert 0 < len(repairs) < 60, "绝对上限必须仍然存在"
    assert rounds[-1].check_ok is False


def test_ceiling_stop_is_distinguishable_from_no_route(monkeypatch) -> None:
    capped, _ = _drive(
        monkeypatch, [("WORKSPACE_REFERENCE_EXECUTION_FAILED", f"Error {i}") for i in range(60)]
    )
    assert any(BUDGET_EXHAUSTED in row for row in capped[-1].diagnostics), (
        "被绝对上限终止的轮次要自报预算耗尽"
    )

    unroutable, repairs = _drive(
        monkeypatch, [("WORKSPACE_RUNTIME_WHEELHOUSE_MISSING", "wheelhouse 缺失")] * 3
    )
    assert repairs == [], "环境类失败本就不交给模型"
    assert not any(BUDGET_EXHAUSTED in row for row in unroutable[-1].diagnostics), (
        "无路可修不是预算耗尽,不能混为一谈"
    )
