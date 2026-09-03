"""合同结构修复不许削弱尺子(incident-contract-repair-weakens-validator-*;安全/假成功类,首起即修)。

现象:某案例第 1 轮诊断点名一个 html_v1 页面引用外部 CDN;合同修复"APPLIED"后
第 2 轮外链码消失——修复者把 html_v1 降成 text_utf8_v1,离线检查随之蒸发,而交付站点仍引用 CDN。

不变量:
  I1 每个 role 的 validation_profile、executable 不得改变;allow_extra_files 不得由 false 变 true;
     entrypoints 不得改变 —— 违者 `workspace-contract-repair:VALIDATOR_WEAKENED`,诊断点名
     role/字段/前后值;
  I2 收紧(allow_extra_files true→false)、改 pattern/cardinality/limits、改 smoke 参数照旧允许;
  I3 提示词明说:内容类诊断(HTML 外链、格式失败)不归合同修,改字节是生产者的事。
"""

from __future__ import annotations

import copy

import pytest

from repoproof.adoption.intake import tool_drafter
from repoproof.adoption.intake.tool_drafter import DraftError, normalize_workspace_contract_repair

_CURRENT = {
    "schema_version": 1,
    "rules": [
        {
            "path_pattern": "site/**/*.html",
            "role": "rendered pages",
            "media_type": "text/html",
            "validation_profile": "html_v1",
            "min_count": 1,
            "max_count": 64,
        },
        {
            "path_pattern": "README.md",
            "role": "human documentation",
            "media_type": "text/markdown",
            "validation_profile": "text_utf8_v1",
        },
    ],
    "allow_extra_files": False,
    "entrypoints": [],
    "runnable": False,
    "smoke_command": [],
    "smoke_timeout_seconds": 30,
    "require_offline_wheelhouse": False,
}


def _repair(mutate) -> dict:
    proposed = copy.deepcopy(_CURRENT)
    mutate(proposed)
    return {"workspace_contract": proposed}


def _weakened_error(mutate) -> DraftError:
    with pytest.raises(DraftError) as caught:
        normalize_workspace_contract_repair(_repair(mutate), current=copy.deepcopy(_CURRENT))
    return caught.value


def test_profile_downgrade_is_rejected_and_named() -> None:
    def downgrade(doc: dict) -> None:
        doc["rules"][0]["validation_profile"] = "text_utf8_v1"

    error = _weakened_error(downgrade)
    assert str(error) == "workspace-contract-repair:VALIDATOR_WEAKENED"
    joined = " | ".join(str(row) for row in error.diagnostics)
    assert "rendered pages" in joined and "html_v1" in joined and "text_utf8_v1" in joined


def test_allow_extra_files_cannot_flip_open() -> None:
    def open_up(doc: dict) -> None:
        doc["allow_extra_files"] = True

    error = _weakened_error(open_up)
    assert str(error) == "workspace-contract-repair:VALIDATOR_WEAKENED"
    assert any("allow_extra_files" in str(row) for row in error.diagnostics)


def test_executable_flag_cannot_change() -> None:
    def flip(doc: dict) -> None:
        doc["rules"][1]["executable"] = True

    assert str(_weakened_error(flip)) == "workspace-contract-repair:VALIDATOR_WEAKENED"


def test_structural_changes_and_tightening_still_pass() -> None:
    def restructure(doc: dict) -> None:
        doc["rules"][0]["path_pattern"] = "site/*/**/*.html"
        doc["rules"][0]["max_count"] = 128

    repaired = normalize_workspace_contract_repair(_repair(restructure), current=copy.deepcopy(_CURRENT))
    assert repaired["rules"][0]["path_pattern"] == "site/*/**/*.html"

    current_open = copy.deepcopy(_CURRENT)
    current_open["allow_extra_files"] = True
    closed = copy.deepcopy(_CURRENT)
    tightened = normalize_workspace_contract_repair({"workspace_contract": closed}, current=current_open)
    assert tightened["allow_extra_files"] is False


def test_contract_repair_prompt_disowns_content_diagnostics() -> None:
    text = tool_drafter._WORKSPACE_CONTRACT_REPAIR_SYSTEM.lower()
    assert "validation_profile" in text and "never" in text
    assert "html_external_resource" in text or "content" in text
