"""冻结前的新输入探针拿不到模型时必须跳过,不能替旅程判死(本人今天引入的缺陷)。

现象:c5 第 19 轮第 4 轮以 `DRAFTERROR`(空诊断)终结旅程 —— 探针那次调用起草者失败,
`propose_workspace_fixture_candidates` 把 `DraftError` 的**类名**当公开码(消息整个丢掉),
而我加的探针接线又把"探针失败"直接当成该轮失败。探针是**加严的额外闸门**:它自己跑不起来时
应当跳过并留痕,只有生产者与裁决者**真分歧**才判该轮失败。

不变量:
  I1 探针返回起草者/供应商/Harness 侧失败(failure_owner != CONTRACT)→ 该轮继续走既有起草
     蓝图生成,并把跳过原因留在轮记录的诊断里;
  I2 探针返回语义分歧(failure_owner == CONTRACT)→ 该轮失败,带裁决者的码与细节;
  I3 候选生成把 DraftError 的公开消息当码,不再退化成类名 `DRAFTERROR`。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.tool_drafter import DraftError
from repoproof.ui.services import product_jobs


class _Probe:
    gaps: tuple[str, ...] = ()
    probed_files = 3


def _drive(monkeypatch, fresh: dict):
    calls: list[tuple[int, bool]] = []

    def fake_candidates(draft_dir, *, n, offline):
        calls.append((n, offline))
        if offline:
            return {"ok": True, "candidates": [{"a": 1}, {"b": 2}, {"c": 3}], "generation_id": "base"}
        return fresh

    monkeypatch.setattr(product_jobs, "propose_workspace_fixture_candidates", fake_candidates)
    monkeypatch.setattr(product_jobs, "_probe_draft_verifier_discrimination", lambda draft_dir, draft: _Probe())
    return product_jobs._self_check_round(Path("/nonexistent"), {}, round_index=1), calls


def test_drafter_side_probe_failure_is_skipped(monkeypatch) -> None:
    rnd, calls = _drive(
        monkeypatch,
        {
            "ok": False,
            "failure_owner": "EXTERNAL",
            "reason_codes": ["tool-draft:INVALID_MODEL_OUTPUT"],
            "error": "起草者不可用",
        },
    )
    assert rnd.check_ok is True, rnd.reason_codes
    assert [offline for _n, offline in calls] == [False, True]
    assert any("INVALID_MODEL_OUTPUT" in item for item in rnd.diagnostics)


def test_harness_side_probe_failure_is_skipped(monkeypatch) -> None:
    rnd, _calls = _drive(
        monkeypatch,
        {"ok": False, "failure_owner": "HARNESS", "reason_codes": ["FIXTURE_BUILDER_ISOLATION_UNAVAILABLE"]},
    )
    assert rnd.check_ok is True


def test_real_disagreement_still_fails_the_round(monkeypatch) -> None:
    rnd, _calls = _drive(
        monkeypatch,
        {
            "ok": False,
            "failure_owner": "CONTRACT",
            "reason_codes": ["WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"],
            "diagnostics": ["TOTAL_MISMATCH: expected 3 observed 2"],
        },
    )
    assert rnd.check_ok is False
    assert rnd.reason_codes[0] == "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"
    assert any("expected 3 observed 2" in item for item in rnd.diagnostics)


def test_draft_error_keeps_its_public_message_as_the_code(tmp_path: Path, monkeypatch) -> None:
    import repoproof.adoption.intake.tool_drafter as drafter

    monkeypatch.setattr(product_jobs, "_validated_draft_dir", lambda p, require_existing=True: (tmp_path, ""))

    def boom(*_args, **_kwargs):
        raise DraftError("tool-draft:REQUIRES_ONLINE_DRAFTER")

    monkeypatch.setattr(drafter, "online_drafter", boom)
    payload = product_jobs.propose_workspace_fixture_candidates(tmp_path, n=1, offline=False)
    assert payload["ok"] is False
    assert "DRAFTERROR" not in payload["reason_codes"]
