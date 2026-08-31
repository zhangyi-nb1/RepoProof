"""FailureAssessmentV1 · Gate 2 投影的钉死(纯读取侧,合成 report 矩阵)。

九种 Product 终止码各至少一条合成 report;泄漏负控(detail 里塞真值,
投影任何字段不得含它);同 report 重复投影逐字节一致;历史不回写
(输入 dict 不被修改)。
"""

from __future__ import annotations

import json

from repoproof.adoption.repair.failure_assessment import (
    assess_report,
    derive_repair_metrics,
    product_stop_code,
)


def _report(**over) -> dict:
    base = {
        "verdict": "FAIL",
        "gate_reasons": [],
        "repair": {"rounds_run": 3, "best_round": 1, "stop_reason": "stagnation",
                   "pending_scope_change": None},
        "public_passed_by_round": [0, 0, 0],
        "capability": "", "policy": "", "budget_exhausted": None,
    }
    base.update(over)
    return base


def test_all_nine_stop_codes_have_a_deterministic_source():
    cases = {
        "NO_REPAIR_NEEDED": _report(
            verdict="PASS_ADAPTED",
            repair={"rounds_run": 1, "stop_reason":
                    "all_public_green_pending_verification"}),
        "REPAIR_SUCCEEDED": _report(
            verdict="PASS_ADAPTED", public_passed_by_round=[2, 5],
            repair={"rounds_run": 2, "stop_reason":
                    "all_public_green_pending_verification"}),
        "STOP_NEEDS_HUMAN": _report(
            repair={"rounds_run": 1, "stop_reason": "scope_change_pending_user",
                    "pending_scope_change": {"ask": "扩输入域"}}),
        "STOP_HARNESS_OR_EXTERNAL": _report(verdict="BLOCKED"),
        "STOP_SCOPE_DRIFT": _report(gate_reasons=[
            "PolicyVerifier: adaptation files 647 > max_patch_files 12"]),
        "STOP_HIDDEN_FAILURE": _report(
            gate_reasons=["CapabilityVerifier: failing: test_held_example_1"],
            public_passed_by_round=[5],
            repair={"rounds_run": 1, "stop_reason":
                    "all_public_green_pending_verification"}),
        "STOP_BUDGET_EXHAUSTED": _report(
            repair={"rounds_run": 3, "stop_reason": "max_rounds"}),
        "STOP_NO_PROGRESS": _report(),
        # NON_REPAIRABLE 由上层评估器给(合同欠定类);投影层不虚构来源,
        # 用显式 state 通道:
        "STOP_NON_REPAIRABLE": None,
    }
    for want, rep in cases.items():
        if rep is None:
            continue
        assert product_stop_code(rep) == want, (want, product_stop_code(rep))


def test_receipt_failure_is_hidden_face():
    rep = _report(receipt_verification={"ok": False,
                                        "reason": "RECEIPT_VERIFICATION_FAILED"},
                  repair={"rounds_run": 1, "stop_reason":
                          "all_public_green_pending_verification"})
    assert product_stop_code(rep) == "STOP_HIDDEN_FAILURE"
    a = assess_report(rep)
    assert "UPSTREAM_ADOPTION_FAILED" in a.reason_codes
    assert a.failure_owner == "AGENT"


def test_harness_side_receipt_error_is_external_bucket():
    rep = _report(gate_reasons=["RECEIPT_VERIFIER_ERROR"])
    assert product_stop_code(rep) == "STOP_HARNESS_OR_EXTERNAL"
    assert assess_report(rep).recommended_action == "RETRY_INFRASTRUCTURE"


def test_provider_outage_does_not_masquerade_as_hidden_or_agent_failure():
    rep = _report(
        gate_reasons=["CapabilityVerifier: failing: test_held_example_1"],
        repair={
            "rounds_run": 1,
            "stop_reason": "non_repairable_failure",
            "failure_owner": "EXTERNAL",
            "reason_codes": ["PROVIDER_UNAVAILABLE"],
        },
    )
    a = assess_report(rep)
    assert a.product_stop_code == "STOP_HARNESS_OR_EXTERNAL"
    assert a.failure_owner == "EXTERNAL"
    assert a.recommended_action == "RETRY_INFRASTRUCTURE"
    assert "PROVIDER_UNAVAILABLE" in a.reason_codes
    assert "HIDDEN_ACCEPTANCE_FAILED" not in a.reason_codes


