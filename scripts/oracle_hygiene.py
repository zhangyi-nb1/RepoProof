#!/usr/bin/env python3
"""oracle 卫生电池 —— v2 卫生判据的执行器(prereg-v2 §1/§3;判定钉死 H1–H6)。

回答:这套上游套件配不配当 held-out 的尺子。判定是纯函数 `judge_hygiene`
与 `judge_statement_determinacy`,跑套件的循环只搬数字:

    七跑(基准 ×3 + COLUMNS/TZ/LANG/TMPDIR 各 1)→ S-a 集合稳定
    + 钦定跑法单发计时(≤120s;首轮已测值按同协议沿用)
    + FAIL_TO_PASS 双向实测(parent+delta 恰红 delta 集;post 树全绿)
    + H6 题面欠定探测(讨论式 PR 正文不宜作题面;--statement 必给)
    → 卫生判决,记录落 docs/evidence/d5_hunt/hygiene/

用法(封存池重审):
    .venv/bin/python scripts/oracle_hygiene.py \\
        --candidate sqlglot-8042 \\
        --parent-tree ~/RepoProofArchive/d5-hunt/candidates/sqlglot-8042/parent_tree \\
        --wheelhouse ~/RepoProofArchive/d5-hunt/wheelhouse/sqlglot \\
        --delta-post-dir ~/RepoProofArchive/d5-hunt/candidates/sqlglot-8042/delta_tests/post \\
        --answer-patch ~/RepoProofArchive/d5-hunt/candidates/sqlglot-8042/answer/full.patch \\
        --tests-patch ~/RepoProofArchive/d5-hunt/candidates/sqlglot-8042/delta_tests/tests.patch \\
        --statement ~/RepoProofArchive/d5-hunt/candidates/sqlglot-8042/statement.md \\
        --canonical-seconds 60.84 \\
        [--extra-packages duckdb,pandas,python-dateutil,pytz,typing_extensions] \\
        [--pretend-version 0.0.0]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "docs" / "evidence" / "d5_hunt" / "hygiene"


def _load_driver():
    if "blind_attack_admission" in sys.modules:
        return sys.modules["blind_attack_admission"]
    spec = importlib.util.spec_from_file_location(
        "blind_attack_admission", REPO / "scripts" / "blind_attack_admission.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["blind_attack_admission"] = mod
    spec.loader.exec_module(mod)
    return mod


_bam = _load_driver()
# 只引用,不复制(H3):判定副本会在原件改动后静默漂移(M58a 的形状)
measurement_problems = _bam.measurement_problems
score_from_junit = _bam.score_from_junit
offline_env = _bam.offline_env
venv_env = _bam.venv_env

# prereg-v2 §1.2:钦定跑法单发 ≤120s。60s 是 v1 的便利线,首轮把供给最好的
# 仓整族杀掉(实测 60.84–88.9s);120 覆盖实测人口 + 增长余量,同时保住
# 准入电池(~11 跑 ≤22 分钟/候选)与未来考试发次(套件时间 ≤~2 分钟/次)
# 的成本上界。协议不变:静机、单发、预声明不重试。改线要新的实测 + 用户
# 重新冻结,不是新的直觉。
MAX_CANONICAL_SECONDS = 120


# ---------------------------------------------------------------- H6:题面欠定
# 由 click-3407 的实测教训成文(V2GEN-GPT-EXT-1,2026-08-21):两个模型在同一
# 隐藏节点双 FAIL,读题面 vs 答案后定因 —— 隐藏节点要求 ParamType 泛型化 +
# PEP 696 默认 + __class_getitem__ 运行期回填,而题面是一篇**三选项的开放式
# 设计讨论**,结尾写着 "# My preference?"。这种题不是难,是**没定**:上游 PR
# 正文当时还在征求意见,答案是讨论之后才收敛的,题面里没有那个收敛。
#
# 判据设计的两次修正(先量后定,不凭直觉):
#   ① 最初想用"答案 patch 新增的公共标识符是否出现在题面"——**实测无判别
#      力**:好题一样中(sqlglot-8042 漏 2 个、click-3581 漏 1 个)。题面本来
#      就不该逐字给出实现标识符,这条会把整池好题一起判死。
#   ② 改测**体裁标记**:选项分节 + 对冲措辞。全池 14 候选实测,只有
#      click-3407 命中(3 选项分节 / 1 疑问行 / 5 种不同对冲措辞),其余 13
#      条全为 0/0/0 —— 分离干净。
# 线放在"选项分节 ≥2 且对冲 ≥1,或对冲 ≥3":单一信号不判死(一句 "we could"
# 不代表题没定),两类信号叠加或对冲密集才判。
_SD_OPTION = re.compile(r"(?m)^#{1,3}\s*(?:option\s*)?\d+[\.\)]\s+\S")
_SD_QUESTION = re.compile(r"(?m)^.*\?\s*$")
_SD_HEDGE = re.compile(
    r"(?i)(remaining question|opening question|my preference|"
    r"which (?:option|approach|one)|we could|should we|"
    r"still (?:a|an) (?:open )?question|undecided|not sure|"
    r"thoughts\?|what do you think|i think the (?:second|third|first))")


def statement_determinacy_signals(text: str) -> dict:
    """题面体裁信号(纯函数,只数不判)。计数与判据分开,是为了让证据面能
    看见"查了、是 0",而不是只看见一个 ok。"""
    return {
        "option_sections": len(_SD_OPTION.findall(text)),
        "question_lines": len(_SD_QUESTION.findall(text)),
        "hedges": sorted({m.group(0).lower() for m in _SD_HEDGE.finditer(text)}),
    }


def judge_statement_determinacy(signals: dict | None) -> tuple[bool, list[str]]:
    """H6 判决(纯函数)。signals=None 意为**没查**,判死 —— "没查"与"查了
    干净"不许长成一个样(不造零,M69c 同律)。"""
    if signals is None:
        return False, ["题面未做欠定探测(H6 未查)—— 没查不等于干净,"
                       "准入必须给 --statement"]
    opts = signals["option_sections"]
    hedges = signals["hedges"]
    if (opts >= 2 and len(hedges) >= 1) or len(hedges) >= 3:
        return False, [
            f"题面疑似**欠定**(H6):选项分节 {opts} 处、对冲措辞 "
            f"{sorted(hedges)} —— 讨论式 PR 正文不宜作 delta 任务题面,"
            "答案会要求题面里根本没出现的设计收敛(反例 click-3407)"]
    return True, []


