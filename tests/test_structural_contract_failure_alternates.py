"""结构性合同失败在同一码上要轮换归属(incident-structural-contract-failure-never-alternates-*)。

现象:两个独立仓库(三轮、四轮),`WORKSPACE_REFERENCE_CONTRACT_FAILED` 带结构码全部派给
合同修复,每次"APPLIED"而码不变;写出这些路径的生产者从没拿到过票。与闭包分歧码同理:
同一码再次出现,说明另一侧才是噪声。

不变量:结构码首轮归合同,第二轮归 reference,第三轮再归合同;非结构码照旧直接归 reference。
"""

from __future__ import annotations

from repoproof.adoption.intake.draft_selfcheck import repair_target_for

_CODE = "WORKSPACE_REFERENCE_CONTRACT_FAILED"
_STRUCTURAL = ("WORKSPACE_RULE_OVERLAP", "WORKSPACE_RULE_OVERLAP: 'a.html' matches 'a.html' and '**/*.html'")


def test_structural_codes_alternate_contract_then_reference() -> None:
    assert repair_target_for(_CODE, round_index=1, diagnostics=_STRUCTURAL) == "contract"
    assert repair_target_for(_CODE, round_index=2, diagnostics=_STRUCTURAL) == "reference"
    assert repair_target_for(_CODE, round_index=3, diagnostics=_STRUCTURAL) == "contract"


def test_content_codes_go_straight_to_the_producer() -> None:
    content = ("WORKSPACE_HTML_EXTERNAL_RESOURCE", "WORKSPACE_HTML_EXTERNAL_RESOURCE: 'x.html' — https://cdn")
    assert repair_target_for(_CODE, round_index=1, diagnostics=content) == "reference"
    assert repair_target_for(_CODE, round_index=2, diagnostics=content) == "reference"
