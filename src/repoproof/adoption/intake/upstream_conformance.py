"""上游一致性样例选取器(M2-e · TOOL_CONTRACT_SCHEMA §四第二层)。

从 pinned 上游自带测试套件里确定性选取与能力相关的子集 —— 它验的是
**上游与环境**("pinned 版本在本机行为正常"),不是 wrapper:
    执行落点 = HostContract host.health_checks(S0 baseline gate 跑,
    gating=True:上游不健康 → BLOCKED,零模型预算消耗 —— 供给/环境
    问题按口径不是任务缺陷,更不是模型的锅)。

选取规则(零 LLM,确定性):
    - 只看 tests//test/ 下的 test_*.py;
    - 文件名或文件内 `def test_*` 函数名命中任一关键词(词根小写包含);
    - 按(命中数降序, 文件名升序)排序,取前 max_files 个;
    - 没有 tests 目录/零命中 → 空选取(如实,不硬凑)。
"""

from __future__ import annotations

import re
from pathlib import Path

_TEST_DIRS = ("tests", "test")


def select_upstream_tests(
    repo_dir: Path,
    keywords: list[str],
    *,
    max_files: int = 3,
) -> list[str]:
    """→ 相对 repo_dir 的测试文件路径列表(确定性排序)。"""
    repo_dir = Path(repo_dir)
    kws = [k.strip().lower() for k in keywords if k.strip()]
    if not kws:
        return []
    scored: list[tuple[int, str]] = []
    for d in _TEST_DIRS:
        base = repo_dir / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("test_*.py")):
            rel = str(p.relative_to(repo_dir))
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            names = " ".join(re.findall(r"^def (test_\w+)", text, re.MULTILINE))
            haystack = (p.name + " " + names).lower()
            hits = sum(haystack.count(k) for k in kws)
            if hits:
                scored.append((hits, rel))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [rel for _, rel in scored[:max_files]]


def precheck_upstream_conformance(
    upstream_dir: Path,
    selected: list[str],
    python: Path,
) -> dict:
    """物化期预检(M2-e 实施定稿):在 harness 侧(已装 pinned 上游的解释
    器)跑选中子集 —— 供给/环境问题在物化期就暴露,不进 run。

    为什么不做成 S0 health check(实测倒逼):上游库是 **agent 的 lock
    责任**,S0 态骨架 venv 里没有它,收集必崩;若让 harness 预装上游,
    replay"从 agent 自锁 lock 重建"的执法点被打穿(lock 缺上游也能绿)。
    → 选中子集不健康 = 抛(物化拒绝);绿 = 返回记录(任务包留痕)。"""
    import subprocess

    if not selected:
        return {"selected": [], "status": "EMPTY"}
    argv = [str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
            *[str(Path(upstream_dir) / rel) for rel in selected]]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(
            f"上游一致性预检失败(exit {r.returncode})—— 供给/环境问题,"
            f"物化期拒绝:{(r.stdout or r.stderr)[-400:]}")
    return {"selected": selected, "status": "PASS",
            "tail": r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""}
