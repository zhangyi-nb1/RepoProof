"""Repository Analyzer — Guided Adoption Phase 2(RFC-002)。

唯一副作用 = 匿名浅克隆到 upstream-cache/analysis/<slug>/。
目标仓库代码永不执行(不 install、不 import、不跑 setup.py);
分析全部是确定性静态扫描。零 LLM,零 Docker。
UNKNOWN 永不猜;每个结论带来源。
"""

from __future__ import annotations

import hashlib
import re
import subprocess
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
_RE_SECRET = re.compile(
    r"(?:environ(?:\.get)?\s*[\[(]|getenv\s*\()\s*['\"]([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)['\"]"
)
_RE_TOP_DEF = re.compile(r"^(?:def|class)\s+([A-Za-z_]\w*)", re.MULTILINE)
_RE_ALL = re.compile(r"__all__\s*=\s*[\[(]([^\])]*)[\])]", re.DOTALL)
_LICENSE_KEYWORDS = [
    ("MIT", "MIT License"), ("Apache-2.0", "Apache License"), ("BSD", "BSD"),
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
    quickstart: Finding = Finding.unknown()
    tests: Finding = Finding.unknown()
    capability_candidates: list[CapabilityCandidate] = []
    sources: list[str] = []
    risks: list[str] = []
    scan_stats: ScanStats = ScanStats()

    def to_dict(self) -> dict:
        return self.model_dump()


def clone_for_analysis(url: str, revision: str | None, cache_root: Path) -> tuple[Path | None, str]:
    """匿名浅克隆(唯一副作用);返回 (目录, 错误串)。永不执行仓库代码。"""
    m = _GITHUB_URL.match(url.strip())
    if not m:
        return None, f"不是公开 GitHub 仓库地址格式: {url!r}"
    slug = hashlib.sha256(f"{url}@{revision or 'HEAD'}".encode()).hexdigest()[:12]
    dest = cache_root / "analysis" / f"{m.group(2)}-{slug}"
    if (dest / ".git").is_dir():
        return dest, ""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", "--quiet"]
    if revision:
        cmd += ["--branch", revision]
    cmd += [url, str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False,
                          env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"})
    if proc.returncode != 0:
        return None, proc.stderr.strip()[-300:] or "git clone failed"
    return dest, ""


def _git_head(repo: Path) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=10, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


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
    secrets: list[Finding] = []
    candidates: list[CapabilityCandidate] = []
    seen_secret: set[str] = set()
    for rel, text in _iter_py_files(root, stats):
        rel_s = str(rel)
        if rel.name == "__init__.py" and len(rel.parts) <= 2:
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
        for m3 in _RE_SECRET.finditer(text):
            if m3.group(1) not in seen_secret:
                seen_secret.add(m3.group(1))
                secrets.append(Finding.fact(m3.group(1), rel_s))
    for m4 in _RE_SECRET.finditer(readme_text):
        if m4.group(1) not in seen_secret:
            seen_secret.add(m4.group(1))
            secrets.append(Finding.fact(m4.group(1), readme.name if readme else "README"))
    for name, target in scripts.items():
        cli_entries.append(Finding.fact(f"{name} = {target}", "pyproject.toml [project.scripts]"))
    if secrets:
        risks.append(f"代码/文档要求环境密钥: {sorted(seen_secret)}——当前不自动提供 secret")

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
        secrets_required=secrets[:20],
        quickstart=quickstart,
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

    parseable: list[tuple[object, str]] = []
    other: list[str] = []
    for t in tags:
        s = t[1:] if t[:1] in ("v", "V") else t
        try:
            parseable.append((Version(s), t))
        except InvalidVersion:
            other.append(t)
    parseable.sort(key=lambda p: p[0], reverse=True)  # type: ignore[arg-type]
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
