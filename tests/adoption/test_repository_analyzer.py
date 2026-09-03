"""Guided Adoption Phase 2 — Repository Analyzer(RFC-002)。

§十五:有 pyproject / 无 pyproject / 需要 GPU / 需要 secret;
外加:license/quickstart/public api/不执行保证/URL 校验/
对本地 pinned python-frontmatter 真仓库自测。全部零网络。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from repoproof.adoption.admission.admission_report import decide_tool
from repoproof.adoption.analysis.host_analyzer import FACT, INFERENCE, UNKNOWN
from repoproof.adoption.analysis.repository_analyzer import (
    analyze_repository_dir,
    clone_for_analysis,
)

REPO = Path(__file__).resolve().parents[2]
PINNED_FM = REPO / "upstream-cache" / "upstream-dc7c0af5466b"


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _make_repo_with_pyproject(root: Path) -> None:
    _write(root, "pyproject.toml", """
[build-system]
requires = ["setuptools"]

[project]
name = "textlib"
requires-python = ">=3.10"
dependencies = ["pyyaml>=6"]

[project.scripts]
textlib = "textlib.cli:main"
""")
    _write(root, "LICENSE", "MIT License\n\nCopyright (c) 2026")
    _write(root, "README.md", "# textlib\n\n```python\nimport textlib\ntextlib.parse('x')\n```\n")
    _write(root, "textlib/__init__.py", '__all__ = ["parse", "Splitter"]\n')
    _write(root, "textlib/core.py", "def parse(t):\n    return t\n")
    _write(root, "tests/test_core.py", "def test_ok():\n    assert True\n")


# ---- §十五 四类 ----


def test_repo_with_pyproject(tmp_path: Path) -> None:
    _make_repo_with_pyproject(tmp_path)
    r = analyze_repository_dir(tmp_path)
    assert r.license.value == "MIT" and r.license.provenance == FACT
    assert r.python_version.value == ">=3.10" and r.python_version.provenance == FACT
    assert "pip install" in str(r.install_method.value) and r.install_method.provenance == FACT
    assert r.dependencies == ["pyyaml"]
    assert any(f.value == "parse" and "__all__" in f.evidence for f in r.public_api)
    assert any("textlib = textlib.cli:main" in str(e.value) for e in r.cli_entry_points)
    assert "import textlib" in str(r.quickstart.value) and r.quickstart.provenance == FACT
    assert "1 个测试文件" in str(r.tests.value)
    assert r.runtime == {"python": True, "gpu": False, "external_api": False}
    assert any(c.name == "parse" for c in r.capability_candidates)
    assert r.commit.provenance == UNKNOWN  # 非 git 目录,如实说明
    assert any("无法固定版本" in x for x in r.risks)


def test_repo_without_pyproject(tmp_path: Path) -> None:
    _write(tmp_path, "mylib/__init__.py", "def run():\n    pass\n")
    _write(tmp_path, "README.md", "# mylib\n")
    r = analyze_repository_dir(tmp_path)
    assert r.python_version.provenance == UNKNOWN
    assert r.install_method.provenance == INFERENCE  # 源码复制推断
    assert any("安装方式需要人工确认" in x for x in r.risks)
    assert any("许可证" in x for x in r.risks)  # 无 LICENSE → 风险
    assert r.quickstart.provenance == INFERENCE  # README 无代码块


def test_repo_requiring_gpu(tmp_path: Path) -> None:
    _write(tmp_path, "requirements.txt", "torch>=2.0\nnumpy\n")
    _write(tmp_path, "README.md", "Requires CUDA 12.\n")
    r = analyze_repository_dir(tmp_path)
    assert r.gpu.value is True and r.gpu.provenance == FACT
    assert "torch" in r.gpu.evidence
    assert r.runtime["gpu"] is True
    assert any("GPU" in x and "超出" in x for x in r.risks)


def test_repo_requiring_secret(tmp_path: Path) -> None:
    _write(tmp_path, "svc/client.py",
           'import os\nKEY = os.environ["OPENAI_API_KEY"]\nT = os.getenv("HF_TOKEN")\n')
    _write(tmp_path, "requirements.txt", "openai\n")
    r = analyze_repository_dir(tmp_path)
    names = {str(s.value) for s in r.secrets_required}
    optional_names = {str(s.value) for s in r.secrets_optional}
    assert names == {"OPENAI_API_KEY"}
    assert optional_names == {"HF_TOKEN"}
    assert all(s.provenance == FACT and s.evidence for s in r.secrets_required)
    assert r.runtime["external_api"] is True
    assert any("secret" in x for x in r.risks)
    assert any("外部服务" in x for x in r.risks)


def test_optional_credential_lookup_is_reviewed_not_blocked(tmp_path: Path) -> None:
    _make_repo_with_pyproject(tmp_path)
    _write(
        tmp_path,
        "textlib/settings.py",
        'import os\nOPTIONAL = os.environ.get("ANALYTICS_TOKEN")\n',
    )
    for args in (
        ["init", "-q"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "pin"],
    ):
        subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
        )

    report = analyze_repository_dir(tmp_path)
    admission = decide_tool(report)

    assert report.secrets_required == []
    assert {str(item.value) for item in report.secrets_optional} == {
        "ANALYTICS_TOKEN"
    }
    assert admission.status == "RISK_REVIEW"
    assert not admission.blockers
    assert any("无凭证" in item for item in admission.risks)


# ---- 安全与诚实 ----


def test_repo_code_is_never_executed(tmp_path: Path) -> None:
    marker = tmp_path / "EXECUTED"
    _write(tmp_path, "setup.py", f"import pathlib; pathlib.Path({str(marker)!r}).write_text('x')")
    _write(tmp_path, "evil/__init__.py", f"import pathlib; pathlib.Path({str(marker)!r}).write_text('x')")
    analyze_repository_dir(tmp_path)
    assert not marker.exists(), "repository code was EXECUTED — forbidden"


def test_clone_rejects_non_github_urls(tmp_path: Path) -> None:
    for bad in ("https://gitlab.com/a/b", "git@github.com:a/b.git", "ftp://x", "not-a-url"):
        dest, err = clone_for_analysis(bad, None, tmp_path)
        assert dest is None and "GitHub" in err


def test_clone_fetches_exact_commit_instead_of_treating_it_as_a_branch(
        tmp_path: Path, monkeypatch) -> None:
    """完整 commit 必须走 fetch + detached checkout，不能传给 clone --branch。"""
    commit = "d98bdb70fbde4d08e191df17bd51576102c19d6a"
    calls: list[list[str]] = []
    timeouts: list[int | None] = []

    def _git(cmd, **_kwargs):
        calls.append(list(cmd))
        timeouts.append(_kwargs.get("timeout"))
        if cmd[:3] == ["git", "init", "--quiet"]:
            (Path(cmd[3]) / ".git").mkdir()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", _git)
    dest, err = clone_for_analysis(
        "https://github.com/weiwei/junitparser", commit, tmp_path)

    assert err == "" and dest is not None and (dest / ".git").is_dir()
    assert not any("--branch" in cmd for cmd in calls)
    fetch = next(cmd for cmd in calls if "fetch" in cmd)
    assert fetch[-1] == commit
    checkout = next(cmd for cmd in calls if "checkout" in cmd)
    assert checkout[-2:] == ["--quiet", "FETCH_HEAD"]
    assert timeouts == [300, 300, 300, 300]


def test_unknown_fields_never_fabricated(tmp_path: Path) -> None:
    r = analyze_repository_dir(tmp_path)  # 空目录
    for f in (r.license, r.python_version, r.quickstart, r.tests, r.commit):
        assert f.provenance == UNKNOWN
    assert r.dependencies == [] and r.public_api == [] and r.capability_candidates == []


def test_analyzer_module_static_bans() -> None:
    src = (REPO / "src/repoproof/adoption/analysis/repository_analyzer.py").read_text()
    for banned in ("litellm", "openai.", "docker", "importlib", "exec(", "eval(",
                   "os.system", '"pip",', "'pip',"):
        assert banned not in src, banned
    # subprocess 只允许 git 用途:恰好三处调用；checkout 命令也全部显式以 git 开头。
    assert src.count("subprocess.run") == 3
    assert '["git", "init"' in src
    assert '["git", "-C", str(repo), "rev-parse"' in src
    assert '["git", "ls-remote"' in src


# ---- 真实仓库自测(本地 pinned 快照,零网络) ----


def test_real_repo_pinned_python_frontmatter() -> None:
    if not PINNED_FM.exists():
        import pytest

        pytest.skip("pinned upstream cache not present")
    r = analyze_repository_dir(PINNED_FM, url="https://github.com/eyeseast/python-frontmatter")
    assert r.commit.provenance == FACT
    assert str(r.commit.value).startswith("dc7c0af5")
    assert r.license.value == "MIT"
    assert "pyyaml" in r.dependencies
    assert r.runtime["gpu"] is False
    assert r.tests.provenance == FACT
    assert r.to_dict()["repository"].endswith("python-frontmatter")


def test_sort_release_tags_version_order() -> None:
    """歧义修复(用户实测):分析快照 commit 被误当版本推荐。Tag 推荐
    必须按语义版本降序,v 前缀可解析,无法解析的字符串沉底。"""
    from repoproof.adoption.analysis.repository_analyzer import sort_release_tags

    out = sort_release_tags(["0.4.0", "v0.10.0", "0.5.1", "weird-tag", "0.5.0"])
    assert out == ["v0.10.0", "0.5.1", "0.5.0", "0.4.0", "weird-tag"]


# ---- 必需式密钥 = 可执行读取,而非文本出现
# (incident-admission-secret-scan-misclassification-v1) ----
#
# 不变量:
# I1 secrets_required 只能来自可执行代码里的 environ 下标读取;
#    字符串字面量(代码生成模板/文档示例)不是运行时需求。
# I2 对 environ 的赋值/删除是"提供",不是"要求"。
# I3 密钥扫描必须确定性覆盖整个 Python 树,不受通用扫描文件数上限
#    截断影响 —— 截断既造成假阳(按字母序扫到哪算哪),也造成假阴
#    (上限之后的真实密钥需求被静默漏掉)。
# I4 上游自身 tests/docs/examples 区读密钥不构成被采纳能力的运行时
#    需求;单独入账,不静默丢弃。


def test_secret_name_inside_string_literal_is_not_required(tmp_path: Path) -> None:
    _write(tmp_path, "gen/emit.py",
           "TEMPLATE = [\n"
           "    '    password=os.environ[\"DB_PASSWORD\"],',\n"
           "]\n")
    r = analyze_repository_dir(tmp_path)
    assert {str(s.value) for s in r.secrets_required} == set()


def test_secret_env_assignment_is_not_required(tmp_path: Path) -> None:
    _write(tmp_path, "svc/setup_env.py",
           'import os\nos.environ["EXPORT_TOKEN"] = "value"\n')
    r = analyze_repository_dir(tmp_path)
    assert "EXPORT_TOKEN" not in {str(s.value) for s in r.secrets_required}
    assert "EXPORT_TOKEN" not in {str(s.value) for s in r.secrets_optional}


def test_readme_secret_mention_is_not_required(tmp_path: Path) -> None:
    _write(tmp_path, "README.md",
           '# demo\n\n```python\nimport os\nk = os.environ["DOC_ONLY_KEY"]\n```\n')
    r = analyze_repository_dir(tmp_path)
    assert "DOC_ONLY_KEY" not in {str(s.value) for s in r.secrets_required}
    # 文档提及仍要可见:进可选/风险面,不静默消失。
    assert "DOC_ONLY_KEY" in {str(s.value) for s in r.secrets_optional}


def test_secret_scan_is_not_truncated_by_generic_file_cap(tmp_path: Path) -> None:
    from repoproof.adoption.analysis.host_analyzer import MAX_PY_FILES

    for i in range(MAX_PY_FILES):
        _write(tmp_path, f"pkg/a_{i:04d}.py", "X = 1\n")
    _write(tmp_path, "pkg/zz_late.py",
           'import os\nK = os.environ["LATE_API_KEY"]\n')
    r = analyze_repository_dir(tmp_path)
    assert "LATE_API_KEY" in {str(s.value) for s in r.secrets_required}


def test_upstream_test_zone_secret_read_is_not_runtime_required(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/core.py", "def run():\n    return 1\n")
    _write(tmp_path, "tests/test_env.py",
           'import os\nK = os.environ["SUITE_ONLY_KEY"]\n')
    r = analyze_repository_dir(tmp_path)
    assert "SUITE_ONLY_KEY" not in {str(s.value) for s in r.secrets_required}
    assert "SUITE_ONLY_KEY" in {str(s.value) for s in r.secrets_test_zone}


def test_executable_lib_secret_read_still_required_via_alias_forms(tmp_path: Path) -> None:
    """正控:闸门不降。真实读取(含 from os import environ 别名形态)仍必须命中。"""
    _write(tmp_path, "svc/a.py", 'import os\nK = os.environ["ALPHA_API_KEY"]\n')
    _write(tmp_path, "svc/b.py", 'from os import environ\nT = environ["BETA_TOKEN"]\n')
    r = analyze_repository_dir(tmp_path)
    names = {str(s.value) for s in r.secrets_required}
    assert {"ALPHA_API_KEY", "BETA_TOKEN"} <= names


def test_wsgi_style_foreign_environ_is_not_a_secret_requirement(tmp_path: Path) -> None:
    """非 os.environ 的同名对象(WSGI environ 参数)不是进程环境密钥。"""
    _write(tmp_path, "web/app.py",
           "def app(environ, start_response):\n"
           '    k = environ["HTTP_X_API_KEY"]\n'
           "    return k\n")
    r = analyze_repository_dir(tmp_path)
    assert "HTTP_X_API_KEY" not in {str(s.value) for s in r.secrets_required}
