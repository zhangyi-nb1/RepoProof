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

import ast
import os
import re
import subprocess
from pathlib import Path

_TEST_DIRS = ("tests", "test")
_MISSING_MODULE_RE = re.compile(
    r"ModuleNotFoundError:\s+No module named ['\"]([^'\"]+)['\"]"
)
_PIN_RE = re.compile(
    r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*==\s*([^\s;]+)\s*(?:;.*)?$"
)


class UpstreamConformanceError(RuntimeError):
    """A deterministic upstream-test precheck failure.

    ``missing_module`` is public environment information.  It is safe to show
    in Product UI and must never be converted into an Agent repair prompt.
    """

    def __init__(self, message: str, *, missing_module: str | None = None) -> None:
        super().__init__(message)
        self.missing_module = missing_module


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


def select_upstream_test_nodes(
    repo_dir: Path,
    keywords: list[str],
    *,
    max_nodes: int = 3,
) -> list[str]:
    """Select a small deterministic set of module-level pytest nodes.

    Selecting whole files made Product onboarding accidentally execute
    hundreds or thousands of unrelated upstream tests.  Besides being slow,
    collection then depended on the upstream project's complete CI stack.
    Node-level selection keeps this evidence lane capability-shaped while the
    reference/public/held-out lanes continue to judge the wrapper itself.
    """

    repo_dir = Path(repo_dir)
    kws = [re.sub(r"[^a-z0-9]+", "", k.lower()) for k in keywords]
    kws = [k for k in kws if len(k) >= 3]
    if not kws:
        return []
    scored: list[tuple[int, str]] = []
    for dirname in _TEST_DIRS:
        base = repo_dir / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            rel = str(path.relative_to(repo_dir))
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            functions = [
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_")
            ]
            for node in functions:
                decorators = " ".join(
                    ast.dump(decorator, include_attributes=False).lower()
                    for decorator in node.decorator_list
                )
                if any(
                    marker in decorators
                    for marker in ("enable_socket", "network", "samples", "slow")
                ):
                    continue
                name = node.name
                haystack = re.sub(r"[^a-z0-9]+", "", name.lower())
                hits = sum(1 for keyword in kws if keyword in haystack)
                if hits:
                    scored.append((hits, f"{rel}::{name}"))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [node for _, node in scored[:max_nodes]]


def _normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _pinned_requirement_for_module(
    upstream_dir: Path,
    module: str,
) -> str | None:
    """Find one exact upstream-owned test pin for a missing import.

    Only plain ``name==version`` lines from test/CI/dev requirement files are
    eligible.  URLs, editable installs, constraints and unpinned names are
    deliberately ignored; a pinned source repository must not be able to turn
    this bounded environment repair into arbitrary installer input.
    """

    wanted = _normalise_name(module.split(".", 1)[0])
    if not wanted:
        return None
    found: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(Path(upstream_dir).rglob("*.txt")):
        rel = str(path.relative_to(upstream_dir)).lower()
        if not any(token in rel for token in ("test", "ci", "dev")):
            continue
        try:
            if path.stat().st_size > 512_000:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            match = _PIN_RE.fullmatch(line)
            if match is None:
                continue
            distribution = match.group(1)
            normalised = _normalise_name(distribution)
            if normalised.startswith(("types", "stubs")):
                continue
            if wanted not in normalised and normalised not in wanted:
                continue
            pin = f"{distribution}=={match.group(2)}"
            filename = path.name.lower()
            priority = (
                0
                if filename in {"dev.txt", "test.txt", "tests.txt"}
                else 1
                if re.search(r"(?:ci|test)[-_]\d", filename)
                else 2
            )
            found.setdefault(normalised, []).append((priority, pin))
    if len(found) != 1:
        return None
    candidates = next(iter(found.values()))
    best_priority = min(priority for priority, _pin in candidates)
    pins = {pin for priority, pin in candidates if priority == best_priority}
    return next(iter(pins)) if len(pins) == 1 else None


def precheck_upstream_conformance(
    upstream_dir: Path,
    selected: list[str],
    python: Path,
    *,
    bootstrap_missing: bool = False,
    max_dependency_repairs: int = 3,
) -> dict:
    """物化期预检(M2-e 实施定稿):在 harness 侧(已装 pinned 上游的解释
    器)跑选中子集 —— 供给/环境问题在物化期就暴露,不进 run。

    为什么不做成 S0 health check(实测倒逼):上游库是 **agent 的 lock
    责任**,S0 态骨架 venv 里没有它,收集必崩;若让 harness 预装上游,
    replay"从 agent 自锁 lock 重建"的执法点被打穿(lock 缺上游也能绿)。
    → 选中子集不健康 = 抛(物化拒绝);绿 = 返回记录(任务包留痕)。"""
    if not selected:
        return {"selected": [], "status": "EMPTY"}
    nodes = []
    for item in selected:
        path, separator, node = item.partition("::")
        target = str(Path(upstream_dir) / path)
        nodes.append(f"{target}::{node}" if separator else target)
    argv = [
        str(python), "-m", "pytest", "-q", "-c", os.devnull,
        "-p", "no:cacheprovider", *nodes,
    ]
    bootstrapped: list[str] = []
    for _attempt in range(max_dependency_repairs + 1):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        if result.returncode == 0:
            record = {
                "selected": selected,
                "status": "PASS",
                "tail": (
                    result.stdout.strip().splitlines()[-1]
                    if result.stdout.strip()
                    else ""
                ),
            }
            if bootstrapped:
                record["dependency_bootstrap"] = bootstrapped
            return record
        output = f"{result.stdout}\n{result.stderr}".strip()
        missing_match = _MISSING_MODULE_RE.search(output)
        missing = missing_match.group(1) if missing_match else None
        pin = (
            _pinned_requirement_for_module(Path(upstream_dir), missing)
            if bootstrap_missing and missing
            else None
        )
        if pin and pin not in bootstrapped and len(bootstrapped) < max_dependency_repairs:
            installed = subprocess.run(
                [
                    str(python), "-m", "pip", "install",
                    "--disable-pip-version-check", "-q", pin,
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if installed.returncode == 0:
                bootstrapped.append(pin)
                continue
        suffix = output[-1200:]
        raise UpstreamConformanceError(
            f"上游一致性预检失败(exit {result.returncode})—— 供给/环境问题,"
            f"物化期拒绝:{suffix}",
            missing_module=missing,
        )
    raise AssertionError("bounded conformance loop exhausted without a decision")
