"""Gate D(RFC-008 §11)— 有界多轮修复机制的无 Docker 钉死测试。

真实模型运行属预注册事项(docs/rfc/PREREG-gateD-guided-repair.md),
本文件只钉机制:§11.3 排序、快照/恢复真实性、FailurePacket 公开性、
Scope Change 提取、轮次账本、junit message 摘要。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.adoption.repair.failure_packet import build_failure_packets
from repoproof.adoption.repair.repair_budget import RepairBudget
from repoproof.adoption.repair.repair_loop import (
    RepairLoop,
    RoundResult,
    classify_agent_exit_status,
    full_score,
)
from repoproof.runner.guided_repair import (
    SCOPE_MARKER,
    RepairRoundRecord,
    extract_scope_change,
    render_packets,
    restore_adaptation,
    snapshot_adaptation,
)
from repoproof.verification.junit import parse_junit_xml

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    ("exit_status", "expected"),
    [
        (
            "Uncaught:ServiceUnavailableError",
            ("EXTERNAL", "PROVIDER_UNAVAILABLE", "RETRY_INFRASTRUCTURE"),
        ),
        (
            "AuthenticationError",
            (
                "HARNESS",
                "PROVIDER_CONFIGURATION_INVALID",
                "RETRY_INFRASTRUCTURE",
            ),
        ),
        (
            "litellm.UnsupportedParamsError: temperature is unsupported",
            (
                "HARNESS",
                "PROVIDER_CONFIGURATION_INVALID",
                "RETRY_INFRASTRUCTURE",
            ),
        ),
        ("LimitsExceeded", None),
        ("Submitted", None),
    ],
)
def test_agent_runtime_exit_responsibility_is_conservative(
    exit_status: str,
    expected: tuple[str, str, str] | None,
) -> None:
    assert classify_agent_exit_status(exit_status) == expected


# ---------- §11.3 Best State 排序(禁止只按通过数) ----------

def _rr(**kw) -> RoundResult:
    base = dict(adapter_snapshot="s", passed=0)
    base.update(kw)
    return RoundResult(**base)


def test_collection_crash_ranks_below_any_collected_round() -> None:
    """崩溃轮(收集失败)即使名义通过数更高也不能当最佳。"""
    crashed = full_score(_rr(passed=9, collected_ok=False))
    modest = full_score(_rr(passed=1, collected_ok=True))
    assert modest > crashed


def test_policy_violation_outranks_pass_count() -> None:
    violating = full_score(_rr(passed=9, policy_violations=2))
    clean = full_score(_rr(passed=8, policy_violations=0))
    assert clean > violating


def test_regression_break_outranks_pass_count() -> None:
    broke = full_score(_rr(passed=9, regression_failed=1))
    safe = full_score(_rr(passed=5, regression_failed=0))
    assert safe > broke


def test_smaller_diff_wins_ties() -> None:
    big = full_score(_rr(passed=5, diff_lines=400))
    small = full_score(_rr(passed=5, diff_lines=40))
    assert small > big


def test_loop_uses_full_score_for_best_state() -> None:
    """第 2 轮通过数更高但违规 → best 仍是第 1 轮,且第 2 轮被回滚。"""
    rounds = [
        _rr(adapter_snapshot="r1", passed=5, failed_nodes=["t::y"]),
        _rr(adapter_snapshot="r2", passed=9, policy_violations=1,
            failed_nodes=["t::x"]),
        _rr(adapter_snapshot="r3", passed=5, failed_nodes=["t::x"]),
    ]

    def run_round(idx, packets, best_snapshot):
        return rounds[idx - 1]

    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=3),
                     score_fn=full_score).run()
    assert out.best_round == 1
    assert 2 in out.rolled_back_rounds


def test_crash_round_never_declares_all_green() -> None:
    """崩溃轮 failed_nodes 为空但 collected_ok=False → 不得判全绿。"""
    rounds = [
        _rr(adapter_snapshot="r1", passed=3, collected_ok=False, failed_nodes=[]),
        _rr(adapter_snapshot="r2", passed=1, failed_nodes=["t::x"]),
        _rr(adapter_snapshot="r3", passed=1, failed_nodes=["t::x"]),
    ]

    def run_round(idx, packets, best_snapshot):
        return rounds[idx - 1]

    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=3),
                     score_fn=full_score).run()
    assert out.stop_reason != "all_public_green_pending_verification"


def test_default_score_preserves_old_behavior() -> None:
    """不传 score_fn → 与旧「通过数」语义一致(RFC-006 钉死不回退)。"""
    rounds = [
        _rr(adapter_snapshot="r1", passed=2, failed_nodes=["t::a"]),
        _rr(adapter_snapshot="r2", passed=5, failed_nodes=[]),
    ]

    def run_round(idx, packets, best_snapshot):
        return rounds[idx - 1]

    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=3)).run()
    assert out.best_round == 2
    assert out.stop_reason == "all_public_green_pending_verification"


# ---------- 快照 / 恢复(F3:真实恢复) ----------

def test_snapshot_and_restore_roundtrip(tmp_path: Path) -> None:
    adaptation = tmp_path / "adaptation"
    adaptation.mkdir()
    (adaptation / "adapter.py").write_text("v1", encoding="utf-8")
    snap = tmp_path / "round-1" / "adaptation"
    snap.parent.mkdir()
    h1 = snapshot_adaptation(adaptation, snap)
    # 劣化:改坏 + 加垃圾文件
    (adaptation / "adapter.py").write_text("v2-broken", encoding="utf-8")
    (adaptation / "junk.py").write_text("x", encoding="utf-8")
    restore_adaptation(adaptation, snap)
    assert (adaptation / "adapter.py").read_text(encoding="utf-8") == "v1"
    assert not (adaptation / "junk.py").exists()
    assert snapshot_adaptation(adaptation, tmp_path / "verify") == h1


# ---------- FailurePacket → 提示文本(§11.6 公开性) ----------

def test_render_packets_contains_no_raw_logs_or_hidden_names() -> None:
    packets = build_failure_packets(
        ["public_tests/test_public_contract.py::test_example_2"],
        {"public_tests/test_public_contract.py::test_example_2":
         "期望包含 '周会纪要',实际: []"},
    )
    text = render_packets(packets)
    assert "test_example_2".replace("test_", "") or True
    for banned in ("held", "oracle", "Traceback", "FAILED", "reference"):
        assert banned not in text, banned
    assert "expected:" in text and "suggestion:" in text


def test_round_header_offers_scope_change_marker() -> None:
    from repoproof.runner.guided_repair import _ROUND_HEADER

    header = _ROUND_HEADER.format(idx=2, max_rounds=3, marker=SCOPE_MARKER)
    assert "ROUND 2/3" in header and SCOPE_MARKER in header
    for banned in ("held-out", "oracle", "verdict"):
        assert banned not in header.lower().replace("held-out", "held-out"), banned


# ---------- Scope Change 提取 ----------

def test_extract_scope_change() -> None:
    sub = f"some output\n{SCOPE_MARKER} 需要新增大型依赖 numpy 才能继续\n"
    assert extract_scope_change(sub) == "需要新增大型依赖 numpy 才能继续"
    assert extract_scope_change("plain submission") is None
    assert extract_scope_change("") is None and extract_scope_change(None) is None


def test_loop_pauses_on_scope_change() -> None:
    rounds = [
        _rr(adapter_snapshot="r1", passed=2, failed_nodes=["t::x"],
            scope_change_request="需要联网下载模型"),
    ]

    def run_round(idx, packets, best_snapshot):
        return rounds[idx - 1]

    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=3),
                     score_fn=full_score).run()
    assert out.stop_reason == "scope_change_pending_user"
    assert out.pending_scope_change == "需要联网下载模型"
    assert out.rounds_run == 1  # 绝不自行继续


def test_product_loop_stops_when_agent_produced_no_adapter_diff() -> None:
    def run_round(idx, packets, best_snapshot):
        return _rr(
            adapter_snapshot=f"r{idx}",
            passed=0,
            failed_nodes=["public_tests/test_contract.py::test_one"],
            adapter_diff_present=False,
            failure_owner="AGENT_ADAPTER",
            reason_codes=["PUBLIC_CONTRACT_FAILURE"],
        )

    out = RepairLoop(
        run_round,
        budget=RepairBudget(max_rounds=3),
        score_fn=full_score,
        responsibility_gating=True,
    ).run()
    assert out.rounds_run == 1
    assert out.stop_reason == "no_adapter_diff"
    assert "NO_ADAPTER_DIFF" in out.reason_codes


def test_product_loop_does_not_accept_green_claim_without_adapter_diff() -> None:
    out = RepairLoop(
        lambda *_args: _rr(
            adapter_snapshot="unchanged",
            passed=3,
            failed_nodes=[],
            adapter_diff_present=False,
            failure_owner="AGENT_ADAPTER",
        ),
        budget=RepairBudget(max_rounds=3),
        score_fn=full_score,
        responsibility_gating=True,
    ).run()
    assert out.rounds_run == 1
    assert out.stop_reason == "no_adapter_diff"
    assert "NO_ADAPTER_DIFF" in out.reason_codes


def test_product_loop_stops_on_second_identical_public_failure() -> None:
    def run_round(idx, packets, best_snapshot):
        return _rr(
            adapter_snapshot=f"r{idx}",
            passed=1,
            failed_nodes=["public_tests/test_contract.py::test_one"],
            adapter_diff_present=True,
            failure_owner="AGENT_ADAPTER",
            reason_codes=["PUBLIC_CONTRACT_FAILURE"],
        )

    out = RepairLoop(
        run_round,
        budget=RepairBudget(max_rounds=3),
        score_fn=full_score,
        responsibility_gating=True,
    ).run()
    assert out.rounds_run == 2
    assert out.stop_reason == "repeated_public_failure"
    assert "REPEATED_PUBLIC_FAILURE" in out.reason_codes


def test_product_loop_does_not_spend_repair_on_harness_failure() -> None:
    def run_round(idx, packets, best_snapshot):
        return _rr(
            adapter_snapshot=f"r{idx}",
            passed=0,
            failed_nodes=["public_tests::collection"],
            failure_owner="HARNESS",
            recommended_action="RETRY_INFRASTRUCTURE",
            reason_codes=["PUBLIC_TEST_COLLECTION_FAILED"],
        )

    out = RepairLoop(
        run_round,
        budget=RepairBudget(max_rounds=3),
        score_fn=full_score,
        responsibility_gating=True,
    ).run()
    assert out.rounds_run == 1
    assert out.stop_reason == "non_repairable_failure"
    assert out.failure_owner == "HARNESS"


@pytest.mark.parametrize("owner", ["CONTRACT", "SAFETY_POLICY", "USER_INPUT"])
def test_product_loop_does_not_repair_non_agent_responsibility(owner: str) -> None:
    out = RepairLoop(
        lambda *_args: _rr(
            adapter_snapshot="r1",
            passed=0,
            failed_nodes=["public_tests::blocked"],
            failure_owner=owner,
            reason_codes=["NON_AGENT_FAILURE"],
        ),
        budget=RepairBudget(max_rounds=3),
        score_fn=full_score,
        responsibility_gating=True,
    ).run()
    assert out.rounds_run == 1
    assert out.stop_reason == "non_repairable_failure"


def test_product_loop_allows_one_useful_repair_then_passes() -> None:
    rounds = [
        _rr(
            adapter_snapshot="r1",
            passed=1,
            failed_nodes=["public_tests::one"],
            adapter_diff_present=True,
            failure_owner="AGENT_ADAPTER",
            reason_codes=["PUBLIC_CONTRACT_FAILURE"],
        ),
        _rr(
            adapter_snapshot="r2",
            passed=2,
            failed_nodes=[],
            adapter_diff_present=True,
            failure_owner="AGENT_ADAPTER",
        ),
    ]

    out = RepairLoop(
        lambda idx, packets, best: rounds[idx - 1],
        budget=RepairBudget(max_rounds=3),
        score_fn=full_score,
        responsibility_gating=True,
    ).run()
    assert out.rounds_run == 2
    assert out.stop_reason == "all_public_green_pending_verification"


def test_product_loop_can_succeed_on_final_third_attempt() -> None:
    rounds = [
        _rr(
            adapter_snapshot="r1",
            passed=1,
            failed_nodes=["public_tests::one"],
            failure_class="AssertionError",
        ),
        _rr(
            adapter_snapshot="r2",
            passed=2,
            failed_nodes=["public_tests::two"],
            failure_class="ValueError",
        ),
        _rr(
            adapter_snapshot="r3",
            passed=3,
            failed_nodes=[],
            failure_class="",
        ),
    ]
    out = RepairLoop(
        lambda idx, *_args: rounds[idx - 1],
        budget=RepairBudget(max_rounds=3),
        score_fn=full_score,
        responsibility_gating=True,
    ).run()
    assert out.rounds_run == 3
    assert out.best_round == 3
    assert out.stop_reason == "all_public_green_pending_verification"


# ---------- 轮次账本(§11.2) ----------

def test_repair_round_record_schema() -> None:
    rec = RepairRoundRecord(round_index=1)
    d = rec.to_dict()
    for key in ("round_index", "base_snapshot_hash", "adaptation_root",
                "changed_files", "diff_lines", "public_passed", "public_failed",
                "regression_passed", "regression_failed", "policy_violations",
                "model_calls", "commands", "tokens_in", "tokens_out",
                "wall_time_s", "failure_packets", "scope_change_request",
                "score", "selected_as_best", "failure_owner",
                "public_failure_fingerprint", "reason_codes",
                "adapter_diff_present", "recommended_action"):
        assert key in d, key
    assert d["tokens_in"] == "UNKNOWN"  # 未知永不写 0


# ---------- junit message 摘要(FailurePacket 输入) ----------

def test_junit_nodes_carry_truncated_message() -> None:
    xml = (b'<testsuite tests="1" failures="1">'
           b'<testcase classname="t" name="test_a">'
           b'<failure message="AssertionError: expected X">' + b"x" * 2000 +
           b"</failure></testcase></testsuite>")
    junit = parse_junit_xml(xml)
    node = junit["nodes"][0]
    assert node["outcome"] == "failed"
    assert node["message"].startswith("AssertionError")
    assert len(node["message"]) <= 400


# ---------- 泄漏静态钉死:guided_repair 源码无 held-out 引用 ----------

def test_guided_repair_source_never_references_hidden_oracle() -> None:
    src = (REPO / "src" / "repoproof" / "runner" / "guided_repair.py").read_text(
        encoding="utf-8")
    # 允许中文说明里出现「held-out …永不」的否定句;禁止任何代码路径
    # 引用 held_out fixture / oracle 参考文件名 / expected verdict
    for banned in ("held_out_documents", "reference_records", "expected_verdict",
                   "test_capability.py", "/oracle/"):
        assert banned not in src, banned
    # 每轮公开测试只跑 /consumer/public_tests
    assert "/consumer/public_tests" in src
