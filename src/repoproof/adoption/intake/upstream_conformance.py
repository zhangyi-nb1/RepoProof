"""上游一致性样例选取器(M2-e · TOOL_CONTRACT_SCHEMA §四第二层)。

从 pinned 上游自带测试套件里确定性选取与能力相关的子集 —— 它验的是
**上游与环境**("pinned 版本在本机行为正常"),不是 wrapper:
    执行落点 = HostContract host.health_checks(S0 baseline gate 跑,
    gating=True:上游不健康 → BLOCKED,零模型预算消耗 —— 供给/环境
    问题按口径不是任务缺陷,更不是模型的锅)。

选取规则(零 LLM,确定性):
    - 从已审阅 reference implementation 的 Python AST 提取实际调用的
      pinned-upstream 相对限定调用路径;用户措辞和格式标签不参与选择;
    - 只看 tests//test/ 下 test_*.py 的 pytest 节点 AST;
    - 只做调用路径各段的精确 AST 匹配,不维护仓库、格式或领域别名表;
    - 按(命中数降序,node id 升序)排序,取前 max_nodes 个;
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
_MODULE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*\Z")
_EXCLUDED_TEST_MARKS = frozenset({"enable_socket", "network", "samples", "slow"})


class UpstreamConformanceError(RuntimeError):
    """A deterministic upstream-test precheck failure.

    ``missing_module`` is public environment information.  It is safe to show
    in Product UI and must never be converted into an Agent repair prompt.
    """

    def __init__(self, message: str, *, missing_module: str | None = None) -> None:
        super().__init__(message)
        self.missing_module = missing_module


def _expression_parts(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = _expression_parts(node.value)
        if parent is not None:
            return (*parent, node.attr)
    return None


def reference_upstream_symbols(
    reference_source: str,
    *,
    import_module: str,
) -> list[str]:
    """Extract exact upstream call identifiers from one reviewed reference.

    This is a structural selection hint, not semantic truth.  Binding it to
    the reference implementation makes natural-language rewrites a no-op.
    """

    module = import_module.strip()
    if _MODULE_RE.fullmatch(module) is None:
        raise UpstreamConformanceError("reference import_module 非法")
    try:
        tree = ast.parse(reference_source)
    except SyntaxError as exc:
        raise UpstreamConformanceError(
            "reference implementation 不是合法 Python"
        ) from exc

    aliases: dict[str, tuple[str, ...]] = {}
    module_parts = tuple(module.split("."))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = tuple(alias.name.split("."))
                if imported[: len(module_parts)] != module_parts:
                    continue
                local = alias.asname or imported[0]
                aliases[local] = imported if alias.asname else (imported[0],)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_module = tuple(node.module.split("."))
            if imported_module[: len(module_parts)] != module_parts:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = (
                    *imported_module,
                    alias.name,
                )

    symbols: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _expression_parts(node.func)
        if called is None or called[0] not in aliases:
            continue
        resolved = (*aliases[called[0]], *called[1:])
        if resolved[: len(module_parts)] != module_parts:
            continue
        # Preserve the path relative to the declared import root. A terminal
        # name such as ``parse`` is far too ambiguous in a large scientific
        # namespace; ``SeqIO.parse`` remains structural public-call evidence
        # without relying on repository names or user vocabulary.
        if len(resolved) <= len(module_parts):
            continue
        relative = resolved[len(module_parts):]
        identifier = ".".join(relative)
        if (
            all(part.isidentifier() and not part.startswith("_") for part in relative)
            and identifier not in symbols
        ):
            symbols.append(identifier)
    return symbols


def _normalise_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _decorator_identifiers(node: ast.AST) -> set[str]:
    values: set[str] = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Name):
            values.add(item.id.lower())
        elif isinstance(item, ast.Attribute):
            values.add(item.attr.lower())
    return values


def _test_nodes(
    tree: ast.Module,
) -> list[
    tuple[
        str,
        ast.FunctionDef | ast.AsyncFunctionDef,
        tuple[ast.AST, ...],
    ]
]:
    nodes: list[
        tuple[
            str,
            ast.FunctionDef | ast.AsyncFunctionDef,
            tuple[ast.AST, ...],
        ]
    ] = []
    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name.startswith("test_"):
                nodes.append((item.name, item, ()))
        elif isinstance(item, ast.ClassDef):
            for method in item.body:
                if (
                    isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and method.name.startswith("test_")
                ):
                    nodes.append((
                        f"{item.name}::{method.name}",
                        method,
                        tuple(item.decorator_list),
                    ))
    return nodes


def select_upstream_test_nodes(
    repo_dir: Path,
    symbols: list[str],
    *,
    max_nodes: int = 3,
) -> list[str]:
    """Select a small deterministic set of structurally related pytest nodes.

    Selecting whole files made Product onboarding accidentally execute
    hundreds or thousands of unrelated upstream tests.  Besides being slow,
    collection then depended on the upstream project's complete CI stack.
    Node-level selection keeps this evidence lane capability-shaped while the
    reference/public/held-out lanes continue to judge the wrapper itself.
    """

    repo_dir = Path(repo_dir)
    wanted_paths: list[tuple[str, ...]] = []
    for symbol in symbols:
        parts = tuple(str(symbol).split("."))
        if not parts or any(
            not part.isidentifier() or part.startswith("_")
            for part in parts
        ):
            continue
        normalised = tuple(_normalise_identifier(part) for part in parts)
        if all(normalised) and normalised not in wanted_paths:
            wanted_paths.append(normalised)
    if not wanted_paths:
        return []
    scored: list[tuple[int, str]] = []
    try:
        bases = sorted(
            (
                child
                for child in repo_dir.iterdir()
                if child.is_dir() and child.name.casefold() in _TEST_DIRS
            ),
            key=lambda child: child.name,
        )
    except OSError:
        return []
    for base in bases:
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
            for node_id, node, class_decorators in _test_nodes(tree):
                decorators = (*class_decorators, *node.decorator_list)
                marks = (
                    set().union(*(
                        _decorator_identifiers(decorator)
                        for decorator in decorators
                    ))
                    if decorators
                    else set()
                )
                if marks & _EXCLUDED_TEST_MARKS:
                    continue
                observed = {
                    _normalise_identifier(item.id)
                    for item in ast.walk(node)
                    if isinstance(item, ast.Name)
                }
                observed.update(
                    _normalise_identifier(item.attr)
                    for item in ast.walk(node)
                    if isinstance(item, ast.Attribute)
                )
                observed.update(
                    _normalise_identifier(part)
                    for part in node.name.removeprefix("test_").split("_")
                )
                # File/class names are valid structural evidence too. This
                # lets a qualified call such as ``SeqIO.parse`` distinguish a
                # focused test module from unrelated ``parse`` users.
                observed.update(
                    _normalise_identifier(part)
                    for part in re.split(r"[^A-Za-z0-9]+", rel)
                    if part
                )
                observed.update(
                    _normalise_identifier(part)
                    for part in re.split(r"[^A-Za-z0-9]+", node_id)
                    if part
                )
                hits = sum(
                    len(path)
                    for path in wanted_paths
                    if set(path).issubset(observed)
                )
                if hits:
                    scored.append((hits, f"{rel}::{node_id}"))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [node for _, node in scored[:max_nodes]]


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
    if not selected:
        return {"selected": [], "status": "EMPTY"}
    nodes = []
    test_roots: set[str] = set()
    for item in selected:
        path, separator, node = item.partition("::")
        target = str(Path(upstream_dir) / path)
        nodes.append(f"{target}::{node}" if separator else target)
        relative_parts = Path(path).parts
        if relative_parts:
            test_roots.add(relative_parts[0])
    # The admitted test surface is rooted in ``tests``/``Tests``/``test``.
    # Execute from that real-cased root so legacy suites can resolve their own
    # fixture directories, while the installed wheel (not the checkout parent)
    # remains the imported upstream distribution.
    execution_root = Path(upstream_dir)
    if len(test_roots) == 1:
        candidate_root = Path(upstream_dir) / next(iter(test_roots))
        if candidate_root.is_dir() and not candidate_root.is_symlink():
            execution_root = candidate_root
    argv = [
        str(python), "-m", "pytest", "-q", "-c", os.devnull,
        "-p", "no:cacheprovider", *nodes,
    ]
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(execution_root),
    )
    if result.returncode == 0:
        return {
            "selected": selected,
            "status": "PASS",
            "tail": (
                result.stdout.strip().splitlines()[-1]
                if result.stdout.strip()
                else ""
            ),
        }
    output = f"{result.stdout}\n{result.stderr}".strip()
    missing_match = _MISSING_MODULE_RE.search(output)
    missing = missing_match.group(1) if missing_match else None
    suffix = output[-1200:]
    raise UpstreamConformanceError(
        f"上游一致性预检失败(exit {result.returncode})—— 供给/环境问题,"
        f"物化期拒绝:{suffix}",
        missing_module=missing,
    )
