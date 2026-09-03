"""verifier 修复观察必须让裁决者看见它判的东西(incident-verifier-repair-observation-thin-*)。

不变量:观察保持来源安全(不给 reference 源码),但对文本工件给出**有界摘录**
(不止首行),对 zip 容器给出成员名,对其他二进制给出魔数;总量封顶。
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from repoproof.ui.services import product_jobs


def _expected_tree(tmp_path: Path) -> Path:
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "README.md").write_text(
        "# 报告\n\n## 输入契约\n- invoices.csv: id,amount\n\n"
        "## 生成的工作簿\n- Sheet `对账`: 列 id, amount, status\n\n## 异常规则\n- amount<0 => 异常\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(expected / "book.xlsx", "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
    (expected / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    (expected / "vendor").mkdir()
    (expected / "vendor" / "x.whl").write_bytes(b"PK\x03\x04junk")
    state = {
        "schema_version": 1,
        "generation_id": "generation-1-abcdef01",
        "records": [{"expected_dir": str(expected)}],
    }
    (tmp_path / product_jobs._WORKSPACE_FIXTURE_STATE).write_text(json.dumps(state), encoding="utf-8")
    return expected


def test_observation_carries_bounded_excerpts_members_and_magic(tmp_path: Path) -> None:
    _expected_tree(tmp_path)
    observation = product_jobs._self_check_artifact_observation(tmp_path, excluded=("vendor/*",))
    by_path = {row["path"]: row for row in observation["files"]}
    assert set(by_path) == {"README.md", "book.xlsx", "chart.png"}
    readme = by_path["README.md"]
    assert readme["first_line"] == "# 报告"
    assert "## 异常规则" in readme["excerpt"] and readme["line_count"] == 10
    assert by_path["book.xlsx"]["zip_members"] == ["[Content_Types].xml", "xl/workbook.xml"]
    assert "excerpt" not in by_path["book.xlsx"]
    assert by_path["chart.png"]["magic"] == "89504e470d0a1a0a"
    assert "excerpt" not in by_path["chart.png"]


def test_observation_excerpts_are_bounded(tmp_path: Path) -> None:
    expected = tmp_path / "expected"
    expected.mkdir()
    (expected / "big.txt").write_text("x" * 50_000, encoding="utf-8")
    state = {
        "schema_version": 1,
        "generation_id": "generation-1-abcdef01",
        "records": [{"expected_dir": str(expected)}],
    }
    (tmp_path / product_jobs._WORKSPACE_FIXTURE_STATE).write_text(json.dumps(state), encoding="utf-8")
    observation = product_jobs._self_check_artifact_observation(tmp_path, excluded=())
    row = observation["files"][0]
    assert len(row["excerpt"]) <= product_jobs._OBSERVATION_EXCERPT_CHARS
    assert row["excerpt_truncated"] is True