def _sets(run: dict) -> tuple:
    return (frozenset(run["passed_nodes"]), frozenset(run["failed_nodes"]),
            frozenset(run.get("skipped_nodes", ())))


def judge_hygiene(*, runs: list[dict], canonical_seconds: float,
                  delta_baseline: dict | None, delta_nodes: frozenset[str] | None,
                  post_run: dict | None) -> tuple[bool, list[str]]:
    """卫生判决(纯函数;判据 H1–H5 冻结在 tests/test_oracle_hygiene.py)。"""
    problems: list[str] = []
    if len(runs) < 2:
        problems.append("跑数 < 2 —— 稳定性判不了,不猜(H5)")
    else:
        ref = _sets(runs[0])
        for i, r in enumerate(runs[1:], 2):
            if _sets(r) != ref:
                problems.append(
                    f"第 {i} 跑与第 1 跑集合不相等(S-a)—— 比集合不比条数,"
                    "同样 25 条但判官换了人也算病")
                break
    if canonical_seconds > MAX_CANONICAL_SECONDS:
        problems.append(
            f"钦定跑法单发 {canonical_seconds:.2f}s,越过 {MAX_CANONICAL_SECONDS}s "
            "线(prereg-v2 §1.2;单发不重试)")
    if delta_nodes is not None:
        if delta_baseline is None:
            problems.append("没有 parent+delta 运行 —— FAIL_TO_PASS 没验")
        else:
            problems += measurement_problems(baseline=delta_baseline,
                                             delta_nodes=delta_nodes)
        if post_run is None:
            problems.append("没有 post 树运行 —— FAIL_TO_PASS 只验了一半")
        else:
            still_red = sorted(set(delta_nodes) - set(post_run["passed_nodes"]))
            if still_red:
                problems.append(
                    f"post 树上 delta 仍不绿:{still_red} —— 答案过不了自己的"
                    "测试,这个 delta 不是实现驱动的")
            if post_run["failed_nodes"]:
                problems.append(
                    f"post 树上有红 {len(post_run['failed_nodes'])} 条(如 "
                    f"{post_run['failed_nodes'][:3]})—— 答案把旧套件打了")
    return (not problems), problems


