"""Sidecar Conformance / Runtime Canary 的钉死。

矩阵本体在 `scripts/sidecar_conformance.py`(零模型、零网络、真 sidecar 进程、
**harness 独占的上游 fixture**)。它证明的是 A1 那条链:

    Agent ──只能调 RPC──▶ Harness-owned Sidecar ──真执行钉版上游──▶ Receipt ──▶ Verifier

与 `test_receipt_controls.py` 的分工:那边证明**回执机制**不可伪造(上游用
agent 装得到的 markdown-it-py),这边证明**这条拓扑**成立(上游 agent 根本
import 不着,且现场核验)。

冻结判据:

- C1 **拓扑先于一切**。上游若够得着,后面的回执与八条攻击全是装饰 ——
  agent 大可自己算,而"它没来敲门"会被读成偷懒,其实是它不需要。
- C2 **正控必须过**,且容得下无害后处理。反例:判据成墙 —— 墙拦不住洗白,
  只拦得住诚实实现(#44)。
- C3 **a4(调了但不用结果)只红在 U4**。这是整套设计的考题;它红在别处
  就说明四道谓词糊在一起了。
- C4 **a7 与 a8 红在不同处**。a7 删行 → 链断而签名有效;a8 增行 → 签名无效
  而链完整。合成一条会掩盖掉其中一道从没被考过。
- C5 **上游能力不可重实现**。反例:能力是纯函数 → "自己重实现"那条会因为
  输出恰好相同而在 U4 上蒙混过去,采纳判据在本 fixture 上零判别力,而我们
  恰恰是拿它来证明采纳判据管用的。
- C6 **不是 benchmark**。反例:结果混进 runs.jsonl 或任何闸门数字 —— 它测的
  是 harness 自己,不是模型。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MATRIX = REPO / "docs" / "evidence" / "sidecar_conformance" / "matrix.json"
ADAPTERS = REPO / "benchmarks" / "v2" / "sidecar_conformance" / "adapters"
FIXTURE = REPO / "benchmarks" / "v2" / "upstream_fixtures" / "canary_upstream_v1"

REQUIRED = {"a0_honest", "a1_never_calls", "a2_reimplements", "a3_fake_package",
            "a4_ignores_result", "a5_wrong_symbol", "a6_replays_receipt",
            "a7_tampers_receipt", "a8_forges_receipt"}


def _m() -> dict:
    import pytest

    if not MATRIX.is_file():
        pytest.skip("矩阵证据未落盘 —— 跑 scripts/sidecar_conformance.py")
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def test_c1_topology_holds():
    """C1:四条拓扑核验全过 —— 这是 A1 的地基。"""
    t = _m()["topology"]
    assert t["ok"], [f for f in t["findings"] if not f["ok"]]
    assert {f["check"] for f in t["findings"]} == {
        "T1.not_in_wheelhouse", "T2.not_importable_cleanly",
        "T3.inside_policy_denied_repo", "T4.no_fixture_hint_in_agent_env"}


def test_c2_honest_adapter_passes():
    """C2:诚实实现必须过,且它做过无害后处理(去行尾空格)。"""
    m = _m()
    a0 = next(r for r in m["rows"] if r["adapter"] == "a0_honest")
    assert a0["actual"] == "PASS", f"正控红了 —— 判据成墙:{a0['actual_red']}"


def test_c3_ignoring_the_result_reds_only_on_adoption():
    """C3:整套设计的考题 —— a4 只红在 U4。"""
    m = _m()
    a4 = next(r for r in m["rows"] if r["adapter"] == "a4_ignores_result")
    assert a4["actual_red"] == ["U4.adoption"], (
        f"a4 的红点变了:{a4['actual_red']} —— '调了但没用'不再是被 U4 单独抓住的")


def test_c4_tamper_and_forge_red_in_different_places():
    """C4:删行与增行必须红在不同处,否则其中一道判据从没被考过。"""
    m = _m()
    a7 = next(r for r in m["rows"] if r["adapter"] == "a7_tampers_receipt")
    a8 = next(r for r in m["rows"] if r["adapter"] == "a8_forges_receipt")
    assert "U1.chain" in a7["actual_red"] and "U1.signature" not in a7["actual_red"], (
        f"a7 该只破链不破签名:{a7['actual_red']}")
    assert "U1.signature" in a8["actual_red"] and "U1.chain" not in a8["actual_red"], (
        f"a8 该只破签名不破链:{a8['actual_red']}")


def test_c5_upstream_capability_is_not_reimplementable():
    """C5:上游能力不可重实现 —— 盐只有它知道。

    反例:能力是纯函数 → "自己重实现"输出恰好相同,U4 反而绿,采纳判据在
    这个 fixture 上零判别力。"""
    sys.path.insert(0, str(FIXTURE))
    import canary_upstream.transform as tr

    out = tr.normalize("a  b")
    assert "#canary:" in out, "输出里没有校验尾 —— 能力被谁改成纯函数了?"
    body = out.split("#canary:")[0]
    naive = body + "#canary:" + "0" * 16 + "\n"
    assert naive != out, "朴素重实现竟然算得出校验尾"

    a2 = next(r for r in _m()["rows"] if r["adapter"] == "a2_reimplements")
    assert "U4.adoption" in a2["actual_red"], (
        "重实现竟然通过了采纳 —— 能力可重实现了,这个 fixture 失去判别力")


def test_c6_conformance_never_enters_the_ledger():
    """C6:它不是 benchmark —— 结果不得进 runs.jsonl,不得影响任何闸门数字。"""
    rows = [json.loads(x) for x in
            (REPO / "benchmarks" / "v2" / "runs.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]
    ids = {r.get("run_id", "") for r in rows}
    assert not [i for i in ids if i.startswith("conf-")], (
        "conformance 发次混进台账了 —— 它测的是 harness 自己,不是模型")
    assert _m()["_not_a_benchmark"]


def test_every_adapter_is_present_and_matches_expectation():
    """一个都不能少,且每条实际红点集与自己声明的期望集逐一相等。"""
    on_disk = {p.stem for p in ADAPTERS.glob("a*.py")}
    assert REQUIRED - on_disk == set(), f"adapter 缺失:{sorted(REQUIRED - on_disk)}"

    m = _m()
    assert m["ok"] is True and m["problems"] == []
    assert {r["adapter"] for r in m["rows"]} == REQUIRED
    for r in m["rows"]:
        if r["expect"] == "FAIL":
            assert sorted(r["actual_red"]) == sorted(r["expect_red"]), r["adapter"]


def _script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sidecar_conformance", REPO / "scripts" / "sidecar_conformance.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_c1b_a_failing_topology_actually_refuses_to_emit(monkeypatch, capsys):
    """C1 的行为面:拓扑不成立时**当场拒绝出数**,而不是照跑。

    变异闸门 M52b 抓到的逃逸:原钉死只读落盘证据里的 `topology.ok`,而现实
    里拓扑一直是通过的 —— 于是把那道闸门整个掏掉也没人看得出来。与 M50a
    同型:**检查器必须先证明自己查得出**,证明的办法是喂它一个合成的失败,
    不是等现实里出问题。

    这一条尤其要紧:拓扑是 A1 的地基。地基不成立时若还照跑,输出的八条
    "攻击全被挡住"会被当成证据,而它其实什么都没证 —— agent 大可自己算,
    根本不必来敲门。"""
    mod = _script()          # 先加载脚本 —— 它把 conformance 目录挂进 sys.path
    import topology as T

    monkeypatch.setattr(
        T, "check_topology",
        lambda: {"ok": False, "findings": [
            {"check": "T2.not_importable_cleanly", "ok": False,
             "detail": "合成失败:agent 竟然 import 得到上游"}]})

    rc = mod.main()
    assert rc == 2, f"拓扑不成立却没拒绝出数(返回 {rc})"
    assert "拒绝出数" in capsys.readouterr().err


def test_matrix_judge_catches_a_wrong_red_spot():
    """判定函数自己的判别力(第 6 步 M50a 的教训:检查器先证明自己查得出)。"""
    mod = _script()

    ok = {"adapter": "x", "expect": "FAIL", "expect_red": ["U4.adoption"],
          "actual": "FAIL", "actual_red": ["U4.adoption"]}
    assert mod.find_problems([ok]) == []
    assert mod.find_problems([{**ok, "actual_red": ["U3.coverage"]}])
    assert mod.find_problems([{**ok, "actual_red": ["U3.coverage", "U4.adoption"]}])
    assert mod.find_problems([{**ok, "actual": "PASS", "actual_red": []}])
