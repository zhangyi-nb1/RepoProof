"""判别力缺口要说清"什么样的改动溜过去了"(incident-discrimination-gap-diagnostics-bare-path-*)。

现象:两个独立仓库上,判官修复连打四轮都堵不上 `VERIFIER_DISCRIMINATION_GAP`,而交给修复
模型的诊断只有**文件路径**。探针明明逐个变异地知道自己改了什么(kind)、判官怎么反应
(ACCEPTED / REJECTED / PROTOCOL_ERROR),这些事实一个都没随行。更糟的是:"每次变异都被
接受"(判官不判别)和"每次变异都让判官崩了"(判官根本没跑完)在记录里长得一模一样,
可它们要求的修法完全相反。

不变量:
  I1 缺口诊断给出路径**和**溜过去的变异种类;
  I2 判官在全部变异上都出错时,诊断说的是"出错",不是"接受";
  I3 缺口文件之外的已判别文件不进诊断。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from repoproof.ui.services import product_jobs


def _probe(files):
    rows = tuple(
        SimpleNamespace(
            path=path,
            discriminated=any(r == "REJECTED" for _k, r in mutations),
            mutations=tuple(SimpleNamespace(kind=k, result=r) for k, r in mutations),
        )
        for path, mutations in files
    )
    return SimpleNamespace(
        probed_files=len(rows),
        files=rows,
        gaps=tuple(row.path for row in rows if not row.discriminated),
        ok=all(row.discriminated for row in rows),
    )


def _round(monkeypatch, probe):
    monkeypatch.setattr(product_jobs, "_probe_draft_verifier_discrimination", lambda *_a, **_k: probe)
    monkeypatch.setattr(
        product_jobs,
        "_self_check_candidates",
        lambda *_a, **_k: {"ok": True, "generation_id": "g", "candidates": [object()]},
        raising=False,
    )
    return product_jobs._discrimination_gap_diagnostics(probe)


def test_gap_diagnostic_names_the_mutations_that_slipped_through() -> None:
    probe = _probe(
        [
            ("site/faq/index.html", [("byte_flip", "ACCEPTED"), ("truncate", "ACCEPTED")]),
            ("site/index.html", [("byte_flip", "REJECTED")]),
        ]
    )
    rows = product_jobs._discrimination_gap_diagnostics(probe)
    assert len(rows) == 1
    assert "site/faq/index.html" in rows[0]
    assert "byte_flip" in rows[0] and "truncate" in rows[0]
    assert "site/index.html" not in " ".join(rows)


def test_a_verifier_that_errors_is_not_reported_as_accepting() -> None:
    probe = _probe(
        [("charts/a.svg", [("byte_flip", "PROTOCOL_ERROR"), ("truncate", "PROTOCOL_ERROR")])]
    )
    rows = product_jobs._discrimination_gap_diagnostics(probe)
    assert len(rows) == 1
    row = rows[0]
    assert "PROTOCOL_ERROR" in row or "错误" in row
    assert "ACCEPTED" not in row and "接受" not in row


def test_paths_still_travel_when_the_probe_reports_no_detail() -> None:
    probe = SimpleNamespace(probed_files=1, files=(), gaps=("only/path.html",), ok=False)
    rows = product_jobs._discrimination_gap_diagnostics(probe)
    assert rows == ("only/path.html",)


def test_the_round_carries_the_detailed_rows(tmp_path: Path, monkeypatch) -> None:
    probe = _probe([("a.html", [("byte_flip", "ACCEPTED")])])
    rows = _round(monkeypatch, probe)
    assert rows and "byte_flip" in rows[0]