# ------------------------------------------------------------------ 执行
def _run(argv, *, cwd, env, timeout=1800):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


def _pytest_score(venv: Path, tree: Path, env: dict) -> dict:
    xml = tree / "_rp_hygiene_junit.xml"
    xml.unlink(missing_ok=True)
    _run([str(venv / "bin" / "python"), "-m", "pytest", "-q",
          "-p", "no:cacheprovider", "--junitxml", str(xml)],
         cwd=tree, env=venv_env(venv, env))
    data = xml.read_bytes() if xml.exists() else b""
    xml.unlink(missing_ok=True)
    return score_from_junit(data)


def _mkvenv(td: Path, name: str, tree: Path, wheelhouse: str, extras: str,
            extra_packages: list[str], env: dict) -> Path | None:
    venv = td / name
    _run([sys.executable, "-m", "venv", str(venv)], cwd=td, env=env)
    target = f"{tree}[{extras}]" if extras else str(tree)
    r = _run([str(venv / "bin" / "pip"), "install", "-q", "--no-index",
              "--find-links", wheelhouse, "-e", target, "pytest",
              *extra_packages], cwd=td, env=env)
    if r.returncode != 0:
        print("离线建环境失败:\n" + (r.stdout + r.stderr)[-500:], file=sys.stderr)
        return None
    return venv


