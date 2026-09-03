"""Repository Analyzer — Guided Adoption Phase 2(RFC-002)。

唯一副作用 = 匿名浅克隆到 upstream-cache/analysis/<slug>/。
目标仓库代码永不执行(不 install、不 import、不跑 setup.py);
分析全部是确定性静态扫描。零 LLM,零 Docker。
UNKNOWN 永不猜;每个结论带来源。
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

from pydantic import BaseModel

from repoproof.adoption.analysis.host_analyzer import (
    Finding,
    ScanStats,
    _iter_py_files,
    _parse_dep_name,
    _read_text,
)

_GITHUB_URL = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")

_GPU_DEPS = {"torch", "torchvision", "torchaudio", "tensorflow", "cupy", "triton",
             "jax", "flash-attn", "bitsandbytes", "vllm", "deepspeed"}
_EXTERNAL_DEPS = {"openai", "anthropic", "google-genai", "boto3", "redis", "qdrant-client",
                  "chromadb", "pinecone", "weaviate-client", "pymongo", "psycopg2", "mysqlclient",
                  "elasticsearch", "kafka-python"}
_SECRET_NAME = r"([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)"
_RE_SECRET_MENTION = re.compile(
    rf"\b(?:environ\s*\[\s*|environ\.get\s*\(\s*|getenv\s*\(\s*)['\"]{_SECRET_NAME}['\"]"
)
_SECRET_NAME_FULL = re.compile(_SECRET_NAME.strip("()"))
# 上游自身的测试/示例/文档目录:其中的密钥读取不构成被采纳能力的运行时
# 需求(conformance 选节点时另行验证可运行性),单独入账、不静默丢弃。
_NON_RUNTIME_ZONES = frozenset(
    {"tests", "test", "testing", "docs", "doc", "examples", "example"}
)
_RE_TOP_DEF = re.compile(r"^(?:def|class)\s+([A-Za-z_]\w*)", re.MULTILINE)
_RE_ALL = re.compile(r"__all__\s*=\s*[\[(]([^\])]*)[\])]", re.DOTALL)
_LICENSE_KEYWORDS = [
    ("MIT", "MIT License"),
    # 无标题正文形态(COPYING 惯例常见,jsonschema 实测):直接版权行 +
    # 特征句 —— 这两句是 MIT/BSD 的专属措辞,识别度高于标题行。
    ("MIT", "Permission is hereby granted, free of charge"),
    ("Apache-2.0", "Apache License"), ("BSD", "BSD"),
    ("BSD", "Redistribution and use in source and binary forms"),
    ("GPL-3.0", "GNU GENERAL PUBLIC LICENSE"), ("MPL-2.0", "Mozilla Public License"),
    ("Unlicense", "unlicense"),
]


class CapabilityCandidate(BaseModel):
    name: str
    interface: str
    evidence: str


class RepositoryReport(BaseModel):
    repository: str
    requested_revision: str | None = None
    is_public: Finding
    commit: Finding
    license: Finding
    python_version: Finding
    install_method: Finding
    dependencies: list[str] = []
    dependencies_evidence: str = ""
    public_api: list[Finding] = []
    cli_entry_points: list[Finding] = []
    runtime: dict = {"python": True, "gpu": False, "external_api": False}
    gpu: Finding = Finding.unknown()
    external_services: Finding = Finding.unknown()
    secrets_required: list[Finding] = []
    secrets_optional: list[Finding] = []
    # 上游测试/示例/文档区的密钥读取:可见但不计入运行时需求(I4)。
    secrets_test_zone: list[Finding] = []
    quickstart: Finding = Finding.unknown()
    # README 正文摘录(有界):此前只留第一个代码块当 quickstart,正文丢掉了,
    # 于是"这个仓库到底是干什么的"在 UI 里无从展示。**它是展示件**:不参与
    # 任何判定,也不得自动填进用户的能力描述(那会把人闸架空)。
    readme_excerpt: str = ""
    tests: Finding = Finding.unknown()
    capability_candidates: list[CapabilityCandidate] = []
    sources: list[str] = []
    risks: list[str] = []
    scan_stats: ScanStats = ScanStats()

    def to_dict(self) -> dict:
        return self.model_dump()


def _rst_code_block(text: str) -> str:
    """RST README 里的上手片段:优先 doctest(`>>>` 连续行),其次 `::` 缩进块。

    只做提取,取第一段即可 —— 它的用途是"让人看一眼这库怎么用",不是文档。
    """
    lines = (text or "").splitlines()
    doctest: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith(">>>") or (doctest and s and not s.startswith(("..", ":"))):
            doctest.append(s)
        elif doctest:
            break
    if doctest:
        return "\n".join(doctest)

    for i, ln in enumerate(lines):                 # `::` 之后的缩进块
        if ln.rstrip().endswith("::"):
            block: list[str] = []
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    if block:
                        break
                    continue
                if nxt[:1] in (" ", "\t"):
                    block.append(nxt.strip())
                else:
                    break
            if block:
                return "\n".join(block)
    return ""


_README_PROSE_CAP = 1200          # 展示用摘录上限,避免把报告撑大
# 徽章/图片/HTML 壳/标题下划线(Markdown),以及 RST 的指令、注释与字段行
# —— `.. image::` / `:alt:` 这类在纯 RST 的 README 里可能占满开头。
_BADGE_LINE = re.compile(
    r"^\s*(\[!\[|!\[|<img|<a\s|<p\s|<div\s|=+\s*$|-+\s*$|~+\s*$"
    r"|\.\.\s|:[A-Za-z][\w-]*:\s)")
_MOSTLY_URL = re.compile(r"^\s*(https?://\S+\s*)+$")


def readme_prose(readme_text: str, *, cap: int = _README_PROSE_CAP) -> str:
    """README 正文摘录(确定性,零模型):去掉徽章/图片/HTML 壳与标题装饰,
    取前若干段落。

    只做**提取**,不做概括 —— 概括是模型的活,而模型产物在本项目里只能
    进展示层。这一份是"仓库自己怎么说自己",来源可指认(README 原文)。
    """
    out: list[str] = []
    used = 0
    for para in re.split(r"\n\s*\n", readme_text or ""):
        lines = [ln for ln in para.strip().splitlines()
                 if ln.strip() and not _BADGE_LINE.match(ln)]
        if not lines:
            continue
        text = " ".join(ln.strip() for ln in lines)
        if text.startswith("#"):                  # 标题:留文字,去井号
            text = text.lstrip("#").strip()
            if not text:
                continue
        if text.startswith("```") or text.startswith("::"):   # 代码块另有 quickstart
            continue
        if _MOSTLY_URL.match(text):               # 纯链接行不算介绍
            continue
        out.append(text)
        used += len(text)
        if used >= cap:
            break
    return "\n\n".join(out)[:cap].strip()


_ANALYSIS_GIT_TIMEOUT_SECONDS = 300


def clone_for_analysis(url: str, revision: str | None, cache_root: Path) -> tuple[Path | None, str]:
    """匿名浅克隆(唯一副作用);返回 (目录, 错误串)。永不执行仓库代码。"""
    m = _GITHUB_URL.match(url.strip())
    if not m:
        return None, f"不是公开 GitHub 仓库地址格式: {url!r}"
    slug = hashlib.sha256(f"{url}@{revision or 'HEAD'}".encode()).hexdigest()[:12]
    dest = cache_root / "analysis" / f"{m.group(2)}-{slug}"
    if (dest / ".git").is_dir() and _git_head(dest):
        return dest, ""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return None, f"分析缓存存在但不是有效 git checkout:{dest}"

    git_env = {"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    # `git clone --branch <revision>` 只接受分支/标签；完整 commit 会被误当
    # 成远端分支并报 `Remote branch ... not found`。资格测试固定的是 40 位
    # commit，所以 revision 路径统一使用 init + fetch + detached checkout。
    # 临时目录保证失败时不会留下一个带 `.git` 的半成品缓存。
    with tempfile.TemporaryDirectory(prefix=f".{m.group(2)}-analysis-", dir=dest.parent) as tmp:
        tmp_path = Path(tmp)
        commands = (
            ["git", "init", "--quiet", str(tmp_path)],
            ["git", "-C", str(tmp_path), "remote", "add", "origin", url],
            [
                "git", "-C", str(tmp_path), "fetch", "--depth", "1", "--quiet",
                "origin", revision or "HEAD",
            ],
            ["git", "-C", str(tmp_path), "checkout", "--detach", "--quiet", "FETCH_HEAD"],
        )
        for cmd in commands:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_ANALYSIS_GIT_TIMEOUT_SECONDS,
                check=False,
                env=git_env,
            )
            if proc.returncode != 0:
                return None, proc.stderr.strip()[-300:] or "git checkout failed"
        tmp_path.replace(dest)
    return dest, ""


def _git_head(repo: Path) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=10, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _is_secret_env_name(name: str) -> bool:
    return _SECRET_NAME_FULL.fullmatch(name) is not None


def _module_secret_env_reads(tree: ast.Module) -> tuple[set[str], set[str]]:
    """按可执行语义提取 (必需式读取, 可选式读取) 的进程环境密钥名。

    必需式 = 对 os.environ(或其 from-import 别名)的下标 **读取**;
    可选式 = environ.get / os.getenv 带常量名调用。字符串字面量因不
    进入 AST 表达式结构而天然排除;Store/Del 上下文(赋值/清理)是
    "提供"不是"要求";WSGI 等同名形参对象通过 import 别名闭包排除。
    """

    os_aliases: set[str] = set()
    environ_aliases: set[str] = set()
    getenv_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "os":
                    os_aliases.add(alias.asname or "os")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name == "environ":
                    environ_aliases.add(alias.asname or "environ")
                elif alias.name == "getenv":
                    getenv_aliases.add(alias.asname or "getenv")

    def _is_environ(expr: ast.expr) -> bool:
        if isinstance(expr, ast.Name):
            return expr.id in environ_aliases
        return (
            isinstance(expr, ast.Attribute)
            and expr.attr == "environ"
            and isinstance(expr.value, ast.Name)
            and expr.value.id in os_aliases
        )

    required: set[str] = set()
    optional: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Load)
            and _is_environ(node.value)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            if _is_secret_env_name(node.slice.value):
                required.add(node.slice.value)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            is_get = (
                (isinstance(func, ast.Attribute) and func.attr == "get" and _is_environ(func.value))
                or (
                    isinstance(func, ast.Attribute)
                    and func.attr == "getenv"
                    and isinstance(func.value, ast.Name)
                    and func.value.id in os_aliases
                )
                or (isinstance(func, ast.Name) and func.id in getenv_aliases)
            )
            first = node.args[0]
            if is_get and isinstance(first, ast.Constant) and isinstance(first.value, str):
                if _is_secret_env_name(first.value):
                    optional.add(first.value)
    return required, optional


def _scan_secret_env_reads(
    root: Path,
) -> tuple[dict[str, Finding], dict[str, Finding], dict[str, Finding], int]:
    """全树确定性密钥读取扫描:(必需, 可选, 非运行时区, 解析失败数)。

    密钥面是 admission 硬判据,故不受通用扫描的文件数上限约束(I3):
    截断既会按字母序制造假阳,也会静默漏掉上限之后的真实需求。逐文件
    大小上限沿用 _read_text;无法按 3.12 语法解析的文件不属于可导入
    运行时,计数后跳过。
    """

    from repoproof.adoption.analysis.host_analyzer import SKIP_DIRS

    required: dict[str, Finding] = {}
    optional: dict[str, Finding] = {}
    non_runtime: dict[str, Finding] = {}
    parse_failed = 0
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        parts = rel.parts
        if any(part in SKIP_DIRS for part in parts):
            continue
        text = _read_text(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            parse_failed += 1
            continue
        module_required, module_optional = _module_secret_env_reads(tree)
        rel_s = str(rel)
        if any(part in _NON_RUNTIME_ZONES for part in parts[:-1]):
            for name in module_required | module_optional:
                non_runtime.setdefault(name, Finding.fact(name, rel_s))
            continue
        for name in module_required:
            required.setdefault(name, Finding.fact(name, rel_s))
        for name in module_optional:
            optional.setdefault(name, Finding.fact(name, rel_s))
    for name in required:
        optional.pop(name, None)
        non_runtime.pop(name, None)
    return required, optional, non_runtime, parse_failed


def analyze_repository_dir(
    repo_dir: str | Path,
    *,
    url: str = "",
    requested_revision: str | None = None,
    is_public: Finding | None = None,
) -> RepositoryReport:
    """对已就位的仓库目录做确定性静态分析(离线;测试注入点)。"""
    root = Path(repo_dir).resolve()
    stats = ScanStats()
    sources: list[str] = []
    risks: list[str] = []

    # ---- 3. commit ----
    head = _git_head(root)
    commit = Finding.fact(head, "git rev-parse HEAD") if head else Finding.unknown(
        "目录不是 git 仓库,无法固定 commit")
    if head is None:
        risks.append("无法固定版本(非 git 仓库)——结果不可复现")

    # ---- pyproject / requirements(复用 RFC-001 解析) ----
    deps: list[str] = []
    deps_evidence = ""
    requires_python = None
    scripts: dict[str, str] = {}
    build_system = False
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        sources.append("pyproject.toml")
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            data = {}
        proj = data.get("project") or {}
        requires_python = proj.get("requires-python")
        scripts = dict(proj.get("scripts") or {})
        build_system = "build-system" in data
        lic = proj.get("license")
        for dep in proj.get("dependencies") or []:
            name = _parse_dep_name(dep)
            if name:
                deps.append(name)
        if deps:
            deps_evidence = "pyproject.toml"
    else:
        lic = None
    requirements = root / "requirements.txt"
    if requirements.exists():
        sources.append("requirements.txt")
        for ln in (_read_text(requirements) or "").splitlines():
            name = _parse_dep_name(ln)
            if name and name not in deps:
                deps.append(name)
        deps_evidence = (deps_evidence + " + requirements.txt").lstrip(" +")

    # ---- 2. license ----
    license_finding = Finding.unknown("no LICENSE file or pyproject license field")
    lic_file = next((p for p in (root / n for n in
                     ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING")) if p.exists()), None)
    if lic_file:
        sources.append(lic_file.name)
        head_text = (_read_text(lic_file) or "")[:2000]
        spdx = next((s for s, kw in _LICENSE_KEYWORDS if kw.lower() in head_text.lower()), None)
        license_finding = Finding.fact(spdx or "存在但未识别类型", lic_file.name)
        if spdx is None:
            risks.append("LICENSE 文件存在但类型未识别——需人工确认许可证兼容性")
    elif lic:
        val = lic if isinstance(lic, str) else (lic.get("text") or lic.get("file") or str(lic))
        license_finding = Finding.fact(val, "pyproject.toml [project.license]")
    else:
        risks.append("未找到许可证——采用前必须人工确认")

    # ---- 4. python version ----
    python_version = (Finding.fact(requires_python, "pyproject.toml requires-python")
                      if requires_python else Finding.unknown("no requires-python declaration"))

    # ---- 5. install method ----
    if build_system:
        install_method = Finding.fact("pip install(pyproject build-system)", "pyproject.toml")
    elif (root / "setup.py").exists():
        install_method = Finding.fact("pip install(setup.py)", "setup.py(未执行)")
        sources.append("setup.py")
    elif any(root.glob("*/__init__.py")):
        install_method = Finding.inference("不可直接安装——需源码复制/wheel 构建", "无打包配置,存在包目录")
        risks.append("无标准打包配置——安装方式需要人工确认")
    else:
        install_method = Finding.unknown()

    # ---- README / 12. quickstart ----
    readme = next((p for p in (root / n for n in
                   ("README.md", "README.rst", "README.txt", "README")) if p.exists()), None)
    readme_text = ""
    quickstart = Finding.unknown("no README found")
    if readme:
        sources.append(readme.name)
        readme_text = _read_text(readme) or ""
        m = re.search(r"```(?:python|bash|sh)?\n(.*?)```", readme_text, re.DOTALL)
        if m:
            quickstart = Finding.fact(m.group(1).strip()[:500], f"{readme.name} 首个代码块")
        elif (rst := _rst_code_block(readme_text)):
            # RST 的 README 不用 ``` 围栏,只认它等于对纯 RST 仓库永远抓不到
            # 上手片段；否则带现成 doctest 的 README 会被误报为"无代码块"。
            quickstart = Finding.fact(rst[:500], f"{readme.name} doctest/代码块(RST)")
        else:
            quickstart = Finding.inference("README 存在但无代码块", readme.name)
    else:
        risks.append("无 README——用法只能靠源码人工确认")

    # ---- 9/10. GPU / 外部服务 ----
    gpu_hits = sorted(set(deps) & _GPU_DEPS)
    readme_cuda = bool(re.search(r"\bCUDA\b|\bGPU required\b", readme_text))
    if gpu_hits:
        gpu = Finding.fact(True, f"依赖含 GPU 包: {gpu_hits}({deps_evidence})")
    elif readme_cuda:
        gpu = Finding.inference(True, f"{readme.name if readme else 'README'} 提及 CUDA/GPU")
    else:
        gpu = Finding.fact(False, "依赖与 README 均无 GPU 迹象")
    ext_hits = sorted(set(deps) & _EXTERNAL_DEPS)
    external = (Finding.fact(ext_hits, f"依赖含外部服务客户端({deps_evidence})")
                if ext_hits else Finding.fact([], "依赖中无已知外部服务客户端"))
    if gpu.value is True:
        risks.append("需要 GPU——超出当前 CPU-only 支持范围")
    if ext_hits:
        risks.append(f"依赖外部服务客户端 {ext_hits}——运行可能需要网络/账号")

    # ---- 源码扫描:7 public api / 8 cli / 11 secrets / 候选 ----
    public_api: list[Finding] = []
    cli_entries: list[Finding] = []
    candidates: list[CapabilityCandidate] = []

    # 密钥读取走独立全树 AST 扫描(I1-I4):必需式只能来自可执行读取,
    # 不受下方通用扫描的 MAX_PY_FILES 截断影响。
    secrets, optional_secrets, test_zone_secrets, secret_parse_failed = (
        _scan_secret_env_reads(root)
    )

    for rel, text in _iter_py_files(root, stats):
        rel_s = str(rel)
        # 顶层包 __init__:兼容根布局(pkg/__init__.py)与 src 布局
        # (src/pkg/__init__.py)——后者是现实主流,漏掉它会把整包 API
        # 判成不存在(Gate 1 fixture 实测;批次二 phonenumbers 同源坑)。
        top_init = (rel.name == "__init__.py"
                    and (len(rel.parts) <= 2
                         or (rel.parts[0] == "src" and len(rel.parts) == 3)))
        if top_init:
            m = _RE_ALL.search(text)
            if m:
                names = [n.strip().strip("'\"") for n in m.group(1).split(",") if n.strip()]
                for n in names[:15]:
                    public_api.append(Finding.fact(n, f"{rel_s} __all__"))
            else:
                for m2 in list(_RE_TOP_DEF.finditer(text))[:10]:
                    public_api.append(Finding.fact(m2.group(1), rel_s))
        if rel.name == "__main__.py":
            cli_entries.append(Finding.fact(f"python -m {rel.parent.name}", rel_s))
    # README 是文档:提及只能构成可选式风险,不能构成"要求"(I1)。
    readme_evidence = readme.name if readme else "README"
    for match in _RE_SECRET_MENTION.finditer(readme_text):
        name = match.group(1)
        if name not in secrets:
            optional_secrets.setdefault(name, Finding.fact(name, readme_evidence))
    for name, target in scripts.items():
        cli_entries.append(Finding.fact(f"{name} = {target}", "pyproject.toml [project.scripts]"))
    if secrets:
        risks.append(
            f"代码要求环境密钥: {sorted(secrets)}——当前不自动提供 secret"
        )
    if optional_secrets:
        risks.append(
            "代码/文档包含可选式环境密钥读取: "
            f"{sorted(optional_secrets)}——所选能力必须在无凭证预检中通过"
        )
    if test_zone_secrets:
        risks.append(
            "上游测试/示例/文档目录读取环境密钥: "
            f"{sorted(test_zone_secrets)}——不计入所选能力的运行时需求;"
            "无凭证预检仍会强制验证"
        )
    if secret_parse_failed:
        risks.append(
            f"密钥扫描:{secret_parse_failed} 个 Python 文件无法按当前语法解析,"
            "未纳入读取分析"
        )

    for f in public_api[:10]:
        candidates.append(CapabilityCandidate(
            name=str(f.value), interface=f"importable symbol `{f.value}`", evidence=f.evidence))

    # ---- 13. tests ----
    tests_dir = root / "tests"
    if tests_dir.is_dir():
        n_tests = len(list(tests_dir.rglob("test_*.py")))
        tests = Finding.fact(f"tests/ 存在,{n_tests} 个测试文件", "tests/")
    else:
        tests = Finding.unknown("no tests/ directory")
        risks.append("仓库无测试目录——行为只能靠参考校准确认")

    if stats.truncated:
        risks.append("仓库过大,源码扫描不完整")

    return RepositoryReport(
        repository=url or str(root),
        requested_revision=requested_revision,
        is_public=is_public or Finding.unknown("由 clone 结果判定;本次为本地目录分析"),
        commit=commit,
        license=license_finding,
        python_version=python_version,
        install_method=install_method,
        dependencies=sorted(set(deps)),
        dependencies_evidence=deps_evidence,
        public_api=public_api[:30],
        cli_entry_points=cli_entries,
        runtime={"python": True, "gpu": bool(gpu.value), "external_api": bool(ext_hits)},
        gpu=gpu,
        external_services=external,
        secrets_required=list(secrets.values())[:20],
        secrets_optional=list(optional_secrets.values())[:20],
        secrets_test_zone=list(test_zone_secrets.values())[:20],
        quickstart=quickstart,
        readme_excerpt=readme_prose(readme_text),
        tests=tests,
        capability_candidates=candidates,
        sources=sorted(set(sources)),
        risks=risks,
        scan_stats=stats,
    )


def analyze_repository(
    url: str,
    revision: str | None = None,
    *,
    cache_root: Path,
) -> RepositoryReport:
    """真实入口:匿名浅克隆(唯一副作用)+ 静态分析。"""
    dest, err = clone_for_analysis(url, revision, cache_root)
    if dest is None:
        return RepositoryReport(
            repository=url,
            requested_revision=revision,
            is_public=Finding.unknown(f"clone 失败(可能私有/不存在/网络问题): {err}"),
            commit=Finding.unknown(),
            license=Finding.unknown(),
            python_version=Finding.unknown(),
            install_method=Finding.unknown(),
            risks=[f"无法获取仓库: {err}"],
        )
    return analyze_repository_dir(
        dest, url=url, requested_revision=revision,
        is_public=Finding.fact(True, "匿名浅克隆成功"),
    )


def sort_release_tags(tags: list[str]) -> list[str]:
    """发布 Tag 按版本号降序(可解析的在前,无法解析的字符串降序在后)。"""
    from packaging.version import InvalidVersion, Version

    parseable: list[tuple[Version, str]] = []
    other: list[str] = []
    for t in tags:
        s = t[1:] if t[:1] in ("v", "V") else t
        try:
            parseable.append((Version(s), t))
        except InvalidVersion:
            other.append(t)
    parseable.sort(key=lambda p: p[0], reverse=True)
    return [t for _, t in parseable] + sorted(other, reverse=True)


def list_remote_tags(url: str, timeout: int = 20) -> list[str]:
    """匿名列出远端正式发布 Tag(git ls-remote,不克隆、不执行);失败容忍返回 []。

    动机(用户实测):版本号留空时分析定位默认分支 HEAD,分析结果里
    显示的 commit 被用户当成"系统推荐的版本"抄回版本框——从而钉住了
    打包损坏的开发版。只有把真正的发布 Tag 列出来,才能斩断这个歧义。"""
    try:
        out = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", url],
            capture_output=True, text=True, timeout=timeout, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    tags = [ln.rsplit("refs/tags/", 1)[-1].strip()
            for ln in out.splitlines() if "refs/tags/" in ln]
    return sort_release_tags(tags)
