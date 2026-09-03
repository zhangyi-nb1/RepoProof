"""上游一致性选取器的钉死(M2-e · G2 第二层)。

选取必须确定性、命中为准、不硬凑;真 pdfplumber 树做集成锚(资源护栏)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repoproof.adoption.intake.upstream_conformance import (
    UpstreamConformanceError,
    precheck_upstream_conformance,
    reference_upstream_symbols,
    select_upstream_test_nodes,
)

REPO = Path(__file__).resolve().parents[1]
PDFPLUMBER = REPO / "upstream-cache" / "upstream-7d4f2f582f2d"


def _up(tmp: Path) -> Path:
    root = tmp / "up"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_table_extract.py").write_text(
        "def test_table_basic():\n    pass\n\n"
        "def test_table_nested():\n    pass\n", encoding="utf-8")
    (root / "tests" / "test_misc.py").write_text(
        "def test_other():\n    pass\n", encoding="utf-8")
    (root / "tests" / "test_render.py").write_text(
        "def test_render_table():\n    pass\n", encoding="utf-8")
    return root


def test_reference_symbols_follow_import_structure_not_prose() -> None:
    source = '''"""Arbitrary words: report PDF title author."""
import acme as lib
from acme.tools import convert
import unrelated

def extract(path):
    return lib.load(path), convert(path), unrelated.load(path)
'''

    assert reference_upstream_symbols(source, import_module="acme") == [
        "load",
        "tools.convert",
    ]
    rewritten = source.replace(
        "Arbitrary words: report PDF title author.",
        "完全不同的自然语言需求，不含任何原词。",
    )
    assert reference_upstream_symbols(
        rewritten,
        import_module="acme",
    ) == ["load", "tools.convert"]


def test_reference_symbols_keep_relative_qualifiers_to_avoid_ambiguous_calls() -> None:
    source = """import acme.tools as api
from acme.deep.helpers import convert

def extract(path):
    return api.load(path), convert(path)