def _added_test_names(tests_patch: Path) -> set[str]:
    names = set()
    for line in tests_patch.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\+\s*(?:async\s+)?def\s+(test_\w+)", line)
        if m:
            names.add(m.group(1))
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--parent-tree", required=True)
    ap.add_argument("--wheelhouse", required=True)
    ap.add_argument("--extras", default="")
    ap.add_argument("--extra-packages", default="",
                    help="测试面额外依赖(逗号分隔,如 sqlglot 的 duckdb,pandas,…)")
    ap.add_argument("--delta-post-dir", required=True)
    ap.add_argument("--answer-patch", required=True)
    ap.add_argument("--tests-patch", required=True)
    ap.add_argument("--canonical-seconds", type=float, required=True,
                    help="钦定跑法单发实测值(首轮已测按协议沿用)")
    ap.add_argument("--statement", required=True,
                    help="候选题面文件(封存池 candidates/<cid>/statement.md)——"
                         "H6 欠定探测的输入;必给,缺席即判死(没查≠干净)")
    ap.add_argument("--pretend-version", default="",
                    help="SETUPTOOLS_SCM_PRETEND_VERSION(无 .git 树的 scm 仓需要)")
    a = ap.parse_args()

    parent = Path(a.parent_tree).expanduser()
    extra_pkgs = [p for p in a.extra_packages.split(",") if p.strip()]
    env = offline_env(dict(__import__("os").environ))
    if a.pretend_version:
        env["SETUPTOOLS_SCM_PRETEND_VERSION"] = a.pretend_version

    with tempfile.TemporaryDirectory(prefix="rp_hygiene_") as td_:
        td = Path(td_)
        tree1 = td / "parent"
        shutil.copytree(parent, tree1,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        wh = str(Path(a.wheelhouse).expanduser())
        venv1 = _mkvenv(td, "venv1", tree1, wh, a.extras, extra_pkgs, env)
        if venv1 is None:
            return 2

        # 七跑:基准 ×3 + 四环境各 1(S-a 的证据面)
        battery_envs = [dict(env), dict(env), dict(env),
                        dict(env, COLUMNS="200"), dict(env, TZ="UTC"),
                        dict(env, LANG="C"), dict(env, TMPDIR=str(td / "tmp"))]
        (td / "tmp").mkdir(exist_ok=True)
        runs = []
        for i, e in enumerate(battery_envs, 1):
            s = _pytest_score(venv1, tree1, e)
            runs.append(s)
            print(f"  跑 {i}/7:passed={s['passed']} failed={len(s['failed_nodes'])} "
                  f"skip={s['skipped']}")

        # parent + delta 测试 → FAIL_TO_PASS 的 parent 侧
        for f in sorted(Path(a.delta_post_dir).expanduser().rglob("*")):
            if f.is_file():
                rel = f.relative_to(Path(a.delta_post_dir).expanduser())
                dest = tree1 / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, dest)
        delta_baseline = _pytest_score(venv1, tree1, env)
        base_red = set(runs[0]["failed_nodes"])
        delta_nodes = frozenset(set(delta_baseline["failed_nodes"]) - base_red)
        # 交叉核对:delta 红集合的函数名必须都是 tests.patch 里 + 出来的
        added = _added_test_names(Path(a.tests_patch).expanduser())
        stray = sorted(n for n in delta_nodes
                       if re.sub(r"\[.*\]$", "", n.split("::")[-1]) not in added)

        # post 树(parent + 答案 patch,独立副本独立 venv)
        tree2 = td / "post"
        shutil.copytree(parent, tree2,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        r = _run(["git", "apply", str(Path(a.answer_patch).expanduser())],
                 cwd=tree2, env=env)
        post_run = None
        apply_err = ""
        if r.returncode != 0:
            apply_err = r.stderr[-300:]
        else:
            venv2 = _mkvenv(td, "venv2", tree2, wh, a.extras, extra_pkgs, env)
            if venv2 is not None:
                post_run = _pytest_score(venv2, tree2, env)

    ok, problems = judge_hygiene(runs=runs, canonical_seconds=a.canonical_seconds,
                                 delta_baseline=delta_baseline,
                                 delta_nodes=delta_nodes, post_run=post_run)
    # H6(P1-b/c,2026-08-21):题面欠定探测。判定仍是纯函数,main 只搬数字。
    stmt_path = Path(a.statement).expanduser()
    sd_signals = (statement_determinacy_signals(
        stmt_path.read_text(encoding="utf-8", errors="replace"))
        if stmt_path.is_file() else None)
    sd_ok, sd_problems = judge_statement_determinacy(sd_signals)
    if not sd_ok:
        ok = False
        problems += sd_problems
    if stray:
        ok = False
        problems.append(f"delta 红集合含非 PR 新增的测试名:{stray[:5]} —— "
                        "红的不只是新测试,delta 集不干净")
    if apply_err:
        ok = False
        problems.append(f"答案 patch 应用失败:{apply_err}")

    record = {
        "_what": "oracle 卫生电池判决(v2 判据,prereg-v2 §1/§3;判定钉死 H1–H6)",
        "candidate": a.candidate,
        # 信号计数与判决分开落账:0/0/[] 是"查了、干净",键缺席才是"没查"
        "statement_determinacy": sd_signals,
        "runs": [{"passed": r["passed"], "failed": len(r["failed_nodes"]),
                  "skipped": r["skipped"]} for r in runs],
        "skip_set_run1": runs[0].get("skipped_nodes", []),
        "canonical_seconds": a.canonical_seconds,
        "delta_nodes": sorted(delta_nodes),
        "delta_stray_names": stray,
        "post_run": (None if post_run is None else
                     {"passed": post_run["passed"],
                      "failed": post_run["failed_nodes"][:10],
                      "skipped": post_run["skipped"]}),
        "verdict": {"ok": ok, "problems": problems},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"{a.candidate}.json"
    dest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(("卫生判决:**通过**" if ok else "卫生判决:**判死**") + f" → {dest}")
    for p in problems:
        print("  -", p)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
