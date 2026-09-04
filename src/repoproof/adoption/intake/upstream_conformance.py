"""上游一致性样例选取器(M2-e · TOOL_CONTRACT_SCHEMA §四第二层)。

从 pinned 上游自带测试套件里确定性选取与能力相关的子集 —— 它验的是
**上游与环境**("pinned 版本在本机行为正常"),不是 wrapper:
    执行落点 = HostContract host.health_checks(S0 baseline gate 跑,
    gating=True:上游不健康 → BLOCKED,零模型预算消耗 —— 供给/环境
    问题按口径不是任务缺陷,更不是模型的锅)。

选取规则(零 LLM,确定性):
    - 从已审阅 reference implementation 的 Python AST 提取实际调用的
      pinned-upstream 相对限定调用路径;用户措辞和格式标签不参与选择;
    - 只看 pytest 在该仓实际会收集的测试模块(上游声明的 testpaths/
      python_files,缺省 pytest 默认模式,全仓递归)的节点 AST;
    - 只做调用路径各段的精确 AST 匹配,不维护仓库、格式或领域别名表;
    - 按(命中数降序,node id 升序)排序,取前 max_nodes 个;
    - 没有可收集测试模块/零命中 → 空选取(如实,不硬凑)。
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
from pathlib import Path

# The admitted test surface is what pytest itself would collect for the
# upstream: its declared ``testpaths``/``python_files`` when present, otherwise
# pytest's default basename patterns over the whole tree.  Only the pytest
# default ``norecursedirs`` plus build/runtime debris are skipped.  Explicit
# node ids let ``-c os.devnull`` pytest execute any of these files, so nothing
# selected here is outside the base-pytest runner profile.
_PYTEST_DEFAULT_PYTHON_FILES = ("test_*.py", "*_test.py")
_NORECURSE_NAMES = frozenset(
    {"build", "dist", "CVS", "_darcs", "{arch}", "venv", ".venv", "node_modules",
     "__pycache__", "upstream-cache", "runs", "site-packages"}
)
_MAX_ADMITTED_TEST_FILES = 4000


def _pytest_config_options(repo_dir: Path) -> dict[str, list[str]]:
    """Read ``testpaths``/``python_files`` the way pytest resolves its rootdir ini."""

    import configparser
    import tomllib

    def _split(value: str) -> list[str]:
        return [item for item in value.replace("\n", " ").split() if item]

    for filename, section in (
        ("pytest.ini", "pytest"),
        ("pyproject.toml", "tool.pytest.ini_options"),
        ("tox.ini", "pytest"),
        ("setup.cfg", "tool:pytest"),
    ):
        path = repo_dir / filename
        if path.is_symlink() or not path.is_file():
            continue
        options: dict[str, list[str]] = {}
        try:
            if filename == "pyproject.toml":
                document = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
                table = ((document.get("tool") or {}).get("pytest") or {}).get("ini_options")
                if not isinstance(table, dict):
                    continue
                for key in ("testpaths", "python_files"):
                    raw = table.get(key)
                    if isinstance(raw, str):
                        options[key] = _split(raw)
                    elif isinstance(raw, list):
                        options[key] = [str(item) for item in raw if str(item).strip()]
            else:
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(path.read_text(encoding="utf-8", errors="replace"))
                if not parser.has_section(section):
                    continue
                for key in ("testpaths", "python_files"):
                    if parser.has_option(section, key):
                        options[key] = _split(parser.get(section, key))
        except (OSError, ValueError, configparser.Error):
            continue
        return options
    return {}


def _recursable(path: Path) -> bool:
    name = path.name
    return not (
        name.startswith(".") or name in _NORECURSE_NAMES or name.endswith(".egg")
    )


def _admitted_test_files(repo_dir: Path) -> list[Path]:
    """Deterministic list of upstream files pytest would collect as test modules."""

    from fnmatch import fnmatch

    options = _pytest_config_options(repo_dir)
    python_files = tuple(options.get("python_files") or _PYTEST_DEFAULT_PYTHON_FILES)

    def _matches_python_files(path: Path) -> bool:
        return path.suffix == ".py" and any(
            fnmatch(path.name, pattern) for pattern in python_files
        )

    def _walk(base: Path) -> list[Path]:
        found: list[Path] = []
        stack = [base]
        while stack and len(found) <= _MAX_ADMITTED_TEST_FILES:
            current = stack.pop()
            try:
                children = sorted(current.iterdir(), key=lambda item: item.name)
            except OSError:
                continue
            for child in children:
                if child.is_symlink():
                    continue
                if child.is_dir():
                    if _recursable(child):
                        stack.append(child)
                elif child.is_file() and _matches_python_files(child):
                    found.append(child)
        return found

    admitted: set[Path] = set()
    testpaths = options.get("testpaths") or []
    if testpaths:
        for entry in testpaths:
            pattern = entry.strip().strip("/")
            if not pattern or pattern.startswith("..") or Path(pattern).is_absolute():
                continue
            try:
                matches = sorted(repo_dir.glob(pattern))
            except (OSError, ValueError):
                continue
            for match in matches:
                if match.is_symlink():
                    continue
                if match.is_dir():
                    admitted.update(_walk(match))
                elif match.is_file() and match.suffix == ".py":
                    # An explicit file argument is collected regardless of
                    # python_files, exactly as on the pytest command line.
                    admitted.add(match)
    else:
        admitted.update(_walk(repo_dir))
    return sorted(admitted)[:_MAX_ADMITTED_TEST_FILES]


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
        ast.FunctionDef,
        tuple[ast.AST, ...],
    ]
]:
    nodes: list[
        tuple[
            str,
            ast.FunctionDef,
            tuple[ast.AST, ...],
        ]
    ] = []
    for item in tree.body:
        # The conformance v1 runner deliberately carries only pytest's base
        # toolchain.  Selecting an async node would make the result depend on
        # an undeclared pytest-asyncio/anyio/trio plugin (and often on the
        # upstream repository's discarded pytest configuration).  Such a node
        # is outside this runner profile, so omit it instead of misreporting a
        # healthy pinned distribution as broken.
        if isinstance(item, ast.FunctionDef):
            if item.name.startswith("test_"):
                nodes.append((item.name, item, ()))
        elif isinstance(item, ast.ClassDef):
            for method in item.body:
                if (
                    isinstance(method, ast.FunctionDef)
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
    scored: list[tuple[int, int, str]] = []
    for path in _admitted_test_files(repo_dir):
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
            structural_observed = {
                _normalise_identifier(item.id)
                for item in ast.walk(node)
                if isinstance(item, ast.Name)
            }
            structural_observed.update(
                _normalise_identifier(item.attr)
                for item in ast.walk(node)
                if isinstance(item, ast.Attribute)
            )
            lexical_observed = {
                _normalise_identifier(part)
                for part in node.name.removeprefix("test_").split("_")
            }
            # File/class names are valid structural evidence too. This
            # lets a qualified call such as ``SeqIO.parse`` distinguish a
            # focused test module from unrelated ``parse`` users.
            lexical_observed.update(
                _normalise_identifier(part)
                for part in re.split(r"[^A-Za-z0-9]+", rel)
                if part
            )
            lexical_observed.update(
                _normalise_identifier(part)
                for part in re.split(r"[^A-Za-z0-9]+", node_id)
                if part
            )
            observed = structural_observed | lexical_observed
            hits = sum(
                len(path)
                for path in wanted_paths
                if set(path).issubset(observed)
                # Very short public symbols such as ``on`` are common
                # prose fragments in test names.  They may select a node
                # only when the node's executable AST actually references
                # them; longer capability names may still use focused file
                # and node names as evidence.
                and (
                    all(len(part) >= 3 for part in path)
                    or set(path).issubset(structural_observed)
                )
            )
            if hits:
                # A self-contained node is more likely to run under the
                # declared base-pytest conformance profile.  Nodes with
                # parameters may rely on repository-specific fixtures;
                # retain them as fallbacks, but do not let their pathname
                # ordering displace an equally relevant zero-fixture node.
                fixture_count = len(node.args.posonlyargs) + len(node.args.args)
                if fixture_count and node.args.args[0].arg in {"self", "cls"}:
                    fixture_count -= 1
                scored.append((hits, fixture_count, f"{rel}::{node_id}"))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [node for _, _, node in scored[:max_nodes]]


_PROBE_RESULT_RE = re.compile(r"^(PASSED|FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?$", re.MULTILINE)
_PROBE_TIMEOUT_S = 300


def _candidate_execution_roots(upstream_dir: Path, selected: list[str]) -> list[tuple[str, Path]]:
    """Repository root first, then the single real-cased test root (see precheck)."""

    test_roots: set[str] = set()
    for item in selected:
        path, _separator, _node = item.partition("::")
        parts = Path(path).parts
        if parts:
            test_roots.add(parts[0])
    roots: list[tuple[str, Path]] = [(".", Path(upstream_dir))]
    if len(test_roots) == 1:
        name = next(iter(test_roots))
        candidate = Path(upstream_dir) / name
        if candidate.is_dir() and not candidate.is_symlink():
            roots.append((name, candidate))
    return roots


def _imports_module(source: str, module: str) -> bool:
    """Module-level import only: an import inside one test body must not prune its siblings."""

    top = module.split(".")[0]
    return re.search(rf"^(?:import|from)\s+{re.escape(top)}\b", source, re.MULTILINE) is not None


def probe_runnable_nodes(
    repo_dir: Path,
    candidates: list[str],
    python: Path,
    *,
    max_nodes: int = 3,
) -> tuple[list[str], list[dict[str, str]]]:
    """Keep only the candidate nodes that really pass under ``python``.

    The static runner profile cannot see a runtime import inside a test body
    or a suite-wide parametrization a conftest injects, so a frozen selection
    could fail at rehearsal on a test-only package the pinned runtime never
    had (incident-conformance-node-needs-absent-test-dependency-*).  Each
    candidate is executed once, in ranked order, under the suite's admitted
    execution roots; passing ids (parameter ids included) are kept, a
    ``ModuleNotFoundError`` prunes every later candidate whose file imports
    that module, and nothing is installed.  Returns ``(kept, dropped)`` where
    each dropped row names the node and, when known, the missing module.
    """

    repo_dir = Path(repo_dir)
    kept: list[str] = []
    dropped: list[dict[str, str]] = []
    absent_modules: set[str] = set()
    roots = _candidate_execution_roots(repo_dir, candidates)
    for candidate in candidates:
        if len(kept) >= max_nodes:
            break
        file_part = candidate.partition("::")[0]
        try:
            source = (repo_dir / file_part).read_text(encoding="utf-8", errors="replace")
        except OSError:
            source = ""
        pruned = next((m for m in sorted(absent_modules) if _imports_module(source, m)), None)
        if pruned is not None:
            dropped.append(
                {"node": candidate, "missing_module": pruned, "reason": "imports absent module (pruned)"}
            )
            continue
        node_part = candidate.partition("::")[2]
        target = f"{repo_dir / file_part}::{node_part}" if node_part else str(repo_dir / file_part)
        argv = [
            str(python), "-m", "pytest", "-q", "-rA", "-c", os.devnull,
            f"--rootdir={repo_dir}", "-p", "no:cacheprovider", target,
        ]
        passed_ids: list[str] = []
        missing: str | None = None
        output = ""
        for _label, root in roots:
            try:
                result = subprocess.run(
                    argv, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S, cwd=str(root)
                )
            except (OSError, subprocess.SubprocessError):
                continue
            output = f"{result.stdout}\n{result.stderr}"
            passed_ids = [
                node_id for status, node_id, _detail in _PROBE_RESULT_RE.findall(result.stdout)
                if status == "PASSED"
            ]
            if passed_ids:
                break
        missing_match = _MISSING_MODULE_RE.search(output)
        missing = missing_match.group(1) if missing_match else None
        if missing:
            absent_modules.add(missing)
        for node_id in passed_ids:
            if len(kept) >= max_nodes:
                break
            if node_id not in kept:
                kept.append(node_id)
        if not passed_ids:
            row = {"node": candidate, "reason": "no passing id under any admitted root"}
            if missing:
                row["missing_module"] = missing
            dropped.append(row)
        elif missing:
            dropped.append(
                {
                    "node": candidate,
                    "missing_module": missing,
                    "reason": "some parameter ids failed on an absent module",
                }
            )
    return kept, dropped


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
    # Upstream suites legitimately differ in their working-directory
    # convention: fixture paths may be relative to the repository root (the
    # path already carries a ``tests/`` prefix) or relative to the real-cased
    # test root itself.  Guessing one convention falsely blocks the other, so
    # the harness probes deterministically — repository root first, then the
    # single test root — and records which root the suite actually satisfied.
    # A subset is unhealthy only if it fails under every admitted root; the
    # nodes themselves must still pass unmodified.
    candidate_roots: list[tuple[str, Path]] = [(".", Path(upstream_dir))]
    if len(test_roots) == 1:
        test_root_name = next(iter(test_roots))
        candidate_root = Path(upstream_dir) / test_root_name
        if candidate_root.is_dir() and not candidate_root.is_symlink():
            candidate_roots.append((test_root_name, candidate_root))
    argv = [
        str(python), "-m", "pytest", "-q", "-c", os.devnull,
        f"--rootdir={upstream_dir}", "-p", "no:cacheprovider", *nodes,
    ]
    result = None
    for root_label, execution_root in candidate_roots:
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
                "execution_root": root_label,
                "tail": (
                    result.stdout.strip().splitlines()[-1]
                    if result.stdout.strip()
                    else ""
                ),
            }
    assert result is not None
    output = f"{result.stdout}\n{result.stderr}".strip()
    missing_match = _MISSING_MODULE_RE.search(output)
    missing = missing_match.group(1) if missing_match else None
    suffix = output[-1200:]
    raise UpstreamConformanceError(
        f"上游一致性预检失败(exit {result.returncode})—— 供给/环境问题,"
        f"物化期拒绝:{suffix}",
        missing_module=missing,
    )


# ---------------------------------------------------------------------------
# 钉版源码树能不能顶替发行版(零模型、零执行、纯文件集比对)
#
# 密封运行把**钉版源码检出**放进 PYTHONPATH,它先于 site-packages 里那份已装
# 好的发行版。绝大多数仓库两者内容一致,遮蔽无害;可有些仓库的运行期数据是
# **构建时生成**的(本地化数据表、编译扩展、生成的解析器),git 树里只有一个
# 空占位目录。这时导入照样成功,真正用到那部分能力才炸,而且**任何**参考实现
# 都改不动它——失败与模型无关。
#
# 判据是可判定的:发行版有、源码树没有的运行期文件集非空即不可用。类型标注类
# 文件不参与判定(它们不在运行期被读)。
# ---------------------------------------------------------------------------

_NON_RUNTIME_SUFFIXES = (".pyi",)
_NON_RUNTIME_NAMES = ("py.typed",)


def _runtime_members(names) -> set[str]:
    keep: set[str] = set()
    for raw in names:
        name = str(raw).replace("\\", "/")
        if name.endswith("/") or "/__pycache__/" in name or name.endswith(".pyc"):
            continue
        if ".dist-info/" in name or ".data/" in name:
            continue
        if name.endswith(_NON_RUNTIME_SUFFIXES) or name.rsplit("/", 1)[-1] in _NON_RUNTIME_NAMES:
            continue
        keep.add(name)
    return keep


def _wheel_for(wheelhouse: Path, distribution: str) -> Path | None:
    stem = re.sub(r"[-_.]+", "_", str(distribution or "")).lower()
    if not stem or not wheelhouse.is_dir():
        return None
    for candidate in sorted(wheelhouse.glob("*.whl")):
        head = candidate.name.split("-", 1)[0]
        if re.sub(r"[-_.]+", "_", head).lower() == stem:
            return candidate
    return None


def _source_package_dir(upstream_dir: Path, import_module: str) -> Path | None:
    top = str(import_module or "").split(".", 1)[0]
    if not top:
        return None
    for candidate in (upstream_dir / "src" / top, upstream_dir / top):
        if candidate.is_dir() and not candidate.is_symlink():
            return candidate
    return None


def pinned_source_tree_shadowing(
    *,
    upstream_dir: Path,
    wheelhouse: Path,
    distribution: str,
    import_module: str,
) -> dict:
    """Can the pinned source checkout stand in for the released distribution?

    Returns a public, model-free verdict.  ``usable`` is False only when the
    released distribution carries runtime files the pinned tree does not have:
    PYTHONPATH puts the tree first, so those files are simply unreachable and
    no reference implementation can bring them back.
    """

    upstream_dir = Path(upstream_dir)
    wheel = _wheel_for(Path(wheelhouse), distribution)
    package = _source_package_dir(upstream_dir, import_module)
    top = str(import_module or "").split(".", 1)[0]
    if wheel is None or package is None or not top:
        return {
            "usable": True,
            "checked": False,
            "severity": "NOT_COMPARED",
            "reason": "没有可比对的发行版或源码包目录(不下结论)",
            "distribution": str(distribution or ""),
            "missing_count": 0,
            "missing_sample": (),
            "remediation": "",
        }
    import zipfile

    with zipfile.ZipFile(wheel) as archive:
        released = {
            name for name in _runtime_members(archive.namelist())
            if name == top or name.startswith(f"{top}/")
        }
    present = {
        f"{top}/{path.relative_to(package).as_posix()}"
        for path in package.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    present = _runtime_members(present)
    missing = sorted(released - present)
    # 有缺失不等于顶不住。真实形态相差极大:一个仓库缺的是编译出来的界面翻译
    # (源文件都在),另一个缺的是构建期生成的版本号——两者都跑通了;而"包等于
    # 不在"的那个仓库,源码树只有发行版**不到零头**的运行期文件。所以判死的
    # 条件是「多数运行期文件缺失」——不是调出来的阈值,而是一句话:源码树里
    # 没有的,比有的还多,它就不是发行版的替身。
    severity = "COMPLETE"
    if missing:
        severity = (
            "PACKAGE_LARGELY_ABSENT" if len(missing) * 2 > len(released) else "PARTIAL"
        )
    remediation = ""
    if severity == "PACKAGE_LARGELY_ABSENT":
        remediation = (
            f"钉版源码检出顶不住发行版:{top} 在发行版里有 {len(released)} 个运行期文件,"
            f"这份检出只有 {len(present)} 个,缺 {len(missing)} 个"
            f"(如 {', '.join(missing[:3])})。密封运行把源码检出放在 PYTHONPATH 最前,"
            f"这些文件因此不可达,导入照样成功、真用到才炸,且任何参考实现都改不动它。"
            f"两条出路:把本任务改钉**已构建的发行版**(而不是源码检出),"
            f"或改用一个不需要这部分能力的题目。"
        )
    return {
        "usable": severity != "PACKAGE_LARGELY_ABSENT",
        "checked": True,
        "severity": severity,
        "distribution": str(distribution or ""),
        "import_module": top,
        "released_files": len(released),
        "source_files": len(present),
        "missing_count": len(missing),
        "missing_sample": tuple(missing[:8]),
        "wheel": wheel.name,
        "remediation": remediation,
    }
