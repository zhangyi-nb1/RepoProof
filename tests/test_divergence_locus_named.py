"""分歧行必须说到位置,不能停在文件路径(incident-divergence-locus-not-named-*)。

现象:两个仓库上可复现探针连报 `<file>=BYTES_DIFFER`,一个是 zip 容器(哪个成员漂了没说),
一个是文本 SVG(哪一行、哪个 token 漂了没说);reference 修复只能猜,连修数轮不中。

不变量:
  I1 zip 容器:`locus` 点名第一个内容不同的成员名(顺序/压缩/时间戳差异仍是 ZIP_METADATA_ONLY);
  I2 文本文件:`locus` 给第一处不同的行号,附**实际侧**(reference 自己这次跑出来的)那一行的有界
     摘录,绝不摘录期望侧;
  I3 可复现探针的公开诊断把 locus 带上(`path=KIND@locus`)。
"""

from __future__ import annotations

import inspect
import io
import zipfile
from pathlib import Path

from repoproof.execution.workspace_bundle import build_artifact_manifest, manifest_divergence
from repoproof.ui.services import product_jobs


def _zip(members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members:
            archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), payload)
    return buffer.getvalue()


def _tree(root: Path, *, core: bytes, svg_line3: str) -> Path:
    (root / "charts").mkdir(parents=True)
    (root / "book.xlsx").write_bytes(_zip([("xl/workbook.xml", b"<workbook/>"), ("docProps/core.xml", core)]))
    (root / "charts" / "spend.svg").write_text(
        f"<svg>\n<g>\n<rect id='{svg_line3}'/>\n</g>\n</svg>\n", encoding="utf-8"
    )
    return root


def test_rows_name_the_member_and_the_line(tmp_path: Path) -> None:
    actual = _tree(tmp_path / "actual", core=b"<created>2026-09-03T11:00:01Z</created>", svg_line3="chart-9b1c")
    expected = _tree(tmp_path / "expected", core=b"<created>2026-09-03T10:59:58Z</created>", svg_line3="chart-3f2a")
    rows = manifest_divergence(
        build_artifact_manifest(actual), build_artifact_manifest(expected), actual_root=actual, expected_root=expected
    )
    by_path = {row["path"]: row for row in rows}
    assert by_path["book.xlsx"]["kind"] == "BYTES_DIFFER"
    assert by_path["book.xlsx"]["locus"] == "docProps/core.xml"
    svg = by_path["charts/spend.svg"]
    assert svg["kind"] == "BYTES_DIFFER" and svg["locus"].startswith("line 3")
    assert "chart-9b1c" in svg["locus"] and "chart-3f2a" not in svg["locus"]  # actual side only


def test_probe_diagnostics_carry_the_locus() -> None:
    source = inspect.getsource(product_jobs._assert_reference_reproducible)
    assert "locus" in source
