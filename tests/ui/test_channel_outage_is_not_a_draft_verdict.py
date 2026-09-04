"""通道断了不是草稿的错(incident-provider-interruption-recorded-as-fail-*)。

现象:自检修复中途外部网关掉线,连着三轮修复都以 `ANTHROPIC_GATEWAY_UNAVAILABLE` 记成
ROLLED_BACK,循环继续在一条死通道上烧预算,最后整趟旅程以"草稿自检失败"收场。同一件事实
——**没有任何修复真的发生过**——在起草者离线时判 UNAVAILABLE 并立刻停,在通道掉线时却
判成草稿的失败。外部中断被写进了任务的终态。

不变量:
  I1 明确的通道可用性失败判为 UNAVAILABLE,循环当轮停止;
  I2 模型真给了坏输出仍是 ROLLED_BACK——不许把模型的错算到通道头上;
  I3 UNAVAILABLE 那一轮记录在案(证据保留),不静默吞掉。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.adoption.intake.draft_selfcheck import DraftSelfCheckRepairV1, DraftSelfCheckRoundV1
from repoproof.ui.services import product_jobs

CHANNEL = [
    "semantic_verifier_contract_repair:ANTHROPIC_GATEWAY_UNAVAILABLE",
    "ANTHROPIC_GATEWAY_TIMEOUT: upstream took too long",
    "workspace_reference_execution_repair:ANTHROPIC_GATEWAY_CONNECTIVITY_ERROR",
    "ANTHROPIC_GATEWAY_RATE_LIMITED",
    "PROVIDER_UNAVAILABLE",
]
MODEL = [
    "semantic_verifier_contract_repair:INVALID_MODEL_OUTPUT",
    "WORKSPACE_CONTRACT_REPAIR_NO_PROGRESS",
    "WORKSPACE_CONTRACT_REPAIR_WEAKENED_VALIDATOR",
    "workspace_reference_execution_repair:INVALID_DOCUMENT",
]


@pytest.mark.parametrize("message", CHANNEL)
def test_channel_failures_are_unavailable(message: str) -> None:
    assert product_jobs._repair_failure_outcome(message) == "UNAVAILABLE"


@pytest.mark.parametrize("message", MODEL)
def test_model_failures_still_roll_back(message: str) -> None:
    assert product_jobs._repair_failure_outcome(message) == "ROLLED_BACK"


def test_offline_drafter_still_unavailable() -> None:
    assert (
        product_jobs._repair_failure_outcome("DRAFT_CONTROL_REPAIR_REQUIRES_ONLINE_DRAFTER")
        == "UNAVAILABLE"
    )


def test_the_loop_stops_on_a_channel_outage(monkeypatch) -> None:
    targets: list[str] = []

    def fake_round(draft_dir, draft, *, round_index, **_extra):
        return DraftSelfCheckRoundV1(
            round=round_index,
            check_ok=False,
            reason_codes=("WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT",),
            diagnostics=("VALUE_MISMATCH",),
        )

    def fake_repair(draft_dir, draft, *, target, failure, drafter, **_extra):
        targets.append(target)
        return DraftSelfCheckRepairV1(
            target=target,
            attempts=0,
            outcome="UNAVAILABLE",
            reason_code="ANTHROPIC_GATEWAY_UNAVAILABLE",
        )

    monkeypatch.setattr(product_jobs, "_self_check_round", fake_round)
    monkeypatch.setattr(product_jobs, "_apply_draft_control_repair", fake_repair)
    rounds = product_jobs._self_check_repair_rounds(
        Path("/nonexistent"), {}, bound=3, repair=True, drafter=object()
    )

    assert targets == ["verifier"], "死通道上不该继续发牌"
    assert rounds[-1].repair is not None
    assert rounds[-1].repair.outcome == "UNAVAILABLE"
    assert rounds[-1].repair.reason_code == "ANTHROPIC_GATEWAY_UNAVAILABLE"
