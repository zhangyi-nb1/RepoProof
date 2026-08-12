"""LESSONS #36(反馈量足够、形状错误)— 同根因折叠与超时成型的钉死。

实录反例(order-55,gpt-5.5 × T3v5,三轮 [3, 6, 8]/23):15 项检查全部
`failed on setup with "AssertionError: 作业 <id> 未在 120.0s 内终结"`,
被摊成 15 枚几乎一样的包;其中 2 枚因测试名里有"字段"被误判成
SCHEMA_ERROR;15 条建议统一写"阅读该项公开测试的断言语义"——而测试
压根没走到断言,它死在 setup 超时。信息量 1 句、噪声 60 行、方向指错。

冻结判据:
  H6-a 同根因(抹掉 id/数字后指纹相同)≥3 项 → 合并成**一枚**包并列出
       全部受连累检查项;
  H6-b 超时必须自成类型 TIMEOUT,建议谈"作业终结时间"而非"断言语义";
  H6-c 零信息丢失:每个失败节点名仍须出现在包里;
  H6-d 不同根因不得被合并。
边界(§39):同一份信息换个形状,不放宽任何判据、不减少任何需求。
"""

from __future__ import annotations

from repoproof.adoption.repair.failure_packet import (
    SHARED_ROOT_CAUSE,
    TIMEOUT,
    build_failure_packets,
)

_TIMEOUT_MSG = ('failed on setup with "AssertionError: '
                '作业 {jid} 未在 120.0s 内终结"')
_JIDS = ["c71b61e3fca24e62", "dcb12c77b8c143b5", "9a0f21bb77c04e18",
         "4471aa02be0f4c1d", "0f5e3c9d1a2b4e6f"]


def _order55_like(n: int = 15) -> tuple[list[str], dict[str, str]]:
    """复刻 order-55 的形状:n 项检查、n 个不同作业 id、同一句根因。"""
    names = ["create_is_non_blocking", "happy_path_reaches_prepared_human_gate",
             "authorized_fields_filled_on_site", "no_final_submit_and_no_trap_hits",
             "unknown_fields_not_filled_and_surfaced", "resume_uploaded_to_site",
             "cancel_moves_job_out_of_running", "status_lifecycle_and_result_fields",
             "duplicate_submission_has_explicit_policy", "restart_has_no_running",
             "privacy_no_pii_in_artifacts", "engine_is_really_present",
             "llm_responses_drive_browser_actions", "concurrent_jobs_do_not_cross",
             "adversarial_jd_never_submits"][:n]
    nodes = [f"public_tests/test_public_apply_assist.py::test_{x}" for x in names]
    details = {node: _TIMEOUT_MSG.format(jid=_JIDS[i % len(_JIDS)])
               for i, node in enumerate(nodes)}
    return nodes, details


def test_shared_root_cause_collapses_into_one_packet() -> None:
    """H6-a:15 项同根因 → 恰 1 枚包(反例:order-55 收到 15 枚)。"""
    nodes, details = _order55_like()
    packets = build_failure_packets(nodes, details)
    assert len(packets) == 1, f"应折叠成 1 枚,实得 {len(packets)}"
    assert packets[0].type == SHARED_ROOT_CAUSE
    assert "15 项" in packets[0].summary
    assert "120" in packets[0].actual and "终结" in packets[0].actual


def test_timeout_is_typed_and_advised_as_timeout() -> None:
    """H6-b:超时自成类型;建议谈终结时间,不得再说"阅读断言语义"。
    反例:order-55 的 13 枚 TEST_FAILURE + 2 枚 SCHEMA_ERROR。"""
    node = "public_tests/t.py::test_authorized_fields_filled_on_site"
    packets = build_failure_packets([node], {node: _TIMEOUT_MSG.format(jid="ab12cd34ef")})
    assert packets[0].type == TIMEOUT, "名里带「字段」不得压过超时根因"
    assert "终结" in packets[0].suggestion
    assert "断言语义" not in packets[0].suggestion

    # 折叠包也要带上根因自己的处置口径
    nodes, details = _order55_like()
    collapsed = build_failure_packets(nodes, details)[0]
    assert TIMEOUT in collapsed.summary
    assert "终结" in collapsed.suggestion


def test_no_information_is_silently_dropped() -> None:
    """H6-c:折叠不是截断——每个失败检查名都必须还在包里。"""
    nodes, details = _order55_like()
    blob = " ".join(p.summary + p.actual for p in build_failure_packets(nodes, details))
    for node in nodes:
        human = node.split("::")[-1].replace("test_", "").replace("_", " ")
        assert human in blob, f"折叠后丢了 {human}"


def test_distinct_root_causes_are_not_merged() -> None:
    """H6-d:不同根因各自成包;同根因不足 3 项也不折叠(2 条不值得抽象)。"""
    nodes = [f"t.py::test_a{i}" for i in range(3)] + [f"t.py::test_b{i}" for i in range(2)]
    details = {n: (_TIMEOUT_MSG.format(jid="aa11bb22cc") if n.startswith("t.py::test_a")
                   else "AssertionError: 授权字段 email 应照常填写")
               for n in nodes}
    packets = build_failure_packets(nodes, details)
    kinds = [p.type for p in packets]
    assert kinds.count(SHARED_ROOT_CAUSE) == 1, "3 项超时应折叠"
    assert len(packets) == 3, f"1 枚折叠 + 2 枚独立,实得 {len(packets)}"


def test_packets_without_details_keep_old_shape() -> None:
    """无 details 时行为不回退(旧钉死语义保持):逐项成包,不误折叠。"""
    nodes = [f"t.py::test_x{i}" for i in range(4)]
    packets = build_failure_packets(nodes)
    assert len(packets) == 4
    assert all(p.type != SHARED_ROOT_CAUSE for p in packets)
