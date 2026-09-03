"""分歧证据的主人不止两个(incident-disagreement-subdiagnostic-owner-ignored-*)。

现象:两个独立仓库上,参考实现与判官"语义分歧"的子诊断分别点名了**第三方**主人——
一处是合同的文件规则(合同刚以 EXTRA_FILE_FORBIDDEN 把某路径判为多余,判官下一轮就喊
该文件缺失),一处是夹具构建器(判官说读不懂喂进来的输入)。路由器对这个原因码只按
同码计数器在判官/生产者之间发牌,五次修复没有一次落在能修的人身上;而停滞预算把
"同一签名再来一次"一律算停滞,于是循环在真正的主人上场前就被判死。

不变量:
  I1 该原因码的主人序列覆盖全部四个控制件:判官、判官、生产者、生产者、合同、构建器;
  I2 停滞预算计的是"同一个主人对同一份证据重复同一尝试";把同一份证据交给**尚未上场**
     的主人是另一次尝试,不消耗预算;
  I3 主人是有限的:主人轮完后同一签名仍会耗尽预算而停,不会跑到绝对上限。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.draft_selfcheck import (
    MAX_REPAIR_ROUNDS,
    MAX_TOTAL_REPAIR_ROUNDS,
    DraftSelfCheckRepairV1,
    DraftSelfCheckRoundV1,
    repair_target_for,
)
from repoproof.ui.services import product_jobs

DISAGREEMENT = "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"


def _drive(monkeypatch, failures: list[tuple[str, str] | None]):
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


def test_every_control_gets_a_turn_on_a_disagreement() -> None:
    """判官两轮、生产者两轮之后,合同与构建器也必须各得一轮。"""

    sequence = [repair_target_for(DISAGREEMENT, round_index=i, diagnostics=()) for i in range(1, 7)]
    assert sequence == ["verifier", "verifier", "reference", "reference", "contract", "builder"]


def test_handing_the_same_evidence_to_a_new_owner_is_not_a_stall(monkeypatch) -> None:
    same = (DISAGREEMENT, "WORKBOOK_MISSING: expected file in output directory, observed none")
    _rounds, repairs = _drive(monkeypatch, [same] * 20)
    assert repairs[:6] == ["verifier", "verifier", "reference", "reference", "contract", "builder"]
    assert len(repairs) > MAX_REPAIR_ROUNDS + 1, "换一个尚未上场的主人不算重复同一尝试"


def test_owners_run_out_and_the_budget_still_ends_it(monkeypatch) -> None:
    same = (DISAGREEMENT, "INPUT_UNPARSEABLE: observed no parseable rows in input")
    rounds, repairs = _drive(monkeypatch, [same] * 30)
    assert len(repairs) < MAX_TOTAL_REPAIR_ROUNDS, "主人轮完后要被停滞预算终止,不是被绝对上限"
    assert rounds[-1].check_ok is False
