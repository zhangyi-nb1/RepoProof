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

用法:
    .venv/bin/python scripts/redgreen.py --fix <commit> \
        tests/test_x.py::test_a tests/test_x.py::test_b
    # base 默认 <fix>~1;--out 缺省 docs/evidence/redgreen/
任一节点在 base 上没红、或在 fix 上没绿 → 判 INVALID,非零退出。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTEST = REPO / ".venv" / "bin" / "pytest"


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


def _run_nodes(tree: Path, nodes: list[str], junit: Path) -> tuple[int, str]:
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    proc = subprocess.run(
        [str(PYTEST), *nodes, "-q", "-p", "no:cacheprovider",
         f"--junitxml={junit}"],
        cwd=tree, env=env, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)[-2000:]


def _phase(commit: str, nodes: list[str], *, tests_from: str | None) -> dict:
    """在 <commit> 的临时 worktree 上跑 nodes;tests_from 非空则先覆盖 tests/。"""
    with tempfile.TemporaryDirectory(prefix="rp_redgreen_") as td:
        tree = Path(td) / "tree"
        _git("worktree", "add", "--detach", str(tree), commit)
        try:
            if tests_from:
                _git("checkout", tests_from, "--", "tests", cwd=tree)
            junit = Path(td) / "junit.xml"
            code, tail = _run_nodes(tree, nodes, junit)
            results = _node_results(junit) if junit.exists() else {}
            return {"exit": code, "results": results, "tail": tail}
        finally:
            _git("worktree", "remove", "--force", str(tree))
            _git("worktree", "prune")


def redgreen(fix: str, base: str | None, nodes: list[str]) -> tuple[bool, str]:
    fix_sha = _git("rev-parse", fix)
    base_sha = _git("rev-parse", base or f"{fix_sha}~1")
    names = [n.rsplit("::", 1)[-1] for n in nodes]

    red = _phase(base_sha, nodes, tests_from=fix_sha)   # 考官来自 fix,考生是 base
    green = _phase(fix_sha, nodes, tests_from=None)

    # 逐节点判定:junit 里查无此名 = collection 阶段死(ImportError 等)。
    # 红段的 collection 死是合法的红(修复前连符号都不存在);绿段必须逐名 passed。
    problems: list[str] = []
    for n in names:
        r = red["results"].get(n, "error-at-collection")
        g = green["results"].get(n, "missing")
        if r not in ("failed", "error", "error-at-collection"):
            problems.append(f"{n}: 在 base 上是 {r} —— 没有红,钉不住缺陷")
        if g != "passed":
            problems.append(f"{n}: 在 fix 上是 {g} —— 没有绿")
    if red["exit"] == 4:
        problems.append("base 段 pytest exit=4(用法错误/节点名不存在)——这不是红")
    valid = not problems

    lines = [
        f"fix commit : {fix_sha}",
        f"base commit: {base_sha}",
        f"nodes      : {len(nodes)}",
        "", "== RED(base 源码 × fix 测试;期望全 FAIL) ==",
        f"pytest exit={red['exit']}",
        *(f"  {n}: {red['results'].get(n, 'error-at-collection')}" for n in names),
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
