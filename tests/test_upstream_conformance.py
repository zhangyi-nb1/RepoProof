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
    assert len(calls) == 1
    assert "pip" not in calls[0]
    assert "tests/test_table_extract.py::test_table_basic" in calls[0][-1]


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