"""

    assert reference_upstream_symbols(source, import_module="acme") == [
        "tools.load",
        "deep.helpers.convert",
    ]


def test_qualified_symbol_excludes_unrelated_terminal_name_matches(tmp_path) -> None:
    root = _up(tmp_path)
    (root / "tests" / "test_seqio.py").write_text(
        "def test_parse_reads():\n    SeqIO.parse('reads.fastq')\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_ace.py").write_text(
        "def test_parse_assembly():\n    Ace.parse('assembly.ace')\n",
        encoding="utf-8",
    )

    assert select_upstream_test_nodes(root, ["SeqIO.parse"]) == [
        "tests/test_seqio.py::test_parse_reads"
    ]


def test_selection_ranks_by_exact_ast_identifiers_and_is_deterministic(tmp_path):
    root = _up(tmp_path)
    got = select_upstream_test_nodes(root, ["table"])
    assert got == [
        "tests/test_render.py::test_render_table",
        "tests/test_table_extract.py::test_table_basic",
        "tests/test_table_extract.py::test_table_nested",
    ]
    assert select_upstream_test_nodes(root, ["table"]) == got


def test_selection_caps_and_empty_cases(tmp_path):
    root = _up(tmp_path)
    assert select_upstream_test_nodes(root, ["table"], max_nodes=1) == [
        "tests/test_render.py::test_render_table"
    ]
    assert select_upstream_test_nodes(root, ["zzz"]) == []
    assert select_upstream_test_nodes(root, []) == []
    assert select_upstream_test_nodes(tmp_path / "none", ["table"]) == []


def test_short_symbol_requires_executable_ast_match_and_skips_async_nodes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "up"
    tests = root / "tests"
    tests.mkdir(parents=True)
    (tests / "test_short.py").write_text(
        "def test_feature_on_basic():\n"
        "    pass\n\n"
        "def test_fixture_backed_use(custom_fixture):\n"
        "    on(custom_fixture)\n\n"
        "async def test_real_async_use():\n"
        "    on('event')\n\n"
        "def test_real_sync_use():\n"
        "    on('event')\n",
        encoding="utf-8",
    )

    assert select_upstream_test_nodes(root, ["on"]) == [
        "tests/test_short.py::test_real_sync_use",
        "tests/test_short.py::test_fixture_backed_use",
    ]


def test_selection_preserves_actual_test_directory_case(tmp_path) -> None:
    root = tmp_path / "up"
    base = root / "Tests"
    base.mkdir(parents=True)
    (base / "test_reader.py").write_text(
        "def test_parse():\n    SeqIO.parse('reads.fastq')\n",
        encoding="utf-8",
    )

    assert select_upstream_test_nodes(root, ["SeqIO.parse"]) == [
        "Tests/test_reader.py::test_parse"
    ]


def test_node_selection_is_small_and_capability_shaped(tmp_path):
    root = _up(tmp_path)
    (root / "tests" / "test_reader.py").write_text(
        "def test_read_metadata_title():\n    pass\n\n"
        "def test_extract_text():\n    pass\n\n"
        "def test_unrelated():\n    pass\n",
        encoding="utf-8",
    )
    got = select_upstream_test_nodes(root, ["metadata", "title", "text"])
    assert got == [
        "tests/test_reader.py::test_read_metadata_title",
        "tests/test_reader.py::test_extract_text",
    ]


def test_node_selection_reads_class_method_body_and_skips_slow_marks(
    tmp_path: Path,
) -> None:
    root = _up(tmp_path)
    (root / "tests" / "test_api.py").write_text(
        "class TestAPI:\n"
        "    def test_generic_behavior(self):\n"
        "        api.read_graphml('x')\n\n"
        "    @pytest.mark.slow\n"
        "    def test_slow_behavior(self):\n"
        "        api.read_graphml('x')\n",
        encoding="utf-8",
    )

    assert select_upstream_test_nodes(root, ["read_graphml"]) == [
        "tests/test_api.py::TestAPI::test_generic_behavior"
    ]


def test_precheck_missing_dependency_is_reported_without_installing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _up(tmp_path)
    requirements = root / "requirements"
    requirements.mkdir()
    (requirements / "ci.txt").write_text(
        "pyyaml==6.0.2\nnot-pinned\n",
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    result = subprocess.CompletedProcess(
        [], 4, "", "ModuleNotFoundError: No module named 'yaml'"
    )

    def fake_run(argv, **_kwargs):
        calls.append([str(item) for item in argv])
        return result

    monkeypatch.setattr(
        "repoproof.adoption.intake.upstream_conformance.subprocess.run",
        fake_run,
    )
    with pytest.raises(UpstreamConformanceError) as caught:
        precheck_upstream_conformance(
            root,
            ["tests/test_table_extract.py::test_table_basic"],
            Path("/tmp/fake-python"),
        )

    assert caught.value.missing_module == "yaml"
    # 不变量是「缺依赖如实上报,不许 pip 自动补装」;cwd 探测允许在
    # 候选根下各试一次 pytest,但每一次都必须仍是 pytest 而非安装。
    assert 1 <= len(calls) <= 2
    for call in calls:
        assert "pip" not in call
        assert "tests/test_table_extract.py::test_table_basic" in call[-1]


def test_precheck_green_and_failing(tmp_path):
    import sys

    root = _up(tmp_path)
    rec = precheck_upstream_conformance(
        root, ["tests/test_table_extract.py"], Path(sys.executable))
    assert rec["status"] == "PASS" and rec["selected"]
    assert precheck_upstream_conformance(root, [], Path(sys.executable)) == {
        "selected": [], "status": "EMPTY"}
    (root / "tests" / "test_bad.py").write_text(
        "import nonexistent_dep_xyz\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        precheck_upstream_conformance(root, ["tests/test_bad.py"],
                                      Path(sys.executable))


def test_precheck_runs_from_real_cased_test_root_for_local_fixtures(tmp_path):
    import sys

    root = tmp_path / "up"
    tests = root / "Tests"
    tests.mkdir(parents=True)
    (tests / "sample.txt").write_text("ready", encoding="utf-8")
    (tests / "test_fixture.py").write_text(
        "def test_relative_fixture():\n"
        "    assert open('sample.txt', encoding='utf-8').read() == 'ready'\n",
        encoding="utf-8",
    )

    result = precheck_upstream_conformance(
        root,
        ["Tests/test_fixture.py::test_relative_fixture"],
        Path(sys.executable),
    )
    assert result["status"] == "PASS"


@pytest.mark.skipif(not PDFPLUMBER.is_dir(),
                    reason="pdfplumber 钉版树不在本机;clone v0.11.10 后可跑")
def test_selection_on_real_pdfplumber():
    symbols = reference_upstream_symbols(
        "import pdfplumber\npdfplumber.open('sample.pdf')\n",
        import_module="pdfplumber",
    )
    assert symbols == ["open"]
    got = select_upstream_test_nodes(PDFPLUMBER, symbols)
    assert all(node.startswith("tests/") and "::" in node for node in got)
    assert len(got) <= 3


def test_precheck_probes_repo_root_convention_for_fixture_paths(tmp_path):
    """cwd 只能探测不能猜(incident-conformance-execution-root-convention-v1)。

    另一半真实惯例:上游测试用**仓库根相对**路径引用 fixture(路径里
    自带 tests/ 前缀)。单一测试根的猜测把 cwd 定到 tests/ 下,这类
    套件必然 RepositoryNotFound 型假拦截。探测顺序确定:仓库根,再
    单一测试根;记录实际通过的 execution_root。
    """
    import sys

    root = tmp_path / "up"
    tests = root / "tests"
    (tests / "fake-repo").mkdir(parents=True)
    (tests / "fake-repo" / "marker.txt").write_text("ready", encoding="utf-8")
    (tests / "test_repo_root_fixture.py").write_text(
        "def test_repo_root_relative_fixture():\n"
        "    assert open('tests/fake-repo/marker.txt', encoding='utf-8').read() == 'ready'\n",
        encoding="utf-8",
    )

    result = precheck_upstream_conformance(
        root,
        ["tests/test_repo_root_fixture.py::test_repo_root_relative_fixture"],
        Path(sys.executable),
    )
    assert result["status"] == "PASS"
    assert result.get("execution_root") == "."


def test_precheck_still_fails_when_nodes_fail_under_every_root(tmp_path):
    """探测不是放水:两种惯例下都失败的子集仍然物化期拒绝。"""
    import sys

    root = tmp_path / "up"
    tests = root / "tests"
    tests.mkdir(parents=True)
    (tests / "test_truly_broken.py").write_text(
        "def test_truly_broken():\n    assert False\n",
        encoding="utf-8",
    )

    with pytest.raises(UpstreamConformanceError):
        precheck_upstream_conformance(
            root,
            ["tests/test_truly_broken.py::test_truly_broken"],
            Path(sys.executable),
        )


# ---- 准入测试面 = pytest 在该仓实际会收集的面
# (incident-conformance-surface-nested-package-tests-v1 /
#  incident-conformance-surface-declared-testpaths-v1) ----


def test_selection_reaches_package_internal_tests_directories(tmp_path) -> None:
    """无顶层 tests/ 的仓:测试嵌在包内 pkg/**/tests/test_*.py(pytest 默认
    递归收集,只跳过 norecursedirs)。只看顶层 tests 目录会把整仓判成零节点。"""
    root = tmp_path / "up"
    nested = root / "graphlib" / "algorithms" / "tests"
    nested.mkdir(parents=True)
    (root / "graphlib" / "__init__.py").write_text("", encoding="utf-8")
    (nested / "test_paths.py").write_text(
        "def test_shortest_path():\n    graphlib.shortest_path('g')\n",
        encoding="utf-8",
    )
    (root / "build" / "lib" / "tests").mkdir(parents=True)
    (root / "build" / "lib" / "tests" / "test_paths.py").write_text(
        "def test_shortest_path():\n    graphlib.shortest_path('g')\n",
        encoding="utf-8",
    )
    assert select_upstream_test_nodes(root, ["shortest_path"]) == [
        "graphlib/algorithms/tests/test_paths.py::test_shortest_path"
    ]


def test_selection_honours_declared_testpaths_and_python_files(tmp_path) -> None:
    """上游自己声明的收集规则(pyproject [tool.pytest.ini_options]):
    testpaths 通配 + 非默认 basename(*_tests.py)。显式 node id 下 pytest
    照样能收集这些文件,所以它们属于可运行的准入面。"""
    root = tmp_path / "up"
    tests = root / "tests"
    tests.mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\ntestpaths = "tests/*test*.py"\n',
        encoding="utf-8",
    )
    (tests / "unit_tests.py").write_text(
        "def test_extract_basic():\n    extract('<html/>')\n",
        encoding="utf-8",
    )
    (tests / "helpers.py").write_text(
        "def test_extract_helper():\n    extract('<html/>')\n",
        encoding="utf-8",
    )
    assert select_upstream_test_nodes(root, ["extract"]) == [
        "tests/unit_tests.py::test_extract_basic"
    ]


def test_selection_uses_pytest_default_python_files_when_undeclared(tmp_path) -> None:
    root = tmp_path / "up"
    tests = root / "tests"
    tests.mkdir(parents=True)
    (tests / "reader_test.py").write_text(
        "def test_parse():\n    reader.parse('x')\n", encoding="utf-8",
    )
    (tests / "notes.py").write_text(
        "def test_parse_notes():\n    reader.parse('x')\n", encoding="utf-8",
    )
    assert select_upstream_test_nodes(root, ["reader.parse"]) == [
        "tests/reader_test.py::test_parse"
    ]


def test_precheck_passes_explicit_non_default_basename_nodes(tmp_path) -> None:
    """守卫:选中的非默认命名文件必须真的能被 -c os.devnull 的 pytest 执行。"""
    import sys

    root = tmp_path / "up"
    tests = root / "tests"
    tests.mkdir(parents=True)
    (tests / "unit_tests.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8",
    )
    result = precheck_upstream_conformance(
        root, ["tests/unit_tests.py::test_ok"], Path(sys.executable),
    )
    assert result["status"] == "PASS"
