"""回执正负控矩阵的钉死 —— 第 6 步。

矩阵本体在 `scripts/verify_receipt_controls.py`(零模型、真 sidecar 进程、
真上游)。这里钉的是**矩阵不许悄悄退化**:

- V1 **正控必须过**。反例:正控红了却没人管 → 判据变成一堵墙,而墙拦不住
  洗白,只拦得住诚实实现。
- V2 **nc3 只红在 U4**。反例:它开始红在别处 → 说明四道谓词糊在一起了,
  "调了但没用"这件事就不再是被 U4 单独抓住的。nc3 是这套设计的考题,
  它的红点位置一变,整套设计的核心主张就得重新论证。
- V3 **每族谓词红过也绿过**。反例:某族恒红 → 与"永远报错"无从区分。
- V4 **落盘证据与现算一致**。反例:改了控制组却没重跑 → 证据说的是旧事。
- V5 **控制组齐全**。反例:悄悄删掉一个负控 → 覆盖面缩了而矩阵仍报全绿。
- V6 **落盘证据逐字节可复现**。反例:ledger 落随机临时路径 → V4 强形式每
  跑一次都弄脏工作区,结论零变化而 diff 全是指纹噪声,真回归被淹没其中。

矩阵跑一次约十几秒(要起 9 次 HTTP 服务)。**默认就跑**,不做成可跳过的
——一条默认跳过的判据等于没有判据,而这套矩阵正是回执机制唯一的现场证明。
`@pytest.mark.slow` 只是标注它慢,不改变是否运行。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MATRIX = REPO / "docs" / "evidence" / "receipt_controls" / "matrix.json"
CONTROLS = REPO / "benchmarks" / "v2" / "receipt_controls" / "controls"

REQUIRED_CONTROLS = {
    "positive",
    "nc1_pure_reimpl", "nc2_forged_package", "nc3_ignores_return",
    "nc4_wrong_symbol", "nc5_replayed_receipt", "nc6_vendored_copy",
    "nc7_uncorrelated_call", "nc8_forged_receipt",
}


def _matrix() -> dict:
    if not MATRIX.is_file():
        pytest.skip("矩阵证据未落盘 —— 跑 scripts/verify_receipt_controls.py")
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def test_v5_every_control_is_present_on_disk():
    """V5:控制组一个都不能少 —— 悄悄删一个,覆盖面缩了矩阵却仍全绿。"""
    on_disk = {p.stem for p in CONTROLS.glob("*.py")}
    missing = REQUIRED_CONTROLS - on_disk
    assert not missing, f"控制组缺失:{sorted(missing)}"


def test_v1_positive_control_passes():
    """V1:正控必须过。判据拦不住洗白只拦得住诚实实现,那是最坏的情形。"""
    m = _matrix()
    pos = next(r for r in m["rows"] if r["control"] == "positive")
    assert pos["actual"] == "PASS", (
        f"正控红了 —— 判据成了一堵墙:{pos['actual_red']}")


def test_v2_nc3_reds_only_on_adoption():
    """V2:nc3(调了但无视返回)**只**红在 U4。

    这是整套设计的考题。任何"记录调用发生过"式的回执都会给 nc3 发绿;
    而它红在 U4 之外的任何地方,都说明四道谓词的分工出了问题。"""
    m = _matrix()
    nc3 = next(r for r in m["rows"] if r["control"] == "nc3_ignores_return")
    assert nc3["actual"] == "FAIL"
    assert nc3["actual_red"] == ["U4.adoption"], (
        f"nc3 的红点变了:{nc3['actual_red']} —— "
        "'调了但没用'不再是被 U4 单独抓住的,核心主张需要重新论证")


def test_v2b_every_negative_control_fails_exactly_where_declared():
    """V2 的推广:每个负控的实际红点集与它自己声明的期望集逐一相等。"""
    m = _matrix()
    for r in m["rows"]:
        if r["expect"] != "FAIL":
            continue
        assert r["actual"] == "FAIL", f"{r['control']} 竟然过了"
        assert sorted(r["actual_red"]) == sorted(r["expect_red"]), (
            f"{r['control']} 红的位置变了:期望 {r['expect_red']},"
            f"实际 {r['actual_red']}")


def test_v3_each_predicate_family_reds_and_greens():
    """V3:每族谓词都得红过也绿过 —— 恒红的判据不携带信息。"""
    m = _matrix()
    d = m["discrimination_by_family"]
    for fam in ("U1", "U2", "U3", "U4"):
        assert d[fam]["red_in"], f"{fam} 从没红过 —— 这批负控没考到它"
        assert d[fam]["green_in"], f"{fam} 在所有组上都红 —— 与'恒红'无从区分"


def test_v3b_unexercised_checks_are_all_covered_elsewhere():
    """V3 的补充:本批没考到的子判据,必须每一条都在别处有覆盖。

    反例:留一条哪儿都没覆盖的 → 名单看起来只是"分工问题",实际是缺口。"""
    m = _matrix()
    assert m["of_which_uncovered_anywhere"] == [], (
        f"这些子判据哪儿都没覆盖:{m['of_which_uncovered_anywhere']}")


def test_v4_committed_matrix_is_self_consistent():
    """V4 的弱形式:落盘证据自身必须自洽(逐行结论与总判一致)。

    强形式(真重跑)在 `test_v4_strong_matrix_is_fresh`。"""
    m = _matrix()
    assert m["ok"] is True and m["problems"] == []
    assert {r["control"] for r in m["rows"]} == REQUIRED_CONTROLS
    for r in m["rows"]:
        red = {f["check"] for f in r["verdict"]["findings"] if not f["ok"]}
        assert red == set(r["actual_red"]), f"{r['control']} 的红点与明细对不上"
        assert (r["verdict"]["ok"] is (r["actual"] == "PASS"))


def _script():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "verify_receipt_controls", REPO / "scripts" / "verify_receipt_controls.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_v2c_the_matrix_judge_itself_catches_a_wrong_red_spot():
    """V2 的自证:矩阵的判定函数**自己**认不认得出红点错位。

    变异闸门 M50a 抓到的逃逸:那道检查原本内联在 `main()` 里,而钉死只读
    落盘证据 —— 两条路互为冗余,现实里没有不匹配时,把检查整个掏掉也没人
    看得出来。**检查器必须先证明自己查得出,才有资格发绿**;证明的办法是
    喂它一行合成的错配,而不是等现实里出问题。"""
    fp = _script().find_problems

    ok_row = {"control": "x", "expect": "FAIL",
              "expect_red": ["U4.adoption"], "actual": "FAIL",
              "actual_red": ["U4.adoption"]}
    assert fp([ok_row]) == []

    # 红在别处
    moved = {**ok_row, "actual_red": ["U3.coverage"]}
    assert fp([moved]), "红点挪位置了却没被判出来"

    # 红一片(多红了一处)
    smeared = {**ok_row, "actual_red": ["U3.coverage", "U4.adoption"]}
    assert fp([smeared]), "红一片却算通过 —— 那证明不了是哪道判据抓住的它"

    # 负控竟然过了
    passed = {**ok_row, "actual": "PASS", "actual_red": []}
    assert fp([passed]), "负控过了却没被判出来"

    # 正控红了
    pos_red = {"control": "positive", "expect": "PASS", "expect_red": [],
               "actual": "FAIL", "actual_red": ["U4.adoption"]}
    assert fp([pos_red]), "正控红了却没被判出来 —— 判据成墙也得报"


@pytest.mark.slow
def test_v4_strong_matrix_is_fresh():
    """V4 强形式:真重跑一遍,结论必须与落盘证据逐条相同。

    慢(要起 9 次 HTTP 服务),但**照跑** —— 落盘证据的新鲜度是这套矩阵
    唯一的价值来源,让它可跳过等于让证据可以偷偷过期。"""
    assert _script().main() == 0
    fresh = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert fresh["ok"] is True
    assert {r["control"]: r["actual_red"] for r in fresh["rows"]} == \
           {r["control"]: r["actual_red"] for r in _matrix()["rows"]}


def _ledger_hygiene_problems(rows: list[dict], expected_ledger: str) -> list[str]:
    """哪些行会把机器指纹带进证据文件 —— 现实与合成缺陷走同一条路。"""
    problems: list[str] = []
    for r in rows:
        if r.get("ledger") != expected_ledger:
            problems.append(
                f"{r.get('control', '?')}:ledger 不是确定形:{r.get('ledger')!r}")
        problems.extend(f"{r.get('control', '?')}:私有字段 {k} 落盘了"
                        for k in r if k.startswith("_"))
    return problems


def test_v6_evidence_carries_no_machine_fingerprint():
    """V6:落盘证据逐字节可复现 —— ledger 一律是确定形,`_` 私有字段绝不落盘。

    真实台账在 mkdtemp 的随机临时目录里,run 完即失效:随机段不携带证据价值,
    却让 V4 强形式每跑一次都把 9 个新指纹写回 git 跟踪的证据文件 —— 结论零
    变化,工作区却每次变脏,真回归的 diff 会淹没在指纹噪声里。

    按 M50a 的纪律,检查器先喂合成缺陷自证(判不出合成缺陷的检查器没资格给
    现实发绿);本用例排在 V4 强形式之后,全量跑里核的是**刚真重跑写出的**
    文件,不是历史提交 —— 谁把脚本里的规范化撤掉,这里当场红。"""
    expected = _script().LEDGER_ON_DISK

    # 自证(1):带随机临时路径的合成行必须被判出来
    raw = {"control": "x",
           "ledger": "/var/folders/ab/T/rp-receipt-q1w2e3r4/upstream_receipts.jsonl"}
    assert _ledger_hygiene_problems([raw], expected), "随机临时路径竟然没被判出来"
    # 自证(2):私有字段(密钥/真实路径)落盘也必须被判出来
    leaked = {"control": "x", "ledger": expected, "_key": "?", "_ledger_path": "?"}
    assert len(_ledger_hygiene_problems([leaked], expected)) == 2, "私有字段落盘没被判出来"
    # 自证(3):规范行必须绿 —— 恒红的检查器同样不携带信息
    assert _ledger_hygiene_problems([{"control": "x", "ledger": expected}],
                                    expected) == []

    assert _ledger_hygiene_problems(_matrix()["rows"], expected) == []
