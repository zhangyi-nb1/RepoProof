"""`rt-sidecar-browser-v1` conformance 矩阵的钉死 —— **真上游 + 真浏览器**。

与 canary 的分工:那边用手造 fixture 证明**机制**成立;这边证明同一套机制在
真 browser-use 0.13.7 + 封存 Chromium 上照样成立。

- B1 **拓扑五条全过**,且报的是**本 suite 的**拓扑。反例(实测发生过):两个
  suite 都有 `topology.py`,裸 import 被先到的赢走,浏览器矩阵报出来的是
  canary 的拓扑,而整张表其余部分全绿、看起来毫无异样。
- B2 **正控过**,且容得下无害后处理。
- B3 **a4(调了但不用结果)只红在 U4** —— 真上游版的考题。
- B4 **a2(自己重实现)红在 U4**。它真去抓页面、真按 flex 规范算,数学上完全
  正确 —— 仍然对不上排版引擎的定点结果。这条一旦变绿,说明能力可重实现了,
  这套 fixture 的采纳判据当场失去判别力。
- B5 **a7/a8 红在不同处**(删行破链 / 增行破签名)。
- B6 **不是 benchmark**:不进 runs.jsonl,不影响闸门。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MATRIX = REPO / "docs" / "evidence" / "browser_conformance" / "matrix.json"
ADAPTERS = REPO / "benchmarks" / "v2" / "sidecar_browser" / "adapters"

REQUIRED = {"a0_honest", "a1_never_calls", "a2_reimplements", "a3_fake_package",
            "a4_ignores_result", "a5_wrong_symbol", "a6_replays_receipt",
            "a7_tampers_receipt", "a8_forges_receipt"}


def _m() -> dict:
    if not MATRIX.is_file():
        pytest.skip("矩阵证据未落盘 —— 跑 scripts/browser_conformance.py")
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def test_b1_topology_is_this_suites_and_holds():
    """B1:五条全过,且**是本 suite 的**拓扑。

    反例是实测发生过的:两个 suite 都有 `topology.py`,裸 import 被 sys.modules
    里先到的那个赢走 —— 浏览器矩阵报出来的是 canary 的拓扑(T2 说
    "No module named 'canary_upstream'"),而整张表其余部分全绿。
    `T5.seal_intact` 只有浏览器 suite 才有,拿它当身份标记。"""
    t = _m()["topology"]
    names = {f["check"] for f in t["findings"]}
    assert "T5.seal_intact" in names, f"报的不是本 suite 的拓扑:{sorted(names)}"
    assert names == {"T1.closure_not_in_wheelhouse", "T2.not_importable_by_agent",
                     "T3.sealed_root_is_protected", "T4.no_runtime_hint_in_agent_env",
                     "T5.seal_intact"}
    assert t["ok"], [f for f in t["findings"] if not f["ok"]]


def test_b2_honest_adapter_passes():
    m = _m()
    a0 = next(r for r in m["rows"] if r["adapter"] == "a0_honest")
    assert a0["actual"] == "PASS", f"正控红了 —— 判据成墙:{a0['actual_red']}"


def test_b3_ignoring_the_result_reds_only_on_adoption():
    m = _m()
    a4 = next(r for r in m["rows"] if r["adapter"] == "a4_ignores_result")
    assert a4["actual_red"] == ["U4.adoption"], a4["actual_red"]


def test_b4_naive_reimplementation_fails_adoption():
    """B4:朴素重实现红在 U4 —— 这套 fixture 的判别力全在这一条上。

    它不是稻草人:真抓页面、真按 flex 规范算,数学上完全正确。它对不上的是
    排版引擎的定点 LayoutUnit 与余量分配。这条一旦变绿,说明能力可重实现了,
    采纳判据在这里就白设了。"""
    m = _m()
    a2 = next(r for r in m["rows"] if r["adapter"] == "a2_reimplements")
    assert "U4.adoption" in a2["actual_red"], (
        "朴素重实现竟然通过了采纳 —— 能力可重实现了,fixture 失去判别力")


def test_b5_tamper_and_forge_red_in_different_places():
    m = _m()
    a7 = next(r for r in m["rows"] if r["adapter"] == "a7_tampers_receipt")
    a8 = next(r for r in m["rows"] if r["adapter"] == "a8_forges_receipt")
    assert "U1.chain" in a7["actual_red"] and "U1.signature" not in a7["actual_red"]
    assert "U1.signature" in a8["actual_red"] and "U1.chain" not in a8["actual_red"]


def test_b6_never_enters_the_ledger():
    ids = {json.loads(x).get("run_id", "") for x in
           (REPO / "benchmarks" / "v2" / "runs.jsonl").read_text(
               encoding="utf-8").splitlines() if x.strip()}
    assert not [i for i in ids if i.startswith("bconf-")]
    assert _m()["_not_a_benchmark"]


def test_all_adapters_present_and_match_expectation():
    on_disk = {p.stem for p in ADAPTERS.glob("a*.py")}
    assert REQUIRED - on_disk == set(), sorted(REQUIRED - on_disk)
    m = _m()
    assert m["ok"] is True and m["problems"] == []
    assert {r["adapter"] for r in m["rows"]} == REQUIRED
    for r in m["rows"]:
        if r["expect"] == "FAIL":
            assert sorted(r["actual_red"]) == sorted(r["expect_red"]), r["adapter"]


def test_chromium_never_touches_the_macos_keychain():
    """浏览器启动**不得**碰 macOS 钥匙串。

    实测事故:Chromium 默认向系统钥匙串要 "Chromium Safe Storage",弹出一个
    **模态**的、要登录密码的对话框,启动就此挂住 —— 表现成"浏览器极慢/超时"
    (第一次 16.3s、第二次直接 400),而日志里完全看不出原因。加上
    `--password-store=basic --use-mock-keychain` 之后 16.3s → 2.3s。

    我们每次都是全新的 user-data-dir、用完即删,既不存 cookie 也不存密码,
    那份加密对我们零价值,代价却是一个需要人输密码的弹窗。自动化里绝不该
    有那种东西。"""
    src = (REPO / "benchmarks" / "v2" / "sidecar_browser"
           / "worker.py").read_text(encoding="utf-8")
    assert '"--password-store=basic"' in src
    assert '"--use-mock-keychain"' in src


def test_offline_flags_are_present():
    """离线是跑出来的:Chromium 起在死代理下,只放行 127.0.0.1。"""
    src = (REPO / "benchmarks" / "v2" / "sidecar_browser"
           / "worker.py").read_text(encoding="utf-8")
    assert "--proxy-server=127.0.0.1:1" in src
    assert "--proxy-bypass-list=127.0.0.1;localhost;<local>" in src


_SCRIPT = None


def _script():
    """**只加载一次**:重载会让 suite profile 跟着重建,而
    `register_profile` 的"同 id 不同内容"守卫会当场报警(dispatch 里是函数
    对象,新旧不相等)。守卫是对的,该改的是重复加载。"""
    global _SCRIPT
    if _SCRIPT is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "browser_conformance", REPO / "scripts" / "browser_conformance.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _SCRIPT = mod
    return _SCRIPT


def test_b1b_a_foreign_suites_topology_is_refused(monkeypatch, capsys):
    """B1 的行为面:喂一份**别的 suite 的**拓扑报告,必须当场拒绝出数。

    变异闸门 M54a 抓到的逃逸:原钉死只读落盘证据里的拓扑,而现实里那份一直
    是对的 —— 把守卫整个掏掉也没人看得见。与 M50a/M52b 同型:**检查器必须先
    证明自己查得出**,证明的办法是喂合成缺陷,不是等现实里出问题。

    合成的是 canary 的形状(没有 T5.seal_intact),正是实测发生过的那次。"""
    mod = _script()
    monkeypatch.setattr(mod, "_suite_topology", lambda: (lambda: {
        "ok": True, "findings": [
            {"check": "T1.not_in_wheelhouse", "ok": True, "detail": "canary 的"},
            {"check": "T2.not_importable_cleanly", "ok": True,
             "detail": "No module named 'canary_upstream'"}]}))
    rc = mod.main()
    assert rc == 2, f"别的 suite 的拓扑竟然被接受了(返回 {rc})"
    assert "不是本 suite" in capsys.readouterr().err


@pytest.mark.slow
def test_matrix_is_fresh():
    """真重跑一遍(~36s),结论必须与落盘证据逐条相同。**默认就跑。**"""
    before = {r["adapter"]: r["actual_red"] for r in _m()["rows"]}
    assert _script().main() == 0
    fresh = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert {r["adapter"]: r["actual_red"] for r in fresh["rows"]} == before
