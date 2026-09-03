"""verifier 判别力探针(incident-draft-controls-unverified-*)。

不变量:一个通过正控与三项反事实的 verifier,仍可能对交付文件的**内容**
毫无判别(只查存在/标题)。探针对每个非 Core 自有文件施加确定性内容变异
(改一字符/截去末行/翻一字节),verifier 必须至少拒绝其中一种;全部接受
= 该文件的语义没有被复核 = 公开缺口。Core 自有文件按模式排除。
"""

from __future__ import annotations

import sys
from pathlib import Path

from repoproof.verification.workspace_semantic import (
    probe_workspace_verifier_discrimination,
)

_CONTENT_VERIFIER = """from pathlib import Path
import miniworkspace


def verify(input_path: Path, artifact_path: Path) -> dict:
    text = (input_path / "brief.txt").read_text()
    expected = miniworkspace.render(text)
    ok = (artifact_path / "README.md").read_text() == expected
    ok = ok and (artifact_path / "data" / "table.csv").read_text().startswith("a,b\\n")
    return {"ok": ok, "reason_codes": [] if ok else ["VALUE_MISMATCH"], "checked_commitment_ids": ["render"]}
"""

_EXISTENCE_VERIFIER = """from pathlib import Path
import miniworkspace


def verify(input_path: Path, artifact_path: Path) -> dict:
    miniworkspace.render("x")
    ok = (artifact_path / "README.md").is_file() and (artifact_path / "data" / "table.csv").is_file()
    return {"ok": ok, "reason_codes": [] if ok else ["MISSING"], "checked_commitment_ids": ["render"]}
"""


def _world(tmp_path: Path, verifier: str) -> dict[str, Path]:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "miniworkspace.py").write_text(
        "def render(text):\n    return '# ' + text.strip() + '\\n'\n", encoding="utf-8"
    )
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "brief.txt").write_text("Experiment", encoding="utf-8")
    artifact = tmp_path / "artifact"
    (artifact / "data").mkdir(parents=True)
    (artifact / "README.md").write_text("# Experiment\n", encoding="utf-8")
    (artifact / "data" / "table.csv").write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    (artifact / "run.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    verifier_path = tmp_path / "semantic_verifier.py"
    verifier_path.write_text(verifier, encoding="utf-8")
    return {"upstream": upstream, "input": input_dir, "artifact": artifact, "verifier": verifier_path}


def _probe(world: dict[str, Path]):
    return probe_workspace_verifier_discrimination(
        verifier_source=world["verifier"],
        input_path=world["input"],
        artifact_dir=world["artifact"],
        python_exe=sys.executable,
        upstream_dir=world["upstream"],
        import_module="miniworkspace",
        excluded_patterns=("run.sh",),
        isolation_required=False,
    )


def test_content_recomputing_verifier_has_no_gap(tmp_path: Path) -> None:
    result = _probe(_world(tmp_path, _CONTENT_VERIFIER))
    assert result.ok is True
    assert result.gaps == ()
    assert {item.path for item in result.files} == {"README.md", "data/table.csv"}
    assert all(item.discriminated for item in result.files)
    assert any(m.result == "REJECTED" for item in result.files for m in item.mutations)


def test_existence_only_verifier_is_flagged_per_file(tmp_path: Path) -> None:
    result = _probe(_world(tmp_path, _EXISTENCE_VERIFIER))
    assert result.ok is False
    assert result.gaps == ("README.md", "data/table.csv")
    # 探针只做内容变异,不用「删文件」冒充判别力:存在性检查不算复核。
    assert all(m.kind != "delete" for item in result.files for m in item.mutations)


def test_core_owned_patterns_are_excluded(tmp_path: Path) -> None:
    result = _probe(_world(tmp_path, _CONTENT_VERIFIER))
    assert "run.sh" not in {item.path for item in result.files}
    assert result.probed_files == 2
