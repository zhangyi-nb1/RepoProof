"""结构校验的每个原因码都要带路径级公开细节(incident-structural-codes-without-path-detail-*)。

不变量:`validate_workspace` 返回的 `details` 对每个 reason code 说出是哪条路径/哪两条规则/
哪个外链;候选生成把这些细节作为 `WORKSPACE_REFERENCE_CONTRACT_FAILED` 的诊断交给修复。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.domain.models import WorkspaceArtifactContractV1
from repoproof.execution.workspace_bundle import validate_workspace


def _contract(rules, *, allow_extra=False) -> WorkspaceArtifactContractV1:
    return WorkspaceArtifactContractV1.model_validate(
        {
            "schema_version": 1,
            "rules": rules,
            "allow_extra_files": allow_extra,
            "entrypoints": [],
            "runnable": False,
            "smoke_command": [],
            "smoke_timeout_seconds": 5,
            "require_offline_wheelhouse": False,
            "limits": {
                "max_files": 20,
                "max_total_bytes": 20000,
                "max_file_bytes": 5000,
                "max_depth": 4,
                "max_path_bytes": 120,
            },
        }
    )


def _rule(pattern: str, profile: str = "text_utf8_v1", **extra) -> dict:
    return {
        "path_pattern": pattern,
        "role": f"r-{pattern}",
        "media_type": "text/plain",
        "validation_profile": profile,
        **extra,
    }


def test_overlap_extra_and_external_resource_are_named_by_path(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    (root / "site").mkdir(parents=True)
    (root / "site" / "index.html").write_text(
        '<html><head><link rel="stylesheet" href="https://cdn.example.com/x.css"></head><body>hi</body></html>',
        encoding="utf-8",
    )
    (root / "notes.txt").write_text("stray\n", encoding="utf-8")
    contract = _contract(
        [
            _rule("site/**/*.html", "html_v1", max_count=8),
            _rule("site/index.html", "html_v1"),
        ]
    )
    result = validate_workspace(root, contract)
    assert result.ok is False
    codes = set(result.reason_codes)
    assert {"WORKSPACE_RULE_OVERLAP", "WORKSPACE_EXTRA_FILE_FORBIDDEN"} <= codes
    details = list(result.details)
    joined = " | ".join(details)
    assert "site/index.html" in joined and "site/**/*.html" in joined  # overlap names path and both patterns
    assert "notes.txt" in joined  # extra file named
    assert "cdn.example.com" in joined or "WORKSPACE_HTML_EXTERNAL_RESOURCE: site/index.html" in joined


def test_missing_required_entry_names_the_pattern(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "README.md").write_text("# x\n", encoding="utf-8")
    result = validate_workspace(root, _contract([_rule("README.md"), _rule("summary.csv", "csv_v1")]))
    assert "WORKSPACE_REQUIRED_ENTRY_MISSING" in result.reason_codes
    assert any("summary.csv" in row for row in result.details)


def test_clean_workspace_has_no_details(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "README.md").write_text("# x\n", encoding="utf-8")
    result = validate_workspace(root, _contract([_rule("README.md")]))
    assert result.ok is True and result.details == ()
