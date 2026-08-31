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


def test_extract_module_uses_real_dirname_not_case_variant(tmp_path):
    """M4 Unidecode 实测:APFS 大小写不敏感,'Unidecode' 能命中 unidecode/
    —— 必须回读真实目录名,否则 Linux 上 import 大写名必炸。"""
    root = tmp_path / "repo"
    (root / "unidecode").mkdir(parents=True)
    (root / "unidecode" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    mod, ev = extract_import_module(root, "Unidecode")
    assert mod == "unidecode", f"必须是真实目录名,得到 {mod!r}"
    assert "真实目录名" in ev


def test_extract_setup_py_title_indirection(tmp_path):
    """M4 slugify 实测形态:name=about['__title__'],字面量在包内 __version__。"""
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    (root / "setup.py").write_text(
        "about = {}\nwith open('pkg/__version__.py') as f:\n"
        "    exec(f.read(), about)\nsetup(name=about['__title__'])\n",
        encoding="utf-8")
    (root / "pkg" / "__version__.py").write_text(
        '__title__ = "python-acme"\n__version__ = "1.0"\n', encoding="utf-8")
    dist, ev = extract_distribution(root)
    assert dist == "python-acme" and "__title__" in ev


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


def test_suggested_name_always_suffixed_against_dist_collision():
    """M4 slugify 实测定稿:kebab(distribution) 规范化恒 ≡ distribution
    规范化 → 直接用库名当工具名必然 pip 同名互顶;建议名恒加 -tool。"""
    from repoproof.adoption.intake.tool_intake import _suggest_tool_name

    assert _suggest_tool_name("g", "minilib", "minilib") == "minilib-tool"
    assert _suggest_tool_name("g", "python-slugify", "slugify") \
        == "python-slugify-tool"
    assert _suggest_tool_name("g", "python-markdownify", "markdownify") \
        == "python-markdownify-tool"


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


def test_intake_rejects_credentialled_irreversible_intent_before_repository_access(
    tmp_path, monkeypatch
):
    """Explicit high-risk intent is a zero-repository, zero-Agent safety stop."""

    def forbidden_repository_access(*_args, **_kwargs):
        raise AssertionError("repository access must not occur for rejected intent")

    monkeypatch.setattr(
        "repoproof.adoption.intake.tool_intake.clone_for_analysis",
        forbidden_repository_access,
    )
    report = run_tool_intake(
        "https://example.invalid/public-source",
        "Authenticate to a private account and complete an irreversible external transaction.",
        cache_root=tmp_path / "cache",
        revision="v1",
    )

    assert report.admission.status == "UNSUPPORTED"
    assert report.admission.executes_third_party_code is False
    assert report.admission.reason_codes == [
        "UNSUPPORTED_CREDENTIALLED_EXTERNAL_SIDE_EFFECT"
    ]
    assert report.draft == {}


@pytest.mark.parametrize(
    ("goal", "reason_code"),
    [
        (
            "从在线 API 下载最新记录并生成本地报告。",
            "UNSUPPORTED_RUNTIME_NETWORK_REQUIRED",
        ),
        (
            "持续监控本地实验目录，有新文件就生成摘要。",
            "UNSUPPORTED_LONG_RUNNING_LIFECYCLE",
        ),
        (
            "把生成的报告上传到云盘，之后允许我删除。",
            "UNSUPPORTED_REVERSIBLE_EXTERNAL_SIDE_EFFECT",
        ),
    ],
)
def test_explicit_delivery_topology_stops_before_repository_access(
    tmp_path, monkeypatch, goal: str, reason_code: str
) -> None:
    def forbidden_repository_access(*_args, **_kwargs):
        raise AssertionError("repository access must not occur for rejected intent")

    monkeypatch.setattr(
        "repoproof.adoption.intake.tool_intake.clone_for_analysis",
        forbidden_repository_access,
    )
    report = run_tool_intake(
        "https://example.invalid/public-source",
        goal,
        cache_root=tmp_path / "cache",
        revision="v1",
    )

    assert report.admission.status == "UNSUPPORTED"
    assert report.admission.reason_codes == [reason_code]
    assert report.draft == {}


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
    assert d["tool"]["name"] == "acme-lib-tool"   # 避撞:acme_lib==import 名
    assert d["tool"]["schema_version"] == 3
    assert d["tool"]["interface"]["output"]["contract"] == {}
    assert d["_delivery_profile"] == {
        "schema_version": 1,
        "profile_id": "cli_v2",
    }
    assert d["tool"]["interface"]["exit_codes"] == {
        "0": "success", "1": "user_error", "2": "internal_error"}
    assert d["_draft"]["status"] == "DRAFT"


def test_intake_preserves_user_requested_revision(tmp_path):
    root = _mini_repo(tmp_path)
    rep = run_tool_intake(
        "https://github.com/a/acme-lib",
        "把 run 能力做成工具",
        cache_root=tmp_path / "cache",
        revision="v1.2.3",
        local_path=root,
    )
    assert rep.repo.requested_revision == "v1.2.3"
    assert rep.draft["source_repo"]["revision"] == "v1.2.3"


def test_intake_gaps_route_truth_to_user_and_prose_to_llm(tmp_path):
    """[G1] 分派:验收真值(样例)归 USER,措辞(statement/summary)归 LLM。"""
    root = _mini_repo(tmp_path)
    rep = run_tool_intake("", "g", cache_root=tmp_path / "cache", local_path=root)
    owner = {g.field: g.owner for g in rep.draft_gaps}
    assert owner["examples"] == "USER"
    assert owner["capability.statement"] == "LLM"
    assert owner["tool.summary"] == "LLM"
    assert owner["tool.interface.output.contract"] == "LLM"
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

@pytest.mark.skipif(not (PDFPLUMBER / ".git").exists(),
                    reason="pdfplumber 钉版树(含 .git)不在本机;资源门查 .git"
                           " 而非裸目录 —— 树在而 .git 不在时 rev-parse 会向上"
                           "漂到外层仓,给出误导性失败(容器预演实测)。"
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
    assert rep.draft["tool"]["name"] == "pdfplumber-tool"   # 避撞建议;最终归 USER
