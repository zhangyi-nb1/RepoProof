"""Guided Adoption Phase 1 — Host Project Analyzer(RFC-001)。

§十五 要求:FastAPI 项目 / CLI 项目 / 普通 Python 包;外加:
空目录不编造、setup.py 永不执行、只读性、provenance 纪律、自测。
零 LLM,零 Docker。"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.analysis.host_analyzer import (
    FACT,
    INFERENCE,
    MAX_PY_FILES,
    UNKNOWN,
    analyze_host_project,
)

REPO = Path(__file__).resolve().parents[2]


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _make_fastapi_project(root: Path) -> None:
    _write(root, "pyproject.toml", """
[project]
name = "my-api"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.100", "pydantic>=2.0", "uvicorn"]

[tool.pytest.ini_options]
testpaths = ["tests"]
""")
    _write(root, "app/main.py", """
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Document(BaseModel):
    doc_id: str
    text: str

@app.post("/ingest")
def ingest(doc: Document):
    return {"ok": True}
""")
    _write(root, "app/parser.py", "def parse(text):\n    return text\n")
    _write(root, "tests/test_main.py", "def test_ok():\n    assert True\n")


def _make_cli_project(root: Path) -> None:
    _write(root, "pyproject.toml", """
[project]
name = "my-cli"
dependencies = ["click"]

[project.scripts]
mycli = "my_cli.main:cli"
""")
    _write(root, "src/my_cli/__init__.py", "")
    _write(root, "src/my_cli/main.py", "import click\n\n@click.command()\ndef cli():\n    pass\n")
    _write(root, "src/my_cli/__main__.py", "from my_cli.main import cli\ncli()\n")


def _make_plain_package(root: Path) -> None:
    _write(root, "requirements.txt", "requests>=2.0\npyyaml\n# comment\n")
    _write(root, "mylib/__init__.py", "")
    _write(root, "mylib/loader.py", """
from dataclasses import dataclass

@dataclass
class Record:
    key: str
""")


# ---- 三类项目(§十五) ----


def test_fastapi_project_detected_with_facts(tmp_path: Path) -> None:
    _make_fastapi_project(tmp_path)
    r = analyze_host_project(tmp_path)
    assert r.project_type.value == "service" and r.project_type.provenance == INFERENCE
    assert r.python_version.value == ">=3.11" and r.python_version.provenance == FACT
    assert r.test_command.value == "pytest" and r.test_command.provenance == FACT
    assert "fastapi" in r.dependencies and "pydantic" in r.dependencies
    assert any(f.value == "fastapi" and f.provenance == FACT for f in r.frameworks)
    assert any("Document (pydantic)" in str(s.value) for s in r.schemas)
    # parser.py 命中集成点启发式;schema 文件也入候选
    files = {c.file for c in r.integration_candidates}
    assert any("parser.py" in f for f in files)
    assert "pyproject.toml" in r.protected_paths and "tests/" in r.protected_paths


def test_cli_project_detected(tmp_path: Path) -> None:
    _make_cli_project(tmp_path)
    r = analyze_host_project(tmp_path)
    assert r.project_type.value == "cli"
    assert any("mycli = my_cli.main:cli" in str(e.value) and e.provenance == FACT
               for e in r.entry_points)
    assert any("python -m my_cli" in str(e.value) for e in r.entry_points)
    assert r.test_command.provenance == UNKNOWN  # 无测试配置 → 不编造
    assert any("测试配置" in x for x in r.risks)


def test_plain_package_detected(tmp_path: Path) -> None:
    _make_plain_package(tmp_path)
    r = analyze_host_project(tmp_path)
    assert r.package_manager.value == "pip" and r.package_manager.provenance == FACT
    assert r.dependencies == ["pyyaml", "requests"]  # 注释行被忽略,排序去重
    assert r.python_version.provenance == UNKNOWN
    assert any("loader.py" in c.file for c in r.integration_candidates)
    assert any("@dataclass" in str(s.value) for s in r.schemas)


# ---- 诚实性:不编造 ----


def test_empty_directory_yields_blank_mode_not_fabrications(tmp_path: Path) -> None:
    """RFC-008 §4.2 修订:真正的空目录不再是一串 UNKNOWN,而是显式
    BLANK_PROJECT 模式(这本身是事实,不是编造);代码相关字段仍然
    如实 UNKNOWN,回归标记为 N/A。"""
    r = analyze_host_project(tmp_path)
    assert r.host_mode.value == "BLANK_PROJECT" and r.host_mode.provenance == "FACT"
    assert r.project_type.value == "blank" and r.project_type.provenance == "FACT"
    assert r.python_version.provenance == UNKNOWN
    assert r.package_manager.provenance == UNKNOWN
    assert r.test_command.provenance == UNKNOWN and "N/A" in r.test_command.evidence
    assert r.dependencies == [] and r.frameworks == [] and r.schemas == []
    assert r.integration_candidates == []


def test_missing_path_reported_honestly(tmp_path: Path) -> None:
    r = analyze_host_project(tmp_path / "no-such-dir")
    assert r.project_type.provenance == UNKNOWN
    assert any("不存在" in x for x in r.risks)


def test_every_fact_carries_evidence(tmp_path: Path) -> None:
    _make_fastapi_project(tmp_path)
    r = analyze_host_project(tmp_path)
    findings = [r.project_type, r.python_version, r.package_manager, r.test_command,
                *r.entry_points, *r.frameworks, *r.schemas]
    for f in findings:
        if f.provenance == FACT:
            assert f.evidence, f"FACT without evidence: {f}"


# ---- 安全性:setup.py 永不执行、纯只读 ----


def test_setup_py_is_parsed_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "EXECUTED_MARKER"
    _write(tmp_path, "setup.py", f"""
