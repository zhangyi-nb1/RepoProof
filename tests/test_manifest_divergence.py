"""黄金树不一致必须能说出"哪条路径、什么性质"(观测仪器透明律)。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from repoproof.execution.workspace_bundle import build_artifact_manifest, manifest_divergence


def _zip(path: Path, *, stamp: tuple[int, int, int, int, int, int]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in (("[Content_Types].xml", b"<Types/>"), ("ppt/slide1.xml", b"<p/>")):
            info = zipfile.ZipInfo(name, date_time=stamp)
            archive.writestr(info, payload)


def test_divergence_classifies_zip_metadata_content_missing_and_extra(tmp_path: Path) -> None:
    actual, expected = tmp_path / "actual", tmp_path / "expected"
    actual.mkdir()
    expected.mkdir()
    _zip(actual / "deck.pptx", stamp=(2026, 9, 2, 12, 8, 58))
    _zip(expected / "deck.pptx", stamp=(2026, 9, 2, 11, 52, 54))
    (actual / "notes.md").write_text("a\n", encoding="utf-8")
    (expected / "notes.md").write_text("b\n", encoding="utf-8")
    (expected / "only-expected.txt").write_text("x\n", encoding="utf-8")
    (actual / "only-actual.txt").write_text("y\n", encoding="utf-8")

    rows = manifest_divergence(
        build_artifact_manifest(actual),
        build_artifact_manifest(expected),
        actual_root=actual,
        expected_root=expected,
    )
    # ``locus`` (which member/line drifted) is covered by test_divergence_locus_named.
    assert [{k: v for k, v in row.items() if k != "locus"} for row in rows] == [
        {"path": "deck.pptx", "kind": "ZIP_METADATA_ONLY"},
        {"path": "notes.md", "kind": "BYTES_DIFFER"},
        {"path": "only-actual.txt", "kind": "EXTRA"},
        {"path": "only-expected.txt", "kind": "MISSING"},
    ]


def test_identical_trees_have_no_divergence(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("same\n", encoding="utf-8")
    manifest = build_artifact_manifest(root)
    assert manifest_divergence(manifest, manifest, actual_root=root, expected_root=root) == []
