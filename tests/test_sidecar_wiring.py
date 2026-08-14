"""sidecar 接进 `host-run` 的钉死。

这一段最容易出的错不是"功能不对",而是**报错报得像另一件事**。三处实测事故
全是这个形状:

- oracle 拿不到 sidecar 环境 → 三条隐藏用例全红,看起来像被测方不行;
- 取件时机晚于会话销毁 → 报 host=None,看起来像交付不存在;
- profile 定义 import 不到 → 报"未登记的 profile",看起来像配置写错了。

所以钉的重点是**归因不许混**。

- W1 **in-process 任务的会话环境一字不变**。反例:新增能力顺手改了所有任务
  的 env → 既有发次与历史不可比,而没人会注意到。
- W2 **agent 与 oracle 都拿不到台账路径与密钥**。反例:漏出去 → U1 的全部
  意义没了(谁都能伪造回执)。
- W3 **取件在会话销毁之前**。反例:放最外层 finally → clean replay 已经把
  会话清了,永远取不到。
- W4 **取件失败 ≠ 采纳不成立**,分开报。反例:混成一个 U4 红 → harness 的
  毛病记成被测方的失败。
- W5 **采纳不通过走 missing_external**,不对 verdict 做手术。反例:自己改
  verdict → gate 的结论与它自己的 reasons 对不上。
- W6 **profile 惰性加载是白名单**,不扫目录。反例:扫目录 → 放个文件进去就
  凭空多出一个"对外承诺的名字"。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HG = (REPO / "src" / "repoproof" / "runner" / "host_guided.py").read_text(encoding="utf-8")
SS = (REPO / "src" / "repoproof" / "runner"
      / "sidecar_session.py").read_text(encoding="utf-8")


def test_w1_inprocess_sessions_are_untouched():
    """W1:`extra_env` 缺省 None,in-process 任务的会话环境一字不变。"""
    assert "extra_env: dict[str, str] | None = None" in HG
    assert "**(extra_env or {})," in HG
    # 只有 sidecar 拓扑才起会话
    assert 'if _rt.topology == "sidecar":' in HG


def test_w2_neither_agent_nor_oracle_gets_the_key_or_ledger():
    """W2:交给 agent / oracle 的环境里没有台账路径与密钥。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.execution.upstream_sidecar import SidecarHandle

    h = SidecarHandle(None, "http://127.0.0.1:1", "tok",       # type: ignore[arg-type]
                      Path("/x/ledger.jsonl"), "rt-x")
    blob = json.dumps(h.agent_env())
    for bad in ("ledger", "LEDGER", "key", "KEY", "/x/"):
        assert bad not in blob, f"agent 环境里漏了 {bad!r}"
    # oracle 走的是同一份 agent_env
    assert "**self._sidecar_env_for_oracle()," in HG
    assert "sess.agent_env()" in HG


def test_w3_delivery_is_extracted_before_the_session_dies():
    """W3:取件必须在 `backend.destroy(s.id); s = None` 之前。

    实测踩过:原本放最外层 finally,而 clean replay 会先销毁会话,
    等到 finally 时 host 目录早没了 —— 报 host=None,看起来像交付不存在。"""
    extract_at = HG.index("delivery_snapshot = self._extract_sidecar_delivery(s)")
    destroy_at = HG.index("                    backend.destroy(s.id)\n                    s = None")
    assert extract_at < destroy_at, "取件排在会话销毁之后了 —— 永远取不到"


def test_w4_extraction_failure_is_not_adoption_failure():
    """W4:取件失败/无取件器/核验器出错,三种各有各的 reason。"""
    for reason in ("NO_DELIVERY_EXTRACTED", "NO_DELIVERY_EXTRACTOR",
                   "RECEIPT_VERIFIER_ERROR"):
        assert reason in HG, f"少了 {reason} —— 会被含糊成 U4 红"
    assert "这不是 U4 红" in SS or "取件失败" in HG


def test_w4b_no_delivery_is_reported_as_extraction_failure():
    """W4 的行为面:`verify(..., delivery=None)` 必须报**取件失败**,
    不是采纳失败。

    变异闸门 M56c 抓到的逃逸:原钉死只查 `host_guided.py` 里有没有那个字符串,
    而这条分支在 `sidecar_session.py` 里 —— 把它的 reason 改成
    RECEIPT_VERIFICATION_FAILED,没人看得见。而那正是"harness 的毛病记成
    被测方的失败"的具体形态。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.runner import sidecar_session as ss

    got = ss.verify(None, task_id="whatever", delivery=None)   # type: ignore[arg-type]
    assert got["ok"] is False
    assert got["reason"] == "NO_DELIVERY_EXTRACTED", (
        f"取件失败被报成了 {got['reason']!r} —— harness 的毛病记成被测方的失败")
    assert "取件失败" in got["detail"] or "无从判断" in got["detail"]


def test_w5_adoption_failure_goes_through_missing_external():
    """W5:采纳不通过走既有通道,不改 verdict。"""
    assert 'missing_external.append(\n                            "RECEIPT_VERIFICATION_FAILED:"' in HG
    assert "gate.verdict =" not in HG, "对 verdict 做了手术 —— 会与 reasons 对不上"


def test_w6_lazy_profile_registration_is_a_whitelist():
    """W6:惰性加载按白名单,不扫目录。"""
    src = (REPO / "src" / "repoproof" / "execution"
           / "runtime_profiles.py").read_text(encoding="utf-8")
    assert "_LAZY_DEFS" in src
    assert "rglob" not in src and "iterdir" not in src, (
        "扫目录了 —— 放个文件进去就凭空多出一个对外承诺的名字")


def test_w7_item_count_must_be_at_least_two():
    """U3 的分母 <2 时抓不住'一次调用充抵所有项' —— 起会话就该拒绝。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.execution.runtime_profiles import profile
    from repoproof.runner import sidecar_session as ss

    with pytest.raises(ValueError, match="至少 2"):
        ss.start(profile=profile("rt-inprocess-v1"), run_id="x",
                 run_dir=Path("/tmp"), item_count=1)


def test_w8_the_real_run_passed_all_four_predicates():
    """接线的现场证明:真跑过一次 host-run,四道谓词全过。"""
    runs = sorted(Path(REPO / "runs").glob("t3-sidecar-page-facts-v1-*"))
    if not runs:
        pytest.skip("尚未跑过 T3-SIDECAR 发次")
    rep = json.loads((runs[-1] / "report.json").read_text(encoding="utf-8"))
    rv = rep.get("receipt_verification")
    assert rv is not None, "报告里没有回执核验 —— 接线断了"
    assert rv["ok"] is True, [f for f in rv["findings"] if not f["ok"]]
    checks = {f["check"] for f in rv["findings"]}
    assert {"U1.chain", "U1.signature", "U1.count", "U2.symbol",
            "U2.upstream_identity", "U3.coverage", "U4.adoption"} <= checks
    assert (runs[-1] / "upstream_receipts.jsonl").is_file(), "台账没落在 run 目录"
