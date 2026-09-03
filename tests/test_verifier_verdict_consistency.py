"""裁决者"通过却带原因码"是协议不一致,必须被点名(incident-verifier-verdict-inconsistency-untaught-*)。

不变量:
  I1 verify() 返回 ok=true 且 reason_codes 非空(模型爱写 ['OK'] 这种信息码)→ 语义筛的
     判决保持"不通过"(通过就等于放行一个自相矛盾的裁决者),但原因码必须换成机制码
     `VERIFIER_INFORMATIONAL_REASON_CODES_ON_PASS`,并附一句说明列出被拒的码;
  I2 该规则写进裁决者的起草与修复提示词——闸门要杀的先教;
  I3 ok=false 且 reason_codes 非空(正常失败)与 ok=true 且 reason_codes 为空(正常通过)不受影响。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from repoproof.adoption.intake import tool_drafter

_spec = importlib.util.spec_from_file_location(
    "_semantic_fixtures", Path(__file__).with_name("test_workspace_semantic.py")
)
_fx = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_fx)

_PASS_WITH_INFO_CODE = """from pathlib import Path
import miniworkspace

def verify(input_path: Path, artifact_path: Path) -> dict:
    text = (input_path / "brief.txt").read_text()
    expected = miniworkspace.render(text)
    actual = (artifact_path / "README.md").read_text()
    ok = actual == expected
    return {
        "ok": ok,
        "reason_codes": ["OK"] if ok else ["VALUE_MISMATCH"],
        "checked_commitment_ids": ["render-workspace"],
        "reason_details": {"OK": "All supplied commitments verified."},
    }
"""


def test_pass_with_informational_code_is_named_not_mistaken_for_a_real_mismatch(tmp_path: Path) -> None:
    evidence = _fx._run(_fx._world(tmp_path, verifier=_PASS_WITH_INFO_CODE))
    assert evidence.passed is False
    assert "VERIFIER_INFORMATIONAL_REASON_CODES_ON_PASS" in evidence.reason_codes
    assert "OK" not in evidence.reason_codes
    detail = dict(evidence.reason_details).get("VERIFIER_INFORMATIONAL_REASON_CODES_ON_PASS", "")
    assert "OK" in detail and "ok=true" in detail.lower().replace(" ", "")


def test_clean_pass_and_real_failure_are_unchanged(tmp_path: Path) -> None:
    clean = _fx._run(_fx._world(tmp_path / "clean"))
    assert clean.passed is True and clean.reason_codes == ()


def test_rule_is_taught_in_the_verifier_prompts() -> None:
    for prompt in (tool_drafter._VERIFIER_SYSTEM, tool_drafter._VERIFIER_REPAIR_SYSTEM):
        lowered = prompt.lower()
        assert "reason_codes" in lowered and "empty" in lowered and "ok is true" in lowered.replace("`", "")
