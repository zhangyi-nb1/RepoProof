"""变异闸门:把**已付过学费的缺陷**逐个注回源码,钉死套件必须 100% 抓住。

这是"评测者的评测者"(PROCESS-INDEPENDENCE-PLAN §5-P1-5)。回答的问题:
我的钉死到底护住了什么?——不是"测试全绿"(照着实现写的测试永远全绿),
而是"把 LESSONS 里每一条历史缺陷(及其近似变体)重新犯一遍,套件会不会红"。
变体的意义:抓得住原案却抓不住变体 = 钉死过拟合到了事发实例,护不住缺陷类。

三种结局:
    CAUGHT   注入后指定测试子集变红(期望值)
    ESCAPED  注入后子集仍绿 —— 套件没在护这条教训,当场补钉死
    STALE    旧串在源里找不到/不唯一 —— 源码重构后登记簿未更新,必须维护

自证机制(先于一切变异运行):金丝雀变异(掏空 PASS_VERDICTS)若未被抓住,
说明 worktree 隔离失效(测的是主树不是变异体),整个闸门自宣无效退出——
检查器必须先证明自己在检查,才有资格给别人发绿。

隔离:临时 git worktree(HEAD)+ `PYTHONPATH=<树>/src` 压过 editable 安装;
每个变异注入→跑子集→`git checkout --` 还原。主工作树全程零触碰。

用法:
    .venv/bin/python scripts/mutation_gate.py          # 全量,证据落盘
    .venv/bin/python scripts/mutation_gate.py --list   # 只列登记簿
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTEST = REPO / ".venv" / "bin" / "pytest"
EVIDENCE_DIR = REPO / "docs" / "evidence" / "mutation_gate"

# ---------------------------------------------------------------- 登记簿
# 每条 = 一次真实事故(lesson)或其近似变体(variant of)。old 必须与 HEAD
# 源码逐字节一致且唯一(STALE 判据);catchers 是必须变红的测试子集。

_BR = "src/repoproof/persistence/bench_records.py"
_HG = "src/repoproof/harness/host_guard.py"
_HD = "src/repoproof/runner/host_guided.py"
_T_BR = ["tests/test_bench_records.py"]
_T_HG = ["tests/test_host_guard.py"]
_T_HD = ["tests/test_host_guided.py"]

CANARY = {
    "id": "C0-plumbing-canary",
    "lesson": "自证:worktree 隔离必须真的生效",
    "file": _BR,
    "old": 'PASS_VERDICTS = frozenset({"PASS", "PASS_ADAPTED"})',
    "new": "PASS_VERDICTS = frozenset()",
    "catchers": _T_BR,
}

MUTATIONS: list[dict] = [
    # ---- LESSONS #30:冒烟发混进闸门通过数 ----
    {
        "id": "M30a-smoke-not-excluded",
        "lesson": "#30 fake 冒烟发被当成模型 PASS(在闸门里躺了 3 天)",
        "file": _BR,
        "old": ('    smoke = [r for r in rows\n'
                '             if str(r.get("model", "")).startswith(SMOKE_MODEL_PREFIX)]\n'
                '    real = [r for r in rows\n'
                '            if not str(r.get("model", "")).startswith(SMOKE_MODEL_PREFIX)]'),
        "new": "    smoke = []\n    real = list(rows)",
        "catchers": _T_BR,
    },
    {
        "id": "M30b-smoke-prefix-case-variant",
        "lesson": "#30 变体:前缀大小写错配,fake-scripted 漏网",
        "file": _BR,
        "old": 'SMOKE_MODEL_PREFIX = "fake"',
        "new": 'SMOKE_MODEL_PREFIX = "FAKE"',
        "catchers": _T_BR,
    },
    # ---- LESSONS #27:探索性加发未与预注册批次隔离 ----
    {
        "id": "M27-exploratory-counts",
        "lesson": "#27 探索性加发充闸门(真话写在机器读不到的地方)",
        "file": _BR,
        "old": '    gateable = [r for r in real if r.get("batch") != EXPLORATORY_BATCH]',
        "new": "    gateable = list(real)",
        "catchers": _T_BR,
    },
    # ---- LESSONS #26:裁定不进统计,台账自失真 ----
    {
        "id": "M26-verdict-not-effective",
        "lesson": "#26 闸门数原始 verdict 而非 effective_verdict(order-38 假 PASS 复活)",
        "file": _BR,
        "old": '    passes = [r for r in gateable if r["effective_verdict"] in PASS_VERDICTS]',
        "new": '    passes = [r for r in gateable if r.get("verdict") in PASS_VERDICTS]',
        "catchers": _T_BR,
    },
    {
        "id": "M26b-substring-pass-variant",
        "lesson": '#26 变体:"PASS" in verdict 子串判定(FALSE_PASS 含 PASS)',
        "file": _BR,
        "old": '    passes = [r for r in gateable if r["effective_verdict"] in PASS_VERDICTS]',
        "new": '    passes = [r for r in gateable if "PASS" in str(r["effective_verdict"])]',
        "catchers": _T_BR,
    },
    # ---- LESSONS #29:bench 根白名单方向反了 ----
    {
        "id": "M29a-prefix-free-pass",
        "lesson": "#29 前缀白名单放行了装着 PASS 解的 T4 栈",
        "file": _HG,
        "old": '        if name == ".DS_Store" or name in _BENCH_ALLOWED_NAMES:',
        "new": ('        if name == ".DS_Store" or name.startswith("offerclaw-") '
                'or name in _BENCH_ALLOWED_NAMES:'),
        "catchers": _T_HG,
    },
    {
        "id": "M29b-upstream-whitelisted",
        "lesson": "#29 变体:给无害兄弟目录 upstream 开口子(该迁走的是整套栈)",
        "file": _HG,
        "old": '    "offerclaw-t3-browser-use",      # T3 宿主副本\n})',
        "new": '    "offerclaw-t3-browser-use",      # T3 宿主副本\n    "upstream",\n})',
        "catchers": _T_HG,
    },
    {
        "id": "M29c-answer-key-registered",
        "lesson": "#29 变体:把答案卷目录本身登记进白名单",
        "file": _HG,
        "old": '    "offerclaw-t3-browser-use",      # T3 宿主副本\n})',
        "new": ('    "offerclaw-t3-browser-use",      # T3 宿主副本\n'
                '    "offerclaw-transaction-stack",\n})'),
        "catchers": _T_HG,
    },
    # ---- 主目录硬护栏(红线,无单独 lesson 号) ----
    {
        "id": "MGuard-case-sensitive",
        "lesson": "护栏红线变体:路径比较丢大小写归一(APFS 大小写不敏感可绕)",
        "file": _HG,
        "old": '    return os.path.realpath(os.path.expanduser(str(p))).lower().rstrip("/")',
        "new": '    return os.path.realpath(os.path.expanduser(str(p))).rstrip("/")',
        "catchers": _T_HG,
    },
    # ---- LESSONS #31:harness 替模型认领错 ----
    {
        "id": "M31a-attribution-neutered",
        "lesson": "#31 归因分支被掏空(一切依赖失败重新都算 harness)",
        "file": _HD,
        "old": "            added = added_unresolvable_dists(full, self._baseline_dists())",
        "new": "            added = []",
        "catchers": _T_HD,
    },
    {
        "id": "M31b-attribution-flipped",
        "lesson": "#31 变体:归因标签写反(agent 缺陷标成 harness)",
        "file": _HD,
        "old": '                               "attribution": "agent",',
        "new": '                               "attribution": "harness",',
        "catchers": _T_HD,
    },
    {
        "id": "M31c-failure-types-union-dropped",
        "lesson": "#31 验证器归因进不了台账 failure_types(只活在 report.json)",
        "file": _HD,
        "old": ('            | {vr.extra["failure_type"]\n'
                '               for vr in (capability_vr, regression_vr, policy_vr, replay_vr)\n'
                '               if vr is not None and vr.extra.get("failure_type")})'),
        "new": "            )",
        "catchers": _T_HD,
    },
    {
        "id": "M31d-pep503-dropped",
        "lesson": "#31 变体:丢 PEP 503 归一(Browser_Use ≠ browser-use,基线比对失效)",
        "file": _HD,
        "old": '    return re.sub(r"[-_.]+", "-", name).lower()',
        "new": "    return name.lower()",
        "catchers": _T_HD,
    },
]


# ---------------------------------------------------------------- 执行机构

def _git(*args: str, cwd: Path = REPO) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _run_subset(tree: Path, catchers: list[str]) -> tuple[int, str]:
    env = dict(os.environ, PYTHONPATH=str(tree / "src"))
    proc = subprocess.run(
        [str(PYTEST), *catchers, "-q", "-x", "-p", "no:cacheprovider"],
        cwd=tree, env=env, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr)[-800:]


def _apply(tree: Path, m: dict) -> str | None:
    """注入变异;返回 None=成功,否则 STALE 原因。"""
    f = tree / m["file"]
    if not f.exists():
        return f"目标文件不存在:{m['file']}"
    text = f.read_text(encoding="utf-8")
    n = text.count(m["old"])
    if n != 1:
        return f"旧串出现 {n} 次(要求恰 1)—— 源码已重构,登记簿过期"
    f.write_text(text.replace(m["old"], m["new"]), encoding="utf-8")
    return None


def _restore(tree: Path, m: dict) -> None:
    _git("checkout", "--", m["file"], cwd=tree)


def run_gate() -> int:
    head = _git("rev-parse", "HEAD")
    results: list[dict] = []
    t_start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="rp_mutation_") as td:
        tree = Path(td) / "tree"
        _git("worktree", "add", "--detach", str(tree), "HEAD")
        try:
            # 基线:未变异的 worktree 上所有 catcher 必须全绿,否则无从归因
            all_catchers = sorted({c for m in [CANARY, *MUTATIONS] for c in m["catchers"]})
            code, tail = _run_subset(tree, all_catchers)
            if code != 0:
                print(f"[ABORT] 基线不绿(exit={code}),无从归因变异:\n{tail}")
                return 2
            # 金丝雀:证明测的是变异体不是主树
            err = _apply(tree, CANARY)
            if err:
                print(f"[ABORT] 金丝雀 STALE:{err}")
                return 2
            code, tail = _run_subset(tree, CANARY["catchers"])
            _restore(tree, CANARY)
            if code == 0:
                print("[ABORT] 金丝雀未被抓住 —— worktree 隔离失效,"
                      "本闸门在测主树而非变异体,一切结论无效。")
                return 2
            print(f"金丝雀 CAUGHT(exit={code})—— 隔离通路自证有效。\n")

            for m in MUTATIONS:
                t0 = time.monotonic()
                err = _apply(tree, m)
                if err:
                    results.append({"id": m["id"], "lesson": m["lesson"],
                                    "outcome": "STALE", "detail": err})
                    print(f"  STALE   {m['id']} —— {err}")
                    continue
                code, tail = _run_subset(tree, m["catchers"])
                _restore(tree, m)
                outcome = "CAUGHT" if code != 0 else "ESCAPED"
                results.append({
                    "id": m["id"], "lesson": m["lesson"], "file": m["file"],
                    "outcome": outcome, "pytest_exit": code,
                    "catchers": m["catchers"],
                    "seconds": round(time.monotonic() - t0, 1),
                    **({"tail": tail} if outcome == "ESCAPED" else {}),
                })
                print(f"  {outcome:7s} {m['id']}  ({results[-1]['seconds']}s)")
        finally:
            _git("worktree", "remove", "--force", str(tree))
            _git("worktree", "prune")

    caught = sum(1 for r in results if r["outcome"] == "CAUGHT")
    bad = [r for r in results if r["outcome"] != "CAUGHT"]
    report = {
        "head_commit": head,
        "mutations": len(MUTATIONS),
        "caught": caught,
        "escaped": [r["id"] for r in results if r["outcome"] == "ESCAPED"],
        "stale": [r["id"] for r in results if r["outcome"] == "STALE"],
        "capture_rate": f"{caught}/{len(MUTATIONS)}",
        "wall_seconds": round(time.monotonic() - t_start, 1),
        "results": results,
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    dest = EVIDENCE_DIR / f"{head[:12]}.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"\n捕获率 {report['capture_rate']};证据已落盘:{dest}")
    if bad:
        print("未达 100% —— ESCAPED 当场补钉死,STALE 更新登记簿。绝不带病放行。")
        return 1
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        for m in MUTATIONS:
            print(f"{m['id']:36s} {m['lesson']}")
        sys.exit(0)
    sys.exit(run_gate())
