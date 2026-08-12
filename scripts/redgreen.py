"""红-绿留痕:证明一次修复的钉死测试**真的在抓那个缺陷**。

原理(PROCESS-INDEPENDENCE-PLAN §5-P0-3):照着已完成的实现写出的测试
几乎不可能不通过——"只有绿"证明不了任何东西。有效钉死的定义是:
在**未修复**的代码上 FAIL(红),在修复后的代码上 PASS(绿)。
本脚本对给定修复 commit 机械地验证这两段,并把证据落盘:

    docs/evidence/redgreen/<fix12>.txt

隔离方式:两个临时 git worktree(base=修复前 / fix=修复后),把 fix 的
tests/ 覆盖进 base 树(测试是考官,源码是考生),`PYTHONPATH=<树>/src`
压过 editable 安装(已实测优先级),逐节点用 junitxml 判定——不信 pytest
退出码孤证(节点名写错也非零,exit 4 会冒充红)。

exit 4 的两义性(2026-08-12,LESSONS #34 首咬):按节点名跑时,
"模块 import 不进去"(新符号还不存在=最强的红)与"节点名打错"
(用法错=不是红)都报 exit 4 + found no collectors。二者用两个机器
条件区分,缺一即判 INVALID:
  ① 所有节点名在**绿段**逐名 passed —— 名字打错不可能在 fix 上通过;
  ② 用文件路径重跑 base 段,该测试文件必须报出 Import/Attribute/Name
     类收集错误(证明是"符号不存在",不是别的毛病)。
不放宽到"exit 4 一律算红"——那等于把守卫拆了。

用法:
    .venv/bin/python scripts/redgreen.py --fix <commit> \
        tests/test_x.py::test_a tests/test_x.py::test_b
    # base 默认 <fix>~1;--out 缺省 docs/evidence/redgreen/
任一节点在 base 上没红、或在 fix 上没绿 → 判 INVALID,非零退出。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTEST = REPO / ".venv" / "bin" / "pytest"

# "特性还不存在"的收集错误长相。刻意只认符号/模块缺失类——
# SyntaxError、conftest 崩溃之类不算红(那是环境坏了,不是缺陷被抓住)。
_SYMBOL_ABSENT = re.compile(
    r"ImportError|ModuleNotFoundError|AttributeError|NameError|cannot import name")


def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _node_results(junit: Path) -> dict[str, str]:
    """junit xml → {测试函数名: passed|failed|error|skipped}。"""
    out: dict[str, str] = {}
    for case in ET.parse(junit).getroot().iter("testcase"):
        name = case.attrib.get("name", "")
        if case.find("failure") is not None:
            out[name] = "failed"
        elif case.find("error") is not None:
            out[name] = "error"
        elif case.find("skipped") is not None:
            out[name] = "skipped"
        else:
            out[name] = "passed"
    return out


def _collection_errors(junit: Path) -> list[tuple[str, str]]:
    """junit xml → [(测试项标识, 错误文本)],只取 <error> 项(收集期死)。"""
    out: list[tuple[str, str]] = []
    for case in ET.parse(junit).getroot().iter("testcase"):
        err = case.find("error")
        if err is not None:
            ident = f"{case.attrib.get('classname', '')} {case.attrib.get('name', '')}"
            out.append((ident.strip(), f"{err.attrib.get('message', '')}\n{err.text or ''}"))
    return out


def _run_pytest(tree: Path, targets: list[str], junit: Path,
                *, extra: tuple[str, ...] = ()) -> tuple[int, str]:
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    proc = subprocess.run(
        [str(PYTEST), *targets, "-q", "-p", "no:cacheprovider",
         *extra, f"--junitxml={junit}"],
        cwd=tree, env=env, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)[-2000:]


def _phase(commit: str, nodes: list[str], *, tests_from: str | None,
           probe_files: list[str] | None = None) -> dict:
    """在 <commit> 的临时 worktree 上跑 nodes;tests_from 非空则先覆盖 tests/。

    probe_files 非空时,同一棵树上再按**文件路径**跑一遍并收集收集期错误
    ——用于辨清 exit 4 是"符号不存在"还是"节点名打错"。
    """
    with tempfile.TemporaryDirectory(prefix="rp_redgreen_") as td:
        tree = Path(td) / "tree"
        _git("worktree", "add", "--detach", str(tree), commit)
        try:
            if tests_from:
                _git("checkout", tests_from, "--", "tests", cwd=tree)
            junit = Path(td) / "junit.xml"
            code, tail = _run_pytest(tree, nodes, junit)
            results = _node_results(junit) if junit.exists() else {}
            collect: list[tuple[str, str]] = []
            if probe_files:
                pj = Path(td) / "probe.xml"
                _run_pytest(tree, probe_files, pj,
                            extra=("--continue-on-collection-errors",))
                collect = _collection_errors(pj) if pj.exists() else []
            return {"exit": code, "results": results, "tail": tail,
                    "collect_errors": collect}
        finally:
            _git("worktree", "remove", "--force", str(tree))
            _git("worktree", "prune")


def judge(*, names: list[str], red_exit: int, red_results: dict[str, str],
          green_results: dict[str, str], red_collect: list[tuple[str, str]],
          files: list[str]) -> list[str]:
    """纯判定:返回问题清单(空=VALID)。与 IO 分离以便直接钉死。"""
    problems: list[str] = []
    for n in names:
        r = red_results.get(n, "error-at-collection")
        g = green_results.get(n, "missing")
        if r not in ("failed", "error", "error-at-collection"):
            problems.append(f"{n}: 在 base 上是 {r} —— 没有红,钉不住缺陷")
        if g != "passed":
            problems.append(f"{n}: 在 fix 上是 {g} —— 没有绿")
    if red_exit == 4:
        # 名字真伪由绿段作证:打错的名字不可能在 fix 上逐名 passed。
        names_real = all(green_results.get(n) == "passed" for n in names)
        stems = {Path(f).stem for f in files}
        matched = [(i, t) for i, t in red_collect if any(s in i for s in stems)]
        genuine = bool(names_real and matched
                       and all(_SYMBOL_ABSENT.search(t) for _, t in matched))
        if not genuine:
            problems.append(
                "base 段 pytest exit=4,且未证明是「符号不存在」型收集错误"
                f"(节点名可信={names_real}, 该文件收集错误={len(matched)} 条)"
                "——这不是红")
    return problems


def redgreen(fix: str, base: str | None, nodes: list[str]) -> tuple[bool, str]:
    fix_sha = _git("rev-parse", fix)
    base_sha = _git("rev-parse", base or f"{fix_sha}~1")
    names = [n.rsplit("::", 1)[-1] for n in nodes]

    files = sorted({n.split("::", 1)[0] for n in nodes})
    # 考官来自 fix,考生是 base;顺手按文件跑一遍以辨清 exit 4 的性质
    red = _phase(base_sha, nodes, tests_from=fix_sha, probe_files=files)
    green = _phase(fix_sha, nodes, tests_from=None)

    # 逐节点判定:junit 里查无此名 = collection 阶段死(ImportError 等)。
    # 红段的 collection 死是合法的红(修复前连符号都不存在);绿段必须逐名 passed。
    problems = judge(names=names, red_exit=red["exit"],
                     red_results=red["results"], green_results=green["results"],
                     red_collect=red["collect_errors"], files=files)
    valid = not problems

    lines = [
        f"fix commit : {fix_sha}",
        f"base commit: {base_sha}",
        f"nodes      : {len(nodes)}",
        "", "== RED(base 源码 × fix 测试;期望全 FAIL) ==",
        f"pytest exit={red['exit']}",
        *(f"  {n}: {red['results'].get(n, 'error-at-collection')}" for n in names),
        *(["", "-- base 段收集错误(按文件重跑取证)--",
           *(f"  [{i}] {t.strip().splitlines()[-1][:200] if t.strip() else ''}"
             for i, t in red["collect_errors"])] if red["collect_errors"] else []),
        red["tail"], "", "== GREEN(fix 源码 × fix 测试;期望全 PASS) ==",
        f"pytest exit={green['exit']}",
        *(f"  {n}: {green['results'].get(n, 'missing')}" for n in names),
        green["tail"], "",
        f"VERDICT: {'VALID' if valid else 'INVALID'}",
        *(f"  ✗ {p}" for p in problems),
    ]
    return valid, "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", required=True, help="修复 commit(其 tests/ 是考官)")
    ap.add_argument("--base", default=None, help="缺省 <fix>~1")
    ap.add_argument("--out", default=str(REPO / "docs" / "evidence" / "redgreen"))
    ap.add_argument("nodes", nargs="+")
    a = ap.parse_args()
    ok, report = redgreen(a.fix, a.base, a.nodes)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / f"{_git('rev-parse', '--short=12', a.fix)}.txt"
    dest.write_text(report, encoding="utf-8")
    print(report)
    print(f"证据已落盘:{dest}")
    sys.exit(0 if ok else 1)
