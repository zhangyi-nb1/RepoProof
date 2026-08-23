"""LOCAL-TOOL intake 的钉死(M2-a · RFC-010 [G1] 确定性骨架)。

- 单仓 admission(decide_tool)按纪律喂违反自证:GPU/commit/secret 各
  自触发 UNSUPPORTED,无入口触发 NEED_INFORMATION,全好 READY;
- 草稿只填推导得出的,推导不出必须进缺口(不许似是而非) —— 合成仓
  验落位,拆件仓验缺口;
- 真 pdfplumber 钉版树(盘上 upstream-cache)做集成:确定性提取质量
  的真实锚(资源不在则 skip,复活入口写明)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repoproof.adoption.admission.admission_report import decide_tool
from repoproof.adoption.analysis.repository_analyzer import Finding, RepositoryReport
from repoproof.adoption.intake.tool_intake import (
    build_draft,
    extract_distribution,
    extract_import_module,
    run_tool_intake,
)

REPO = Path(__file__).resolve().parents[1]
PDFPLUMBER = REPO / "upstream-cache" / "upstream-7d4f2f582f2d"


def _mini_repo(tmp: Path, *, src_layout: bool = True, name: str = "acme-lib") -> Path:
    root = tmp / "repo"
    pkg_parent = (root / "src") if src_layout else root
    pkg = pkg_parent / name.replace("-", "_")
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("def run(x):\n    return x\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n'
        'requires-python = ">=3.10"\ndependencies = []\n'
        "[build-system]\nrequires = [\"setuptools\"]\n"
        'build-backend = "setuptools.build_meta"\n', encoding="utf-8")
    (root / "LICENSE").write_text("MIT License\n\nPermission is hereby granted...",
                                  encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n",
                                              encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1"]):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True)
    return root


# ------------------------------------------------------------ 确定性提取

def test_extract_distribution_and_module_src_layout(tmp_path):
    root = _mini_repo(tmp_path)
    dist, ev = extract_distribution(root)
    assert dist == "acme-lib" and "pyproject" in ev
    mod, ev2 = extract_import_module(root, dist)
    assert mod == "acme_lib" and "src 布局" in ev2


def test_extract_module_flat_layout_unique_package(tmp_path):
    root = _mini_repo(tmp_path, src_layout=False)
    assert extract_import_module(root, "acme-lib")[0] == "acme_lib"


def test_extract_refuses_to_guess(tmp_path):
    """推导不出 = 空 + 原因;绝不返回似是而非的值。"""
    bare = tmp_path / "bare"
    bare.mkdir()
    dist, ev = extract_distribution(bare)
    assert dist == "" and ev
    mod, ev2 = extract_import_module(bare, "")
    assert mod == "" and ev2


# --------------------------------------------- admission 单仓口径:喂违反

def _repo_report(**over) -> RepositoryReport:
    base = dict(
        repository="https://github.com/a/b",
        is_public=Finding.fact(True, "clone ok"),
        commit=Finding.fact("deadbeef" * 5, "git rev-parse HEAD"),
        license=Finding.fact("MIT", "LICENSE"),
        python_version=Finding.fact(">=3.10", "pyproject"),
        install_method=Finding.fact("pip", "pyproject build-system"),
        gpu=Finding.fact(False, "未发现 GPU 依赖"),
        tests=Finding.fact("tests/", "目录存在"),
        public_api=[Finding.fact("b.run", "__init__")],
    )
    base.update(over)
    return RepositoryReport(**base)


def test_decide_tool_ready_when_all_good():
    assert decide_tool(_repo_report()).status == "READY"


def test_decide_tool_gpu_is_unsupported():
    r = decide_tool(_repo_report(gpu=Finding.fact(True, "requirements: torch")))
    assert r.status == "UNSUPPORTED" and any("GPU" in b for b in r.blockers)


def test_decide_tool_unpinnable_commit_is_unsupported():
    r = decide_tool(_repo_report(commit=Finding.unknown("非 git 仓库")))
    assert r.status == "UNSUPPORTED" and any("固定" in b for b in r.blockers)


def test_decide_tool_secrets_are_unsupported():
    r = decide_tool(_repo_report(
        secrets_required=[Finding.fact("OPENAI_API_KEY", "os.environ 引用")]))
    assert r.status == "UNSUPPORTED" and any("密钥" in b for b in r.blockers)


def test_decide_tool_no_entrypoint_needs_information():
    r = decide_tool(_repo_report(public_api=[]))
    assert r.status == "NEED_INFORMATION"
    assert any("入口" in q for q in r.questions)


def test_decide_tool_external_services_is_risk_review():
    r = decide_tool(_repo_report(
        external_services=Finding.fact(["requests"], "import 扫描")))
    assert r.status == "RISK_REVIEW" and any("外部服务" in x for x in r.risks)


# ------------------------------------------------------------ 草稿与缺口

def test_intake_draft_fills_deterministic_fields(tmp_path):
    root = _mini_repo(tmp_path)
    rep = run_tool_intake("https://github.com/a/acme-lib", "把 run 能力做成工具",
                          cache_root=tmp_path / "cache", local_path=root)
    d = rep.draft
    assert d["source_repo"]["distribution"] == "acme-lib"
    assert d["source_repo"]["import_module"] == "acme_lib"
    assert len(d["source_repo"]["resolved_commit"]) == 40
    assert d["source_repo"]["license"] == "MIT"
    assert d["task_family"] == "LOCAL-TOOL"
    assert d["tool"]["name"] == "acme-lib"
    assert d["tool"]["interface"]["exit_codes"] == {
        "0": "success", "1": "user_error", "2": "internal_error"}
    assert d["_draft"]["status"] == "DRAFT"


def test_intake_gaps_route_truth_to_user_and_prose_to_llm(tmp_path):
    """[G1] 分派:验收真值(样例)归 USER,措辞(statement/summary)归 LLM。"""
    root = _mini_repo(tmp_path)
    rep = run_tool_intake("", "g", cache_root=tmp_path / "cache", local_path=root)
    owner = {g.field: g.owner for g in rep.draft_gaps}
    assert owner["examples"] == "USER"
    assert owner["capability.statement"] == "LLM"
    assert owner["tool.summary"] == "LLM"
    assert owner["reference_impl"] == "LLM"
    assert owner["reference_lock"] == "AUTO"
    # 草稿里这些字段必须是空,不许预填似是而非的值
    assert rep.draft["capability"]["statement"] == ""
    assert rep.draft["tool"]["summary"] == ""


def test_intake_missing_metadata_becomes_user_gaps(tmp_path):
    """拆件仓(无 pyproject name):distribution/import_module 进 USER 缺口。"""
    root = tmp_path / "repo"
    (root / "stuff").mkdir(parents=True)
    (root / "stuff" / "x.py").write_text("pass\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True,
                   capture_output=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-qm", "v"], check=True,
                   capture_output=True)
    rep = run_tool_intake("", "g", cache_root=tmp_path / "cache", local_path=root)
    fields = {g.field for g in rep.draft_gaps if g.owner == "USER"}
    assert {"source_repo.distribution", "source_repo.import_module"} <= fields
    assert rep.draft["source_repo"]["distribution"] == ""


# ---------------------------------------------------- 真仓集成(资源护栏)

@pytest.mark.skipif(not PDFPLUMBER.is_dir(),
                    reason="pdfplumber 钉版树不在本机(upstream-cache 已清理);"
                           "git clone jsvine/pdfplumber@v0.11.10 后可跑")
def test_intake_on_real_pdfplumber_tree():
    rep = run_tool_intake("https://github.com/jsvine/pdfplumber",
                          "PDF 表格提取为 Markdown",
                          cache_root=Path("/tmp/rp-intake-cache"),
                          local_path=PDFPLUMBER)
    assert rep.admission.status != "UNSUPPORTED", rep.admission.blockers
    d = rep.draft["source_repo"]
    assert d["distribution"] == "pdfplumber"
    assert d["import_module"] == "pdfplumber"
    assert d["resolved_commit"].startswith("7d4f2f58")
    assert d["license"] == "MIT"
    assert rep.draft["tool"]["name"] == "pdfplumber"   # 建议名;最终归 USER