def test_output_contract_mismatch_is_contract_owner():
    rep = _report(gate_reasons=["[tool-output-contract] mismatch"],
                  repair={"rounds_run": 3, "stop_reason": "max_rounds"})
    a = assess_report(rep)
    assert a.failure_owner == "CONTRACT"
    assert a.repairability == "NEEDS_HUMAN"
    assert "OUTPUT_CONTRACT_MISMATCH" in a.reason_codes


def test_leak_negative_control_secret_never_survives_projection():
    """detail 里塞进 held-out 真值与路径:投影全字段不得含它。"""
    secret = "期望输出是'绝密答案42'在/Users/x/oracle/held.txt"
    rep = _report(gate_reasons=[f"CapabilityVerifier: {secret}",
                               "failing: test_held_example_1"])
    a = assess_report(rep)
    dump = a.model_dump_json()
    assert "绝密答案" not in dump
    assert "/Users/" not in dump
    assert "held.txt" not in dump
    m = derive_repair_metrics(rep)
    assert "绝密答案" not in json.dumps(m, ensure_ascii=False)


def test_projection_is_pure_and_deterministic():
    rep = _report(gate_reasons=["CapabilityVerifier: failing: test_example_2"])
    before = json.dumps(rep, ensure_ascii=False, sort_keys=True)
    a1 = assess_report(rep).model_dump_json()
    a2 = assess_report(rep).model_dump_json()
    assert a1 == a2                              # 重复投影逐字节一致
    assert json.dumps(rep, ensure_ascii=False, sort_keys=True) == before  # 零回写


def test_same_root_cause_same_fingerprint_different_values():
    """同根因不同具体值(行数/路径变了)→ 指纹一致;根因变 → 指纹变。"""
    a = _report(gate_reasons=[
        "PolicyVerifier: adaptation files 647 > max_patch_files 12"])
    b = _report(gate_reasons=[
        "PolicyVerifier: adaptation files 899 > max_patch_files 12"])
    c = _report(gate_reasons=["CapabilityVerifier: failing: test_example_1"])
    fa = assess_report(a).public_failure_fingerprint
    fb = assess_report(b).public_failure_fingerprint
    fc = assess_report(c).public_failure_fingerprint
    assert fa == fb
    assert fa != fc


def test_repair_metrics_rescue_accounting():
    ok2 = _report(verdict="PASS_ADAPTED", public_passed_by_round=[1, 5],
                  repair={"rounds_run": 2, "stop_reason":
                          "all_public_green_pending_verification"})
    m = derive_repair_metrics(ok2)
    assert m["repair_attempted"] is True
    assert m["rescued_at_attempt"] == 1
    assert m["initial_public_pass"] is False
    ok1 = _report(verdict="PASS_ADAPTED", public_passed_by_round=[5],
                  repair={"rounds_run": 1, "stop_reason":
                          "all_public_green_pending_verification"})
    m1 = derive_repair_metrics(ok1)
    assert m1["initial_public_pass"] is True
    assert m1["rescued_at_attempt"] is None
    assert m1["product_stop_code"] == "NO_REPAIR_NEEDED"


def test_ui_build_conclusion_projection():
    """Gate 4:活动页构建结论卡的投影 helper(路线/终止码/零模型声明)。"""
    import json

    from repoproof.ui.services.product_mode import (
        build_conclusion,
        parse_build_summary,
    )

    log = "前置噪声{不完整\n" + json.dumps({
        "stages": {"route": {"route": "DIRECT_WRAP", "agent_invoked": False},
                   "direct": {"verdict": "PASS_DIRECT",
                              "product_stop_code": "NO_REPAIR_NEEDED",
                              "run_id": "r-1"}},
        "verdict": "VERIFIED_TOOL_READY (DIRECT)",
        "exported": "/tools/x"}, ensure_ascii=False)
    c = build_conclusion(parse_build_summary(log))
    assert c["agent_invoked"] is False
    assert "不需要 Agent" in c["route_label"]
    assert c["stop_label"].startswith("初次候选即通过")
    assert parse_build_summary("完全不是 JSON 的日志") is None
