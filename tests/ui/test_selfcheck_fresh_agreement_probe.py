"""冻结前要用一个没见过的输入探一次 reference↔裁决者一致性(incident-frozen-controls-disagree-on-fresh-input-*)。

现象:两个任务版本真发都过了(其中一例 4 步),导出后新输入抽查在候选提议步
`WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT`——冻结的两件控制件只在起草的 3–4 个蓝图上
证明过一致,第一个新输入就分歧;而新输入的提议与物化机制在起草期本来就存在(offline=False)。

不变量:
  I1 自检轮先用在线提议**两个**新蓝图(v2:一个不够,冻结后抽查仍分歧)物化并跑冻结前的
     reference 与裁决者;分歧即该轮失败,带裁决者原因码与细节,进既有 verifier→verifier→reference 修复;
  I2 新输入探针先于基础生成运行,基础生成仍是最新一代(确认样例不受影响);
  I3 没有在线起草者时探针跳过,不阻塞离线自检。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.intake.tool_drafter import DraftError
from repoproof.ui.services import product_jobs


class _Probe:
    """Lightweight stand-in for the discrimination probe result."""

    gaps: tuple[str, ...] = ()
    probed_files = 3


def _install(monkeypatch, fresh_result):
    calls: list[tuple[int, bool]] = []

    def fake_candidates(draft_dir, *, n, offline):
        calls.append((n, offline))
        if offline:
            return {"ok": True, "candidates": [{"a": 1}, {"b": 2}, {"c": 3}], "generation_id": "generation-base"}
        if isinstance(fresh_result, Exception):
            raise fresh_result
        return fresh_result

    monkeypatch.setattr(product_jobs, "propose_workspace_fixture_candidates", fake_candidates)
    monkeypatch.setattr(product_jobs, "_probe_draft_verifier_discrimination", lambda draft_dir, draft: _Probe())
    return calls


def test_fresh_disagreement_fails_the_round_with_the_verifier_details(tmp_path: Path, monkeypatch) -> None:
    calls = _install(
        monkeypatch,
        {
            "ok": False,
            "reason_codes": ["WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"],
            "diagnostics": ["TOTAL_MISMATCH", "TOTAL_MISMATCH: expected total 3 but observed 2 in summary.txt"],
        },
    )
    (tmp_path / "fixture_blueprints.json").write_text('{"blueprints": [{}, {}, {}]}', encoding="utf-8")
    rnd = product_jobs._self_check_round(tmp_path, {}, round_index=1)
    assert rnd.check_ok is False
    assert rnd.reason_codes[0] == "WORKSPACE_REFERENCE_VERIFIER_SEMANTIC_DISAGREEMENT"
    assert any("expected total 3" in item for item in rnd.diagnostics)
    assert calls == [
        (2, False)
    ]  # two fresh scenarios, probed first; a failing probe ends the round before the drafted generation


def test_offline_drafter_skips_the_probe(tmp_path: Path, monkeypatch) -> None:
    calls = _install(monkeypatch, DraftError("tool-draft:REQUIRES_ONLINE_DRAFTER"))
    (tmp_path / "fixture_blueprints.json").write_text('{"blueprints": [{}, {}, {}]}', encoding="utf-8")
    rnd = product_jobs._self_check_round(tmp_path, {}, round_index=1)
    assert rnd.check_ok is True
    assert [offline for _n, offline in calls] == [False, True]
