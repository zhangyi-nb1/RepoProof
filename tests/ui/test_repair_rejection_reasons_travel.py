"""修复被拒的理由必须留在记录里、传给下一次尝试(incident-contract-repair-rejection-opaque-*)。

现象:两个仓库上合同修复两次 ROLLED_BACK `WORKSPACE_CONTRACT_STRUCTURAL_REPAIR_INVALID_MODEL_OUTPUT`,
轮记录只有这个笼统码——是 schema 不合、角色集变了、尺子被削弱还是 smoke 参数越界,盘上没有;
`_repair_source` 的第二次尝试也只被告知"不符合 schema",不知道 Core 拒它的真实理由;
下一轮换人再修时同样一无所知。

不变量:
  I1 `_repair_source` 最终抛出的 DraftError 带内层拒绝码(消息里)与 Core 的诊断行;第二次尝试的
     用户消息里含上一次被拒的码与 loc;
  I2 修复记录 `DraftSelfCheckRepairV1.diagnostics` 保存这些诊断行(公开的 loc/msg,不含模型输出);
  I3 轮循环把同一目标此前被拒的诊断作为 `previous_rejections` 交给下一次修复。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from repoproof.adoption.intake.draft_selfcheck import DraftSelfCheckRepairV1, DraftSelfCheckRoundV1
from repoproof.adoption.intake.tool_drafter import DraftError, LiteLLMDrafter
from repoproof.ui.services import product_jobs

_spec = importlib.util.spec_from_file_location(
    "_contract_repair_fixtures", Path(__file__).with_name("test_selfcheck_contract_repair.py")
)
_fixtures = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fixtures)

_ROWS = [
    {
        "loc": "workspace_contract.rules[role=pages].validation_profile",
        "type": "validator_weakened",
        "msg": "html_v1 -> text_utf8_v1",
    }
]


def test_repair_source_keeps_the_inner_rejection_and_tells_the_retry_why() -> None:
    drafter = LiteLLMDrafter.__new__(LiteLLMDrafter)
    seen: list[str] = []

    def fake_once(system, user, *, schema, schema_name):
        seen.append(user)
        return '{"workspace_contract": {"rules": []}}'

    drafter._once_with_system = fake_once  # type: ignore[method-assign]

    def rejecting_normalizer(document):
        raise DraftError("workspace-contract-repair:VALIDATOR_WEAKENED", diagnostics=_ROWS)

    try:
        drafter._repair_source(
            context={"x": 1},
            system="s",
            schema={},
            schema_name="workspace_contract_structural_repair",
            normalizer=rejecting_normalizer,
        )
    except DraftError as exc:
        assert "VALIDATOR_WEAKENED" in str(exc)
        assert exc.diagnostics and exc.diagnostics[0]["loc"] == _ROWS[0]["loc"]
    else:
        raise AssertionError("rejected repair must raise")
    assert len(seen) == 2
    assert "VALIDATOR_WEAKENED" in seen[1] and _ROWS[0]["loc"] in seen[1]


class _RejectingDrafter:
    name = "scripted-drafter"

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def repair_workspace_contract(self, context):
        self.contexts.append(context)
        raise DraftError(
            "workspace_contract_structural_repair:INVALID_MODEL_OUTPUT:VALIDATOR_WEAKENED", diagnostics=_ROWS
        )


def test_repair_record_carries_the_rejection_diagnostics_and_previous_rejections_reach_the_drafter(
    tmp_path: Path, monkeypatch
) -> None:
    draft_dir = _fixtures._draft_with_contract(tmp_path, monkeypatch)
    import yaml

    draft = yaml.safe_load((draft_dir / "draft.yaml").read_text(encoding="utf-8"))
    failure = DraftSelfCheckRoundV1(
        round=1,
        check_ok=False,
        reason_codes=("WORKSPACE_REFERENCE_CONTRACT_FAILED",),
        diagnostics=("WORKSPACE_RULE_OVERLAP", "WORKSPACE_RULE_OVERLAP: 'a' matches 'a' and '**'"),
    )
    drafter = _RejectingDrafter()
    record = product_jobs._apply_draft_control_repair(
        draft_dir,
        draft,
        target="contract",
        failure=failure,
        drafter=drafter,
        previous_rejections=("earlier: role set changed",),
    )
    assert record.outcome == "ROLLED_BACK"
    assert "VALIDATOR_WEAKENED" in (record.reason_code or "")
    assert record.diagnostics and _ROWS[0]["loc"] in record.diagnostics[0]
    assert drafter.contexts[0]["self_check_failure"]["previous_rejections"] == ["earlier: role set changed"]


def test_round_loop_hands_previous_rejections_to_the_next_attempt(monkeypatch) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    def fake_round(draft_dir, draft, *, round_index):
        return DraftSelfCheckRoundV1(
            round=round_index,
            check_ok=bool(seen and seen[-1][0] == "applied"),
            reason_codes=() if seen and seen[-1][0] == "applied" else ("WORKSPACE_REFERENCE_CONTRACT_FAILED",),
            diagnostics=("WORKSPACE_RULE_OVERLAP",),
        )

    outcomes = iter(["ROLLED_BACK", "APPLIED"])

    def fake_repair(
        draft_dir, draft, *, target, failure, drafter, same_code_repairs=0, previous_targets=(), previous_rejections=()
    ):
        outcome = next(outcomes)
        seen.append(("applied" if outcome == "APPLIED" else "rolled", tuple(previous_rejections)))
        return DraftSelfCheckRepairV1(
            target=target,
            attempts=1,
            outcome=outcome,
            reason_code=None if outcome == "APPLIED" else "X",
            diagnostics=("why: weakened",) if outcome != "APPLIED" else (),
        )

    monkeypatch.setattr(product_jobs, "_self_check_round", fake_round)
    monkeypatch.setattr(product_jobs, "_apply_draft_control_repair", fake_repair)
    product_jobs._self_check_repair_rounds(Path("/nonexistent"), {}, bound=3, repair=True, drafter=object())
    assert seen[0][1] == ()
    assert seen[1][1] == ("contract: why: weakened",)  # every owner hears what was refused before
