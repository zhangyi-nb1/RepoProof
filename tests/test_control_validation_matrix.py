"""六物验证判定逻辑的钉死(`scripts/validate_controls.py`)。

**冻结判据**(先写判据与反例,再写实现;措辞此后不改):

- V1 预期必红的必须真红:`must_fail` 里的用例全绿 → 判不符。反例:R16 若
  只写进契约、忘了写进 oracle,nc6 会**全绿** —— 手工验证时"全绿"极容易
  被读成"通过",而它的真实含义是"这条需求只有文字没有执法"。
- V2 鉴别力:`must_pass="REST"` 的负控除 `must_fail` 外必须全绿。反例:
  若 nc6 顺带把 h2/h3 也打红了,就无法证明"是金丝雀抓住了它" —— 可能是
  它把整个子系统弄坏了,换任何一条判据都会红。
- V3 空跑绝不算通过:一条用例都没收集到时必须判不符。反例:树装错或
  collect 失败时 pytest 输出里没有任何 PASSED/FAILED 行,而正控的
  `must_fail` 是空集 —— 朴素实现会因"没有违背项"而发绿,把**什么都没跑**
  判成**全绿**。这是本文件最该防的一种假通过。
- V4 参数化用例按函数名归并,任一参数红即算红。反例:
  `test_existing_routes_still_work` 有 3 个参数,只有一个红时不得算绿。
- V5 每个套件必须自证真的跑起来了:收到 0 条用例、或 pytest 以 2/3/4/5
  退出,这一跑一律不作数。反例(**2026-08-13 实测,本脚本第一版的真实缺陷**):
  第一版用正则解析 `pytest -v` 的终端输出,而跑 oracle 那一发的 rootdir
  落在 RepoProof 仓、吃到 `pyproject.toml` 里的 `addopts = "-q"`,`-v` 被
  抵消成点号输出 —— 10 条隐藏用例**一条都没解析到**。正控的 must_fail 是
  空集,于是"只跑了公开面"被判成"符合预期"。这是 V3 的**部分版本**:
  比"什么都没跑"更难发现,因为矩阵里确实有一排绿。故解析改走 JUnit XML
  (不受 rootdir/addopts/终端宽度摆布),并加这一层自证。

判据只管**判定**;控制组各自的语义(nc6 真的丢掉了引擎正文等)由脚本
实跑执法,不在这里。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_H1 = "test_h1_real_odr_graph_is_invoked"
_CANARY = "test_report_body_comes_from_the_engine"


def _load(script: str):
    """按**文件路径**加载 —— 红绿/变异闸门用 `PYTHONPATH=<树>/src` 隔离运行,
    包导入在那里找不到 scripts/;这也保证考的是树里那份,不是工作区那份。"""
    spec = importlib.util.spec_from_file_location(script[:-3], REPO / "scripts" / script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nc6_outcomes(**overrides: str) -> dict[str, str]:
    """nc6 的一份"理想"结果:两条该红的红,其余全绿。"""
    base = {_H1: "FAILED", _CANARY: "FAILED",
            "test_h2_concurrent_jobs_do_not_cross": "PASSED",
            "test_h3_duplicate_submit_follows_frozen_policy": "PASSED",
            "test_report_reflects_research_topic": "PASSED",
            "test_upstream_graph_module_engaged": "PASSED"}
    base.update(overrides)
    return base


def test_must_fail_all_green_means_the_requirement_is_only_text():
    """V1:该红的全绿 —— 需求没有执法,必须判不符。"""
    judge = _load("validate_controls.py").judge

    ok, problems = judge("nc6_local_report",
                         _nc6_outcomes(**{_H1: "PASSED", _CANARY: "PASSED"}))

    assert ok is False
    assert any(_CANARY in p and "预期必红" in p for p in problems), problems


def test_expected_reds_actually_red_is_a_pass():
    """V1 的另一面:该红的真红、其余全绿 → 符合预期。"""
    judge = _load("validate_controls.py").judge

    ok, problems = judge("nc6_local_report", _nc6_outcomes())

    assert ok is True, problems


def test_collateral_red_destroys_discrimination():
    """V2:负控把无关用例也打红了,证明不了是哪条判据抓住的它。"""
    judge = _load("validate_controls.py").judge

    ok, problems = judge(
        "nc6_local_report",
        _nc6_outcomes(test_h2_concurrent_jobs_do_not_cross="FAILED"))

    assert ok is False
    assert any("鉴别力" in p for p in problems), problems


def test_positive_control_any_red_is_a_contradiction():
    """V2 用在正控上:正控红一条,说明这套验收自相矛盾。"""
    judge = _load("validate_controls.py").judge

    ok, problems = judge("positive", {"test_a": "PASSED", "test_b": "FAILED"})

    assert ok is False
    assert any("正控自相矛盾" in p for p in problems), problems


def test_nothing_collected_is_never_a_pass():
    """V3:一条都没跑起来时,正控的 must_fail 是空集 —— 不得因此发绿。"""
    judge = _load("validate_controls.py").judge

    ok, problems = judge("positive", {})

    assert ok is False, "什么都没跑却判通过 —— 这正是假通过的原型"
    assert problems


def test_must_fail_case_that_never_ran_is_not_a_pass():
    """V3 的近亲:该红的那条根本没被收集到,不能算它红了。"""
    judge = _load("validate_controls.py").judge

    outcomes = _nc6_outcomes()
    outcomes.pop(_H1)
    ok, problems = judge("nc6_local_report", outcomes)

    assert ok is False
    assert any(_H1 in p and "没跑" in p for p in problems), problems


def _junit(*cases: tuple[str, str]) -> str:
    """拼一份 JUnit XML。cases 是 (name, "" | "failure" | "error" | "skipped")。"""
    body = ""
    for name, kind in cases:
        inner = f"<{kind} message='x'>d</{kind}>" if kind else ""
        body += f"<testcase classname='m' name='{name}' time='0.1'>{inner}</testcase>"
    return f"<testsuites><testsuite name='pytest' tests='{len(cases)}'>{body}</testsuite></testsuites>"


def test_parametrized_outcomes_merge_and_a_single_red_wins():
    """V4:参数化用例按函数名归并,任一参数红即算红(绿不得覆盖红)。"""
    parse = _load("validate_controls.py").parse_outcomes

    got, n = parse(_junit(
        ("test_existing_routes_still_work[/health]", ""),
        ("test_existing_routes_still_work[/api/x]", "failure"),
        ("test_existing_routes_still_work[/docs]", ""),
        ("test_flag_off_by_default_no_research_api", "")))

    assert got["test_existing_routes_still_work"] == "FAILED", got
    assert got["test_flag_off_by_default_no_research_api"] == "PASSED", got
    assert n == 4, "testcase 元素数必须如实上报,套件整跑丢失全靠它暴露"


def test_error_counts_as_red_not_as_green():
    """V4 的边角:collect/fixture 阶段的 error 也是红,不能算绿。"""
    parse = _load("validate_controls.py").parse_outcomes

    got, _ = parse(_junit(("test_h1_real_odr_graph_is_invoked", "error")))

    assert got["test_h1_real_odr_graph_is_invoked"] == "FAILED", got


def test_a_suite_that_ran_nothing_voids_the_verdict():
    """V5:套件收到 0 条用例 —— 这正是 oracle 那一跑整个丢失时的形状。"""
    check_suites = _load("validate_controls.py").check_suites

    problems = check_suites([("positive/public", 14, 0), ("positive/oracle", 0, 0)])

    assert any("oracle" in p and "一条用例都没跑起来" in p for p in problems), problems


def test_pytest_internal_exit_codes_void_the_run():
    """V5:退出码 2/3/4/5 一律不作数 —— 跑了几条也不能拿来下结论。"""
    check_suites = _load("validate_controls.py").check_suites

    for rc in (2, 3, 4, 5):
        problems = check_suites([("positive/oracle", 7, rc)])
        assert problems, f"退出码 {rc} 被当成了有效的一跑"
        assert "不作数" in problems[0], problems


def test_both_suites_healthy_raises_no_problem():
    """V5 的另一面:两个套件都真跑了,这一层不该无中生有。"""
    check_suites = _load("validate_controls.py").check_suites

    assert check_suites([("positive/public", 14, 0), ("positive/oracle", 10, 1)]) == []
