"""上游一致性选取器的钉死(M2-e · G2 第二层)。

选取必须确定性、命中为准、不硬凑;真 pdfplumber 树做集成锚(资源护栏)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.adoption.intake.upstream_conformance import (
    precheck_upstream_conformance,
    select_upstream_tests,
)

REPO = Path(__file__).resolve().parents[1]
PDFPLUMBER = REPO / "upstream-cache" / "upstream-7d4f2f582f2d"


def _up(tmp: Path) -> Path:
    root = tmp / "up"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_table_extract.py").write_text(
        "def test_table_basic():\n    pass\n\n"
        "def test_table_nested():\n    pass\n", encoding="utf-8")
    (root / "tests" / "test_misc.py").write_text(
        "def test_other():\n    pass\n", encoding="utf-8")
    (root / "tests" / "test_render.py").write_text(
        "def test_render_table():\n    pass\n", encoding="utf-8")
    return root


def test_selection_ranks_by_hits_and_is_deterministic(tmp_path):
    root = _up(tmp_path)
    got = select_upstream_tests(root, ["table"])
    assert got == ["tests/test_table_extract.py", "tests/test_render.py"]
    assert select_upstream_tests(root, ["table"]) == got     # 确定性


def test_selection_caps_and_empty_cases(tmp_path):
    root = _up(tmp_path)
    assert select_upstream_tests(root, ["table"], max_files=1) == [
        "tests/test_table_extract.py"]
    assert select_upstream_tests(root, ["zzz"]) == []        # 零命中不硬凑
    assert select_upstream_tests(root, []) == []
    assert select_upstream_tests(tmp_path / "none", ["table"]) == []


def test_precheck_green_and_failing(tmp_path):
    import sys

    root = _up(tmp_path)
    rec = precheck_upstream_conformance(
        root, ["tests/test_table_extract.py"], Path(sys.executable))
    assert rec["status"] == "PASS" and rec["selected"]
    assert precheck_upstream_conformance(root, [], Path(sys.executable)) == {
        "selected": [], "status": "EMPTY"}
    (root / "tests" / "test_bad.py").write_text(
        "import nonexistent_dep_xyz\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        precheck_upstream_conformance(root, ["tests/test_bad.py"],
                                      Path(sys.executable))


@pytest.mark.skipif(not PDFPLUMBER.is_dir(),
                    reason="pdfplumber 钉版树不在本机;clone v0.11.10 后可跑")
def test_selection_on_real_pdfplumber():
    got = select_upstream_tests(PDFPLUMBER, ["table"])
    assert got, "真树上 table 词根必须有命中"
    assert all(r.startswith("tests/") and "table" in r.lower() or r
               for r in got)
    assert len(got) <= 3
