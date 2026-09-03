"""可复现探针看不见天级时钟读取,冻结件就成了定时炸弹(incident-wall-clock-date-embedded-undetected-*)。

现象:冻结的期望 SVG 里带着 `Generated with pygal ... on <今天>`——上游把生成日期写进注释,参考实现的
稳定化正则没盖到这种写法,隔 2 秒重跑的探针当然看不出天级漂移,任务就带着"只在今天成立"的黄金件
冻结了:明天参考实现自己就过不了自己的黄金件,所有 Agent 发都会 FAIL。

不变量:
  I1 `_wall_clock_date_findings(root, input_root)` 在生成的 UTF-8 文本文件里找**今天**(本地与 UTC)
     的日期字符串(ISO 与常见变体),输入树里本来就有的字符串不算;
  I2 可复现探针在树身份一致之后仍以 `WORKSPACE_REFERENCE_NOT_REPRODUCIBLE` /
     `WALL_CLOCK_DATE_EMBEDDED` 拒绝,诊断带 `path=WALL_CLOCK_DATE@line N: 摘录`(实际侧);
  I3 输入里本来就含今天日期的数据不触发。
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from repoproof.execution.workspace_bundle import WorkspaceBundleError
from repoproof.ui.services import product_jobs

_TODAY = datetime.date.today().isoformat()


def _tree(root: Path, *, stamp: str) -> Path:
    (root / "charts").mkdir(parents=True)
    (root / "charts" / "daily.svg").write_text(
        f"<svg>\n<!--Generated with acme 1.0 on {stamp}-->\n</svg>\n", encoding="utf-8"
    )
    (root / "README.md").write_text("# report\n", encoding="utf-8")
    return root


def test_findings_name_todays_date_in_generated_text_only(tmp_path: Path) -> None:
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "rows.csv").write_text("date,cost\n2024-07-02,1\n", encoding="utf-8")
    generated = _tree(tmp_path / "out", stamp=_TODAY)
    rows = product_jobs._wall_clock_date_findings(generated, input_root=inputs)
    assert rows and rows[0]["path"] == "charts/daily.svg" and rows[0]["locus"].startswith("line 2")
    assert _TODAY in rows[0]["locus"]
    # A date that the input itself carries is data, not a clock read.
    (inputs / "rows.csv").write_text(f"date,cost\n{_TODAY},1\n", encoding="utf-8")
    assert product_jobs._wall_clock_date_findings(generated, input_root=inputs) == []


def test_probe_rejects_a_reproducible_tree_that_embeds_today(tmp_path: Path, monkeypatch) -> None:
    class _Contract:
        limits = None

    expected = _tree(tmp_path / "expected", stamp=_TODAY)
    inputs = tmp_path / "input"
    inputs.mkdir()
    (inputs / "rows.csv").write_text("date,cost\n2024-07-02,1\n", encoding="utf-8")
    monkeypatch.setattr(product_jobs, "_REPRODUCIBILITY_GAP_SECONDS", 0)

    def rerun(target: Path) -> None:
        _tree(target, stamp=_TODAY)  # byte-identical rerun: the 2-second probe alone is blind

    with pytest.raises(WorkspaceBundleError) as caught:
        product_jobs._assert_reference_reproducible(
            expected_dir=expected, rerun_dir=tmp_path / "rerun", contract=_Contract(), rerun=rerun, input_root=inputs
        )
    assert caught.value.code == "WORKSPACE_REFERENCE_NOT_REPRODUCIBLE"
    assert "WALL_CLOCK_DATE_EMBEDDED" in caught.value.diagnostics
    assert any("charts/daily.svg=WALL_CLOCK_DATE@line 2" in item for item in caught.value.diagnostics)
