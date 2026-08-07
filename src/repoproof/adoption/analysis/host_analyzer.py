"""Host Project Analyzer — Guided Adoption Phase 1(RFC-001)。

纯静态分析:不执行项目代码(setup.py 只读文本)、不写文件、不启动
Docker、不调用 LLM、不联网。每个结论标注 FACT / INFERENCE / UNKNOWN
并携带 evidence;无法确定的字段如实 UNKNOWN,禁止编造。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel

FACT = "FACT"
INFERENCE = "INFERENCE"
UNKNOWN = "UNKNOWN"

MAX_PY_FILES = 400
MAX_FILE_BYTES = 200_000
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", "dist",
             ".mypy_cache", ".ruff_cache", ".pytest_cache", "runs", "upstream-cache"}

_INTEGRATION_STEMS = ("parser", "parse", "ingest", "loader", "load", "pipeline",
                      "process", "index", "search", "chunk", "extract", "convert")

_RE_PYDANTIC = re.compile(r"^class\s+(\w+)\s*\([^)]*\bBaseModel\b[^)]*\)", re.MULTILINE)
_RE_DATACLASS = re.compile(r"^@dataclass", re.MULTILINE)
_RE_TYPED = re.compile(r"^class\s+(\w+)\s*\([^)]*\b(TypedDict|NamedTuple)\b[^)]*\)", re.MULTILINE)
_RE_INSTALL_REQUIRES = re.compile(r"install_requires\s*=\s*\[([^\]]*)\]", re.DOTALL)
_RE_DEP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


class Finding(BaseModel):
    """一个可追溯的结论:值 + 来源等级 + 证据。"""

    value: object = None
    provenance: str = UNKNOWN
    evidence: str = ""

    @classmethod
    def fact(cls, value, evidence: str) -> Finding:
        return cls(value=value, provenance=FACT, evidence=evidence)

    @classmethod
    def inference(cls, value, evidence: str) -> Finding:
        return cls(value=value, provenance=INFERENCE, evidence=evidence)

    @classmethod
    def unknown(cls, note: str = "not determinable from static analysis") -> Finding:
        return cls(value=None, provenance=UNKNOWN, evidence=note)


class IntegrationCandidate(BaseModel):
    file: str
    reason: str
    provenance: str = INFERENCE


class ScanStats(BaseModel):
    py_files_seen: int = 0
    py_files_scanned: int = 0
    truncated: bool = False
    skipped_oversize: int = 0


class HostProjectReport(BaseModel):
    project_path: str
    project_type: Finding
    python_version: Finding
    package_manager: Finding
    entry_points: list[Finding] = []
    test_command: Finding
    dependencies: list[str] = []
    dependencies_evidence: str = ""
    frameworks: list[Finding] = []
    schemas: list[Finding] = []
    integration_candidates: list[IntegrationCandidate] = []
    protected_paths: list[str] = []
    risks: list[str] = []
    scan_stats: ScanStats = ScanStats()

    def to_dict(self) -> dict:
        return self.model_dump()


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _iter_py_files(root: Path, stats: ScanStats):
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        stats.py_files_seen += 1
        if stats.py_files_scanned >= MAX_PY_FILES:
            stats.truncated = True
            continue
        text = _read_text(path)
        if text is None:
            stats.skipped_oversize += 1
            continue
        stats.py_files_scanned += 1
        yield path.relative_to(root), text


def _parse_dep_name(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith(("#", "-", "git+")):
        return None
    m = _RE_DEP_NAME.match(line)
    return m.group(0).lower() if m else None


def analyze_host_project(project_path: str | Path) -> HostProjectReport:
    """静态分析一个本地 Python 项目;永不修改它。"""
    root = Path(project_path).expanduser().resolve()
    stats = ScanStats()
    if not root.is_dir():
        return HostProjectReport(
            project_path=str(root),
            project_type=Finding.unknown("path does not exist or is not a directory"),
            python_version=Finding.unknown(),
            package_manager=Finding.unknown(),
            test_command=Finding.unknown(),
            risks=["项目路径不存在,无法分析"],
            scan_stats=stats,
        )

    deps: list[str] = []
    deps_evidence = ""
    scripts: dict[str, str] = {}
    requires_python: str | None = None
    pytest_configured = False

    # ---- 1. pyproject.toml(FACT 源) ----
    pyproject = root / "pyproject.toml"
    pyproject_data: dict = {}
    if pyproject.exists():
        try:
            pyproject_data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            pyproject_data = {}
        proj = pyproject_data.get("project") or {}
        requires_python = proj.get("requires-python")
        for dep in proj.get("dependencies") or []:
            name = _parse_dep_name(dep)
            if name:
                deps.append(name)
        scripts = dict(proj.get("scripts") or {})
        if deps:
            deps_evidence = "pyproject.toml [project.dependencies]"
        if "tool" in pyproject_data and "pytest" in pyproject_data["tool"]:
            pytest_configured = True

    # ---- 2. requirements.txt ----
    requirements = root / "requirements.txt"
    if requirements.exists():
        text = _read_text(requirements) or ""
        req_deps = [n for n in (_parse_dep_name(ln) for ln in text.splitlines()) if n]
        for name in req_deps:
            if name not in deps:
                deps.append(name)
        if req_deps and not deps_evidence:
            deps_evidence = "requirements.txt"
        elif req_deps:
            deps_evidence += " + requirements.txt"

    # ---- 3. setup.py(只读文本,绝不执行) ----
    setup_py = root / "setup.py"
    if setup_py.exists() and not deps:
        text = _read_text(setup_py) or ""
        m = _RE_INSTALL_REQUIRES.search(text)
        if m:
            for chunk in m.group(1).split(","):
                name = _parse_dep_name(chunk.strip().strip("'\""))
                if name and name not in deps:
                    deps.append(name)
            deps_evidence = "setup.py install_requires(文本解析,未执行)"

    # ---- python version ----
    python_version = (
        Finding.fact(requires_python, "pyproject.toml [project.requires-python]")
        if requires_python
        else Finding.unknown("no requires-python declaration found")
    )

    # ---- package manager ----
    if (root / "poetry.lock").exists():
        package_manager = Finding.fact("poetry", "poetry.lock")
    elif (root / "uv.lock").exists():
        package_manager = Finding.fact("uv", "uv.lock")
    elif (root / "Pipfile").exists():
        package_manager = Finding.fact("pipenv", "Pipfile")
    elif requirements.exists():
        package_manager = Finding.fact("pip", "requirements.txt")
    elif pyproject.exists():
        package_manager = Finding.inference("pip", "pyproject.toml 存在但无 lockfile,推断 pip")
    else:
        package_manager = Finding.unknown()

    # ---- 4. pytest / test command ----
    tests_dir = (root / "tests").is_dir()
    if (root / "pytest.ini").exists() or pytest_configured:
        ev = "pytest.ini" if (root / "pytest.ini").exists() else "pyproject.toml [tool.pytest.ini_options]"
        test_command = Finding.fact("pytest", ev)
    elif tests_dir:
        test_command = Finding.inference("pytest", "tests/ 目录存在,推断 pytest")
    else:
        test_command = Finding.unknown("no pytest config or tests/ directory")

    # ---- 源码扫描(5/6/7/9/10 + 集成点) ----
    frameworks: list[Finding] = []
    schemas: list[Finding] = []
    entry_points: list[Finding] = []
    candidates: list[IntegrationCandidate] = []
    fw_seen: set[str] = set()
    cli_lib_seen: str | None = None

    for name, dep_ev in (("fastapi", deps_evidence), ("flask", deps_evidence)):
        if name in deps:
            frameworks.append(Finding.fact(name, dep_ev or "dependency declaration"))
            fw_seen.add(name)

    for rel, text in _iter_py_files(root, stats):
        rel_s = str(rel)
        if "fastapi" not in fw_seen and re.search(r"^\s*(from|import)\s+fastapi\b", text, re.MULTILINE):
            frameworks.append(Finding.fact("fastapi", f"{rel_s}: import fastapi"))
            fw_seen.add("fastapi")
        if "flask" not in fw_seen and re.search(r"^\s*(from|import)\s+flask\b", text, re.MULTILINE):
            frameworks.append(Finding.fact("flask", f"{rel_s}: import flask"))
            fw_seen.add("flask")
        for lib in ("click", "typer", "argparse"):
            if cli_lib_seen is None and re.search(rf"^\s*(from|import)\s+{lib}\b", text, re.MULTILINE):
                cli_lib_seen = f"{rel_s}: import {lib}"
        for m in _RE_PYDANTIC.finditer(text):
            schemas.append(Finding.fact(f"{m.group(1)} (pydantic)", rel_s))
        for m in _RE_TYPED.finditer(text):
            schemas.append(Finding.fact(f"{m.group(1)} ({m.group(2)})", rel_s))
        if _RE_DATACLASS.search(text):
            schemas.append(Finding.fact("@dataclass definitions", rel_s))
        if rel.name == "__main__.py":
            entry_points.append(Finding.fact(f"python -m {rel.parent.name}", rel_s))
        stem_hit = next((s for s in _INTEGRATION_STEMS if s in rel.stem.lower()), None)
        if stem_hit:
            candidates.append(IntegrationCandidate(
                file=rel_s, reason=f"模块名含「{stem_hit}」,疑似数据处理入口"))

    for script_name, target in scripts.items():
        entry_points.append(Finding.fact(f"{script_name} = {target}", "pyproject.toml [project.scripts]"))

    # schema 所在文件也是集成点候选
    schema_files = {f.evidence for f in schemas if f.provenance == FACT}
    for sf in sorted(schema_files):
        if not any(c.file == sf for c in candidates):
            candidates.append(IntegrationCandidate(file=sf, reason="定义了数据结构/Schema"))

    # ---- 8. src 布局 ----
    src_layout = any((root / "src").glob("*/__init__.py")) if (root / "src").is_dir() else False

    # ---- project type(INFERENCE) ----
    if "fastapi" in fw_seen or "flask" in fw_seen:
        project_type = Finding.inference("service", "检测到 Web 框架")
    elif scripts or cli_lib_seen:
        ev = "pyproject [project.scripts]" if scripts else str(cli_lib_seen)
        project_type = Finding.inference("cli", ev)
    elif src_layout or pyproject.exists():
        project_type = Finding.inference("library", "src 布局或 pyproject 打包配置")
    elif stats.py_files_scanned > 0:
        project_type = Finding.inference("scripts", "散落 .py 文件,无打包配置")
    else:
        project_type = Finding.unknown("no python files found")

    if cli_lib_seen and not scripts and not any("__main__" in str(e.value) for e in entry_points):
        entry_points.append(Finding.inference("CLI(库导入推断,入口未定位)", cli_lib_seen))

    # ---- protected paths(规则默认) ----
    protected = [p for p, cond in [
        (".git/", (root / ".git").exists()),
        ("tests/", tests_dir),
        ("pyproject.toml", pyproject.exists()),
        ("requirements.txt", requirements.exists()),
        ("poetry.lock", (root / "poetry.lock").exists()),
        ("uv.lock", (root / "uv.lock").exists()),
    ] if cond]

    # ---- risks(确定性检查) ----
    risks: list[str] = []
    if test_command.provenance == UNKNOWN:
        risks.append("未找到测试配置——适配后无法用你自己的测试确认原功能不受影响")
    if python_version.provenance == UNKNOWN:
        risks.append("未声明 Python 版本要求——环境兼容性需要人工确认")
    if not deps and stats.py_files_scanned > 0:
        risks.append("未找到依赖声明文件——依赖关系只能靠人工确认")
    if stats.truncated:
        risks.append(f"项目过大,仅扫描前 {MAX_PY_FILES} 个 .py 文件——分析结果不完整")

    return HostProjectReport(
        project_path=str(root),
        project_type=project_type,
        python_version=python_version,
        package_manager=package_manager,
        entry_points=entry_points,
        test_command=test_command,
        dependencies=sorted(set(deps)),
        dependencies_evidence=deps_evidence,
        frameworks=frameworks,
        schemas=schemas[:50],
        integration_candidates=candidates[:20],
        protected_paths=protected,
        risks=risks,
        scan_stats=stats,
    )
