"""Fresh-audit 提案循环的接缝钉(incident-fresh-audit-proposal-batch-abort-*)。

不变量:模型提案的唯一"定义域 oracle"是冻结 builder/reference 的真实
物化 —— 提示词鼓励 Unicode/边界场景,而 builder 从不声明参数域。因此:
  I1 每个提案独立物化;冻结件对**某一个**提案的域外拒绝(builder 抛、
     reference 判 UserInputError)是该提案的记录结果,不许连坐已物化的
     同批候选;
  I2 拒绝必须带稳定公开分类(异常类名),并作为排除反馈进入有界再提案;
  I3 系统性故障(builder 不安全/解释器缺失/隔离不可用等)仍即时中止;
  I4 门槛不降:在界内没有任何提案物化 = 失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.adoption.intake.workspace_fixtures import (
    FixtureBlueprintV1,
    FixtureBuilderError,
)
from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services.product_jobs import (
    materialize_fresh_workspace_proposals,
)


def _bp(identifier: str, **parameters) -> FixtureBlueprintV1:
    return FixtureBlueprintV1(
        blueprint_id=identifier,
        title=identifier,
        scenario=f"scenario {identifier}",
        input_kind="file",
        parameters=parameters or {"kind": "text"},
    )


def _record(blueprint: FixtureBlueprintV1) -> dict[str, object]:
    return {"blueprint_id": blueprint.blueprint_id, "candidate_token": "t-" + blueprint.blueprint_id}


def test_one_rejected_proposal_does_not_discard_materialized_sibling() -> None:
    bad = _bp("unicode-page", kind="text", lines=["Résumé"])
    good = _bp("empty-page", kind="text", lines=[])

    def propose(_context):
        return [bad, good]

    def materialize(blueprint):
        if blueprint is bad:
            raise FixtureBuilderError("FIXTURE_BUILDER_FAILED", "UnicodeEncodeError")
        return _record(blueprint)

    records, rejected = materialize_fresh_workspace_proposals(
        propose=propose,
        materialize=materialize,
        proposal_context={"how_many": 2, "excluded_blueprint_ids": [], "excluded_parameter_fingerprints": []},
        requested=2,
        max_rounds=1,
    )
    assert [r["blueprint_id"] for r in records] == ["empty-page"]
    assert rejected == [{
        "blueprint_id": "unicode-page",
        "stage": "builder",
        "reason_code": "FIXTURE_BUILDER_FAILED",
        "public_class": "UnicodeEncodeError",
    }]


def test_rejections_feed_back_as_exclusions_within_bound() -> None:
    bad = _bp("unicode-page", kind="text", lines=["Résumé"])
    good1 = _bp("plain-page", kind="text", lines=["plain"])
    good2 = _bp("table-page", kind="table")
    contexts: list[dict] = []

    def propose(context):
        contexts.append(context)
        return [bad, good1] if len(contexts) == 1 else [good2]

    def materialize(blueprint):
        if blueprint is bad:
            raise WorkspaceBundleError("WORKSPACE_REFERENCE_FIXTURE_REJECTED", "UserInputError")
        return _record(blueprint)

    records, rejected = materialize_fresh_workspace_proposals(
        propose=propose,
        materialize=materialize,
        proposal_context={
            "how_many": 2,
            "excluded_blueprint_ids": ["seed-a"],
            "excluded_parameter_fingerprints": ["f" * 64],
        },
        requested=2,
        max_rounds=2,
    )
    assert [r["blueprint_id"] for r in records] == ["plain-page", "table-page"]
    assert len(contexts) == 2
    second = contexts[1]
    assert "seed-a" in second["excluded_blueprint_ids"]
    assert "unicode-page" in second["excluded_blueprint_ids"]
    assert "plain-page" in second["excluded_blueprint_ids"]
    assert len(second["excluded_parameter_fingerprints"]) == 3
    assert second["rejected_proposals"] == [{
        "blueprint_id": "unicode-page",
        "stage": "reference",
        "reason_code": "WORKSPACE_REFERENCE_FIXTURE_REJECTED",
        "public_class": "UserInputError",
    }]
    assert rejected and rejected[0]["stage"] == "reference"
    # 原 context 不被就地污染
    assert contexts[0]["excluded_blueprint_ids"] == ["seed-a"]


def test_systemic_builder_failure_still_aborts_immediately() -> None:
    bad = _bp("any-page")
    calls = []

    def propose(_context):
        calls.append(1)
        return [bad, _bp("other-page")]

    def materialize(blueprint):
        raise FixtureBuilderError("FIXTURE_BUILDER_UNSAFE")

    with pytest.raises(FixtureBuilderError) as caught:
        materialize_fresh_workspace_proposals(
            propose=propose, materialize=materialize,
            proposal_context={"how_many": 2}, requested=2, max_rounds=2,
        )
    assert caught.value.code == "FIXTURE_BUILDER_UNSAFE"
    assert len(calls) == 1


def test_all_rejected_within_bound_yields_no_records_and_stops_at_bound() -> None:
    rounds = []

    def propose(context):
        rounds.append(context)
        return [_bp(f"p{len(rounds)}-a"), _bp(f"p{len(rounds)}-b")]

    def materialize(blueprint):
        raise FixtureBuilderError("FIXTURE_BUILDER_FAILED", "ValueError")

    records, rejected = materialize_fresh_workspace_proposals(
        propose=propose, materialize=materialize,
        proposal_context={"how_many": 2}, requested=2, max_rounds=2,
    )
    assert records == []
    assert len(rejected) == 4
    assert len(rounds) == 2


def test_duplicate_of_existing_fixture_is_skipped_without_counting_as_rejection() -> None:
    dup = _bp("dup-page")
    good = _bp("new-page")

    def materialize(blueprint):
        return None if blueprint is dup else _record(blueprint)

    records, rejected = materialize_fresh_workspace_proposals(
        propose=lambda _c: [dup, good], materialize=materialize,
        proposal_context={"how_many": 2}, requested=1, max_rounds=1,
    )
    assert [r["blueprint_id"] for r in records] == ["new-page"]
    assert rejected == []


def test_stops_once_requested_count_is_reached() -> None:
    seen = []

    def materialize(blueprint):
        seen.append(blueprint.blueprint_id)
        return _record(blueprint)

    records, _ = materialize_fresh_workspace_proposals(
        propose=lambda _c: [_bp("a"), _bp("b"), _bp("c")], materialize=materialize,
        proposal_context={"how_many": 2}, requested=2, max_rounds=3,
    )
    assert len(records) == 2 and seen == ["a", "b"]


def test_helper_is_the_single_owner_of_fresh_audit_materialization() -> None:
    """守卫:真实提案函数必须经由本 helper,不许再长出第二条裸循环。"""
    source = Path(__file__).resolve().parents[1] / "src" / "repoproof" / "ui" / "services" / "product_jobs.py"
    text = source.read_text(encoding="utf-8")
    start = text.index("def _propose_workspace_audit_candidates(")
    end = text.index("\ndef ", start + 1)
    body = text[start:end]
    assert "materialize_fresh_workspace_proposals(" in body
    assert "for blueprint in proposed:" not in body
