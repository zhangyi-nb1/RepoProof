"""改了控制件而失败的措辞纹丝不动,就该说出来(incident-ineffective-owner-not-named-*)。

现象:两个独立仓库上,同一个控制件被连续修了三到五次——每次修复都 APPLIED、前后哈希不同、
源码确实变了——而失败的**原话一个字都没变**。一处是上游自陈的环境错误(源码检出没构建数据
文件),没有任何参考实现能修好它;一处是判官对某个文件的同一句判词。记录里这些轮次和"模型
没写对"长得一模一样,于是一趟因环境不可用而注定失败的旅程,读起来像是模型不争气。

这不是启发式猜测,是一条可判定的推断:**改了 X 而证据不动,失败就不依赖 X。**

不变量:
  I1 连续两次以上"控制件真的变了、证据逐字不变"后,终局轮点名这个无效的主人;
  I2 证据只要变过(哪怕只变一行),就不算无效——修复是有效果的;
  I3 回滚/未应用的修复不参与计数——它本来就没改动什么。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.draft_selfcheck import (
    INEFFECTIVE_OWNER,
    MAX_REPAIR_ROUNDS,
    DraftSelfCheckRepairV1,
    DraftSelfCheckRoundV1,
)
from repoproof.ui.services import product_jobs

_CODE = "WORKSPACE_REFERENCE_EXECUTION_FAILED"


def _drive(monkeypatch, diagnostics_per_round, *, outcome="APPLIED", changed=True):
    calls: list[int] = []

    def fake_round(draft_dir, draft, *, round_index, **_extra):
        calls.append(round_index)
        rows = diagnostics_per_round[min(len(calls) - 1, len(diagnostics_per_round) - 1)]
        return DraftSelfCheckRoundV1(
            round=round_index, check_ok=False, reason_codes=(_CODE,), diagnostics=rows
        )

    def fake_repair(draft_dir, draft, *, target, failure, drafter, **_extra):
        return DraftSelfCheckRepairV1(
            target=target,
            attempts=1,
            outcome=outcome,
            before_sha256="a" * 64,
            after_sha256=("b" if changed else "a") * 64,
        )

    monkeypatch.setattr(product_jobs, "_self_check_round", fake_round)
    monkeypatch.setattr(product_jobs, "_apply_draft_control_repair", fake_repair)
    return product_jobs._self_check_repair_rounds(
        Path("/nonexistent"), {}, bound=MAX_REPAIR_ROUNDS, repair=True, drafter=object()
    )


def test_an_owner_with_no_effect_is_named(monkeypatch) -> None:
    rounds = _drive(monkeypatch, [("RuntimeError: the pinned upstream is not usable",)])
    final = rounds[-1]
    named = [row for row in final.diagnostics if INEFFECTIVE_OWNER in row]
    assert named, f"终局轮要点名无效的主人,实际:{final.diagnostics}"
    assert "reference" in named[0]


def test_evidence_that_moves_is_not_ineffective(monkeypatch) -> None:
    # Every round says something new, so no repair is ever shown to be useless.
    rounds = _drive(monkeypatch, [(f"RuntimeError: run {i}",) for i in range(40)])
    assert not any(INEFFECTIVE_OWNER in row for row in rounds[-1].diagnostics)


def test_a_rolled_back_repair_does_not_count(monkeypatch) -> None:
    rounds = _drive(monkeypatch, [("RuntimeError: same",)], outcome="ROLLED_BACK")
    assert not any(INEFFECTIVE_OWNER in row for row in rounds[-1].diagnostics)


def test_an_applied_repair_that_changed_nothing_does_not_count(monkeypatch) -> None:
    rounds = _drive(monkeypatch, [("RuntimeError: same",)], changed=False)
    assert not any(INEFFECTIVE_OWNER in row for row in rounds[-1].diagnostics)
