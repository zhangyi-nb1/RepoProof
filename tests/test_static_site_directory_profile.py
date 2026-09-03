"""static_site_v1 目录级 profile(协议冻结清单第七项;此前未实现,c5 只有逐文件外链检查)。

不变量:
  I1 `directory_profile_errors("static_site_v1", root)`:树内无任何 index.html →
     `WORKSPACE_SITE_INDEX_MISSING`;HTML 内部链接(href/src/action,非外链/锚点/mailto/data)
     解析不到树内文件 → `WORKSPACE_SITE_LINK_BROKEN`,点名文件与链接;目录链接可经其
     index.html 闭合;`..` 越出树顶记 broken;
  I2 合同新增可选 `directory_profiles`(默认空,旧冻结合同不受影响;未知名拒收);Core 与
     导出 runtime 两侧 `validate_workspace` 同尺执行(奇偶校验);
  I3 合同修复不得删除 directory profile(VALIDATOR_WEAKENED);
  I4 干净站点零行。
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from repoproof.adoption.delivery import portable_workspace_runtime as portable
from repoproof.adoption.delivery.portable_workspace_runtime import WorkspaceRuntimeError, directory_profile_errors
from repoproof.adoption.intake.tool_drafter import DraftError, normalize_workspace_contract_repair
from repoproof.domain.models import WorkspaceArtifactContractV1
from repoproof.execution.workspace_bundle import validate_workspace


def _site(root: Path, *, index: bool = True, broken: bool = False) -> Path:
    (root / "site" / "guide").mkdir(parents=True)
    (root / "site" / "style.css").write_text("body{}", encoding="utf-8")
    guide_name = "index.html" if index else "inner.html"
    guide_home = "../index.html" if index else "../page.html"
    (root / "site" / "guide" / guide_name).write_text(
        f'<html><body><a href="{guide_home}">home</a><a href="#top">top</a><a href="mailto:x@y">mail</a></body></html>',
        encoding="utf-8",
    )
    guide_link = "guide/" if index else "guide/inner.html"
    body = f'<link href="style.css" rel="stylesheet"><a href="{guide_link}">guide</a>'
    if broken:
        body += '<a href="missing/page.html">gone</a><img src="../escape.png">'
    (root / "site" / ("index.html" if index else "page.html")).write_text(
        f"<html><body>{body}</body></html>", encoding="utf-8"
    )
    return root


def test_clean_site_has_no_rows(tmp_path: Path) -> None:
    assert directory_profile_errors("static_site_v1", _site(tmp_path / "ws")) == []


def test_missing_index_and_broken_links_are_named(tmp_path: Path) -> None:
    rows = directory_profile_errors("static_site_v1", _site(tmp_path / "ws", index=False, broken=True))
    codes = [code for code, _ in rows]
    assert "WORKSPACE_SITE_INDEX_MISSING" in codes
    broken = [detail for code, detail in rows if code == "WORKSPACE_SITE_LINK_BROKEN"]
    assert any("missing/page.html" in detail and "site/page.html" in detail for detail in broken)
    assert any("../escape.png" in detail for detail in broken)


def test_unknown_profile_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "ws").mkdir()
    assert directory_profile_errors("made_up_v9", tmp_path / "ws") == [
        ("WORKSPACE_DIRECTORY_PROFILE_UNKNOWN", "made_up_v9")
    ]


_CONTRACT = {
    "schema_version": 1,
    "rules": [
        {
            "path_pattern": "site/**/*.html",
            "role": "pages",
            "media_type": "text/html",
            "validation_profile": "html_v1",
            "max_count": 16,
        },
        {
            "path_pattern": "site/**/*.css",
            "role": "styles",
            "media_type": "text/css",
            "validation_profile": "text_utf8_v1",
            "min_count": 0,
            "max_count": 16,
        },
    ],
    "allow_extra_files": False,
    "entrypoints": [],
    "runnable": False,
    "smoke_command": [],
    "smoke_timeout_seconds": 30,
    "require_offline_wheelhouse": False,
    "directory_profiles": ["static_site_v1"],
}


def test_core_and_exported_validators_share_the_ruler(tmp_path: Path) -> None:
    contract = WorkspaceArtifactContractV1.model_validate(_CONTRACT)
    good = _site(tmp_path / "good")
    result = validate_workspace(good, contract)
    assert result.ok, result.details
    portable.validate_workspace(good, contract.model_dump(mode="json"))

    bad = _site(tmp_path / "bad", index=False, broken=True)
    core = validate_workspace(bad, contract)
    assert "WORKSPACE_SITE_INDEX_MISSING" in core.reason_codes
    assert any("WORKSPACE_SITE_LINK_BROKEN" in row for row in core.details)
    with pytest.raises(WorkspaceRuntimeError) as caught:
        portable.validate_workspace(bad, contract.model_dump(mode="json"))
    assert caught.value.code.startswith("WORKSPACE_SITE_")


def test_old_contracts_without_the_field_still_validate() -> None:
    document = {k: v for k, v in _CONTRACT.items() if k != "directory_profiles"}
    assert WorkspaceArtifactContractV1.model_validate(document).directory_profiles == ()
    with pytest.raises(ValueError):
        WorkspaceArtifactContractV1.model_validate({**_CONTRACT, "directory_profiles": ["made_up_v9"]})


def test_contract_repair_cannot_drop_a_directory_profile() -> None:
    current = copy.deepcopy(_CONTRACT)
    proposed = copy.deepcopy(_CONTRACT)
    proposed["directory_profiles"] = []
    with pytest.raises(DraftError) as caught:
        normalize_workspace_contract_repair({"workspace_contract": proposed}, current=current)
    assert "VALIDATOR_WEAKENED" in str(caught.value)
    assert any("directory_profiles" in str(row) for row in caught.value.diagnostics)
