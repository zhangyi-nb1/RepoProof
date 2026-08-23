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


def conformance_health_check(selected: list[str]) -> dict | None:
    """→ HostHealthCheck 形状的 dict(bridge 合成用);空选取 → None。

    经会话 venv 跑 ../upstream 下选中子集;pytest 进程 cwd=host,上游
    只读挂载,cache 禁写。收集期崩(插件缺/filterwarnings 撞新 pytest)
    也是"上游在本环境不健康"的如实读数 —— gating BLOCKED,不烧预算。"""
    if not selected:
        return None
    return {
        "command": [".venv/bin/python", "-m", "pytest", "-q",
                    "-p", "no:cacheprovider",
                    *[f"../upstream/{rel}" for rel in selected]],
        "pass_if_stdout_contains": "passed",
        "gating": True,
    }