import pathlib
pathlib.Path({str(marker)!r}).write_text("boom")
install_requires=["numpy", "requests>=2"]
""")
    r = analyze_host_project(tmp_path)
    assert not marker.exists(), "setup.py was EXECUTED — forbidden"
    assert "numpy" in r.dependencies and "requests" in r.dependencies
    assert "未执行" in r.dependencies_evidence


def test_analysis_is_read_only(tmp_path: Path) -> None:
    _make_plain_package(tmp_path)
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    snapshot = {p: (tmp_path / p).read_bytes() for p in before if (tmp_path / p).is_file()}
    analyze_host_project(tmp_path)
    after = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert after == before
    for p, data in snapshot.items():
        assert (tmp_path / p).read_bytes() == data


def test_analyzer_module_has_no_llm_docker_or_write_calls() -> None:
    src = (REPO / "src" / "repoproof" / "adoption" / "analysis" / "host_analyzer.py").read_text()
    for banned in ("litellm", "openai", "docker", "subprocess", "write_text(", "write_bytes(",
                   "shutil", "urllib", "requests.", "socket"):
        assert banned not in src, banned


def test_host_git_module_is_readonly_queries_only() -> None:
    """RFC-008:git 只读查询集中在 host_git.py——允许 subprocess,
    但仅限 rev-parse/status;禁写、禁网络、禁 LLM、禁容器;任何
    写型 git 子命令不得作为 argv 字面量出现。"""
    src = (REPO / "src" / "repoproof" / "adoption" / "analysis" / "host_git.py").read_text()
    for banned in ("litellm", "openai", "write_text(", "write_bytes(",
                   "shutil", "urllib", "requests.", "socket",
                   '"checkout"', '"reset"', '"clean"', '"push"', '"commit"',
                   '"stash"', '"add"', '"merge"', '"rebase"'):
        assert banned not in src, banned
    assert "rev-parse" in src and "--porcelain" in src


# ---- 扫描边界:大项目诚实降级 ----


def test_truncation_is_disclosed(tmp_path: Path) -> None:
    for i in range(MAX_PY_FILES + 20):
        _write(tmp_path, f"pkg/m_{i:04d}.py", "x = 1\n")
    r = analyze_host_project(tmp_path)
    assert r.scan_stats.truncated is True
    assert r.scan_stats.py_files_scanned == MAX_PY_FILES
    assert any("不完整" in x for x in r.risks)


# ---- 自测:对 RepoProof 自身 ----


def test_self_analysis_on_repoproof() -> None:
    r = analyze_host_project(REPO)
    assert r.python_version.provenance == FACT  # pyproject requires-python
    assert r.test_command.value == "pytest"
    assert "pydantic" in r.dependencies
    assert r.to_dict()["project_path"] == str(REPO)
