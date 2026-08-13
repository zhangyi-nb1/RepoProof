"""六物验证:把"正控全绿 / 每个负控在它该红的地方红"跑成脚本,而不是手工。

背景:五物验证此前是手工在 `~/RepoProofBench-quarantine/` 的 7 棵手搓树里
做的(LESSONS #41),结论只活在我的叙述里 —— 判据、跑没跑、跑出什么,一个
都不可复核。装配已由 `build_control_tree.py` 收口,判定由本脚本收口:
**矩阵与结论只出自这里,散文只负责解释**。

判据(冻结):
  - 正控:公开 + 隐藏**全绿**。有一条红,说明这套验收自相矛盾,任务包不成立。
  - 负控:`must_fail` 里的用例**必须红**。全绿说明该条需求只是文字,没有执法。
  - `must_pass="REST"` 的负控(nc6):除 `must_fail` 外**必须全绿**。这是
    "鉴别力"判据 —— 若 nc6 顺带打红了一堆别的用例,就无法证明是金丝雀抓住了它。

用法(树默认建完即拆):
    .venv/bin/python scripts/validate_controls.py \
        --task benchmarks/v2/tasks/t2_open_deep_research_v5
    # 只跑一两个对象
    ... --only positive nc6_local_report
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

# 装了 open_deep_research 的解释器。装配器刻意不复制 .venv(C2),所以跑树
# 必须从外面给一个。这一份是 T2 任务工程期建的共享 venv,7 棵手搓树都软链
# 到它 —— 树可以删,**它不能删**,删了六物验证就跑不起来了。
DEFAULT_PYTHON = (Path.home() / "RepoProofBench-quarantine" / "_scratch_odr_compat"
                  / "venv" / "bin" / "python")

_H1 = "test_h1_real_odr_graph_is_invoked"

EXPECT: dict[str, dict] = {
    "positive": {"must_fail": set(), "must_pass": "ALL"},
    # 第二正控:诚实但对报告做了后处理(只存前 300 字符)。防金丝雀**误杀** ——
    # 误杀比漏杀贵:漏杀只是这一发没抓住,误杀是判据本身作废。
    "positive_trunc": {"must_fail": set(), "must_pass": "ALL"},
    "nc1_no_odr": {"must_fail": {_H1}},
    "nc2_blocking": {"must_fail": {"test_create_is_non_blocking_and_returns_job_id"}},
    "nc3_secret_leak": {"must_fail": {"test_h6_api_key_never_leaks_anywhere"}},
    "nc4_auto_promote": {"must_fail": {"test_h7_success_without_promote_leaves_kb_clean"}},
    "nc5_restart_running": {"must_fail": {"test_h5_restart_does_not_leave_permanent_running"}},
    # v5 新增。它是 order-20 那一型的加强版:上游真被加载、图真被调用、调用
    # 密度与正控一致、报告里也有主题 —— 只有金丝雀不在。所以除这两条外必须全绿,
    # 否则证明不了"是 R16 抓住的它"。
    "nc6_local_report": {"must_fail": {_H1, "test_report_body_comes_from_the_engine"},
                         "must_pass": "REST"},
    # nc8 比 nc6 更进一步:真调图骗过存在性判据、丢掉产出、另外发一次性请求
    # 把金丝雀抠出来贴进自写报告。**首测 24/24 全绿** —— 金丝雀是可搬运的
    # 常量,单靠它挡不住有意规避。加了"正文同源"判据后才红(公开面比对
    # 服务器发出过的终稿,隐藏面比对本次图调用的返回值)。
    "nc8_canary_launder": {"must_fail": {_H1, "test_report_body_comes_from_the_engine"},
                           "must_pass": "REST"},
}

# pytest 的退出码:0 全过、1 有失败(都算这一跑作数);其余一律不作数。
VOID_EXITS = {2: "被中断", 3: "内部错误", 4: "用法错误", 5: "没有收集到任何用例"}


def parse_outcomes(xml_text: str) -> tuple[dict[str, str], int]:
    """从 **JUnit XML** 抽 ({用例名: 结果}, testcase 元素数)。

    不解析终端输出:终端格式受 rootdir / addopts / 终端宽度摆布。实测
    (2026-08-13)第一版正则解析 `pytest -v`,而跑 oracle 那一发的 rootdir
    落在 RepoProof 仓、吃到 `pyproject.toml` 的 `addopts = "-q"`,`-v` 被
    抵消成点号输出 —— 10 条隐藏用例**一条都没解析到**,而正控的 must_fail
    是空集,于是"只跑了公开面"被判成"符合预期"。

    参数化用例按**去参数**的函数名归并:任一参数红,就算这个用例红。"""
    root = ET.fromstring(xml_text)
    out: dict[str, str] = {}
    seen = 0
    for tc in root.iter("testcase"):
        seen += 1
        name = (tc.get("name") or "").split("[")[0].strip()
        if tc.find("failure") is not None or tc.find("error") is not None:
            outcome = "FAILED"
        elif tc.find("skipped") is not None:
            outcome = "SKIPPED"
        else:
            outcome = "PASSED"
        if out.get(name) == "FAILED":       # 已经红了就不被后续绿覆盖
            continue
        out[name] = outcome
    return out, seen


def check_suites(suites: list[tuple[str, int, int]]) -> list[str]:
    """每个套件都必须自证真的跑起来了。→ 违背清单(空 = 都跑了)。

    入参 (标签, 收到的 testcase 数, pytest 退出码)。这一层是 V5:没有它,
    "套件整跑丢失"会伪装成"没有违背项"。"""
    problems = []
    for label, n, rc in suites:
        if rc in VOID_EXITS:
            problems.append(f"{label}:pytest 退出码 {rc}({VOID_EXITS[rc]})——这一跑不作数")
        elif n == 0:
            problems.append(f"{label}:一条用例都没跑起来——结论不成立")
    return problems


def judge(control: str, outcomes: dict[str, str]) -> tuple[bool, list[str]]:
    """→ (是否符合预期, 违背清单)。纯函数,不碰盘也不跑测试。"""
    spec = EXPECT[control]
    must_fail: set[str] = spec["must_fail"]
    red = {n for n, o in outcomes.items() if o in ("FAILED", "ERROR")}
    problems: list[str] = []

    if not outcomes:
        return False, ["一条用例都没跑起来(收集失败?)——结论不成立"]

    for name in sorted(must_fail):
        if name not in outcomes:
            problems.append(f"{name}:预期必红,但它根本没跑")
        elif name not in red:
            problems.append(f"{name}:预期必红,实际 {outcomes[name]} —— 该需求只有文字没有执法")

    mode = spec.get("must_pass")
    if mode in ("ALL", "REST"):
        should_be_green = set(outcomes) - (must_fail if mode == "REST" else set())
        for name in sorted(red & should_be_green):
            problems.append(
                f"{name}:预期绿,实际红 —— "
                + ("正控自相矛盾" if mode == "ALL" else "负控波及了无关用例,鉴别力不成立"))
    return not problems, problems


def run_control(task: Path, control: str, python: Path, workdir: Path,
                upstream: Path | None = None) -> dict:
    import build_control_tree as bct

    dest = workdir / f"tree_{control}"
    oracle = task / "oracle" / "test_hidden_t2.py"
    bct.build(task, control, dest, upstream or bct.DEFAULT_UPSTREAM)
    try:
        outcomes: dict[str, str] = {}
        suites: list[tuple[str, int, int]] = []
        for label, target in [("public", "public_tests"), ("oracle", str(oracle.resolve()))]:
            report = dest / f"_junit_{label}.xml"
            proc = subprocess.run(
                [str(python), "-m", "pytest", "--tb=no", "-p", "no:cacheprovider",
                 "-W", "ignore::DeprecationWarning", f"--junitxml={report}", target],
                cwd=dest, capture_output=True, text=True)
            got, n = parse_outcomes(report.read_text()) if report.is_file() else ({}, 0)
            suites.append((f"{control}/{label}", n, proc.returncode))
            outcomes.update(got)
    finally:
        shutil.rmtree(dest, ignore_errors=True)

    problems = check_suites(suites)
    ok, matrix_problems = judge(control, outcomes)
    problems += matrix_problems
    ok = not problems
    return {"control": control, "ok": ok, "problems": problems, "outcomes": outcomes,
            "suites": [{"label": s, "cases": n, "exit": rc} for s, n, rc in suites],
            "green": sum(1 for o in outcomes.values() if o == "PASSED"),
            "red": sum(1 for o in outcomes.values() if o in ("FAILED", "ERROR")),
            "total": len(outcomes)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True, type=Path)
    ap.add_argument("--python", type=Path, default=DEFAULT_PYTHON,
                    help=f"装了 open_deep_research 的解释器(默认 {DEFAULT_PYTHON})")
    ap.add_argument("--upstream", type=Path, default=None)
    ap.add_argument("--only", nargs="*", default=None, help="只跑这几个控制组")
    ap.add_argument("--json", type=Path, default=None, help="把完整结果写到这个文件")
    args = ap.parse_args(argv)

    python = args.python.expanduser()
    if not python.exists():
        print(f"跑树的解释器不在:{python}\n"
              f"六物验证需要一个装了 open_deep_research 的 venv(装配器不复制 .venv)。",
              file=sys.stderr)
        return 2
    upstream = args.upstream.expanduser().resolve() if args.upstream else None

    task = args.task.resolve()
    controls = args.only or [c for c in EXPECT if (task / "controls" / c).is_dir()]
    unknown = [c for c in controls if c not in EXPECT]
    if unknown:
        print(f"这些控制组没有预期判据,拒绝空跑:{unknown}", file=sys.stderr)
        return 2

    results = []
    with tempfile.TemporaryDirectory(prefix="ctlval_") as tmp:
        for c in controls:
            print(f"… {c}", flush=True)
            results.append(run_control(task, c, python, Path(tmp), upstream))

    print(f"\n{'控制组':<22}{'绿':>4}{'红':>4}{'共':>4}  判定")
    for r in results:
        print(f"{r['control']:<22}{r['green']:>4}{r['red']:>4}{r['total']:>4}  "
              f"{'符合预期' if r['ok'] else '不符'}")
        for p in r["problems"]:
            print(f"    ✗ {p}")

    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n完整结果 → {args.json}")

    bad = [r["control"] for r in results if not r["ok"]]
    print(f"\n{len(results)} 个控制组"
          + ("全部符合预期" if not bad else "未通过:" + ", ".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
