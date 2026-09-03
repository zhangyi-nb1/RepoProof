"""一致性节点在冻结前要真的跑一遍(incident-conformance-node-needs-absent-test-dependency-*)。

现象:静态 AST 可运行性画像看不见函数体内的运行期 import(pyquery)与 conftest 通过
`pytest_generate_tests` 注入的套件级参数化(lxml 变体),选中的节点到彩排期才发现跑不起来,
整个案例以 HARNESS 环境故障 BLOCKED——而同文件里明明有能跑的节点。

不变量:
  I1 `probe_runnable_nodes(repo, candidates, python)` 逐个执行候选,只保留在当前解释器下
     真正通过的节点 id(含参数 id,如 `test_x[plain]`),丢弃的节点连同缺失模块名一起记录;
  I2 `ModuleNotFoundError: X` 使所有还没跑的、源码里 import X 的候选直接淘汰,不再逐个跑;
  I3 全部候选都跑不起来时返回空选择与原因,而不是把注定失败的节点冻结进任务包。
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from repoproof.adoption.intake.upstream_conformance import probe_runnable_nodes, select_upstream_test_nodes


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "up"
    tests = repo / "tests"
    tests.mkdir(parents=True)
    (repo / "widget.py").write_text("def render(x):\n    return x * 2\n", encoding="utf-8")
    (tests / "conftest.py").write_text(
        textwrap.dedent(
            """
            import pytest

            def pytest_generate_tests(metafunc):
                if "flavour" in metafunc.fixturenames:
                    metafunc.parametrize("flavour", ["needs_missing", "plain"])

            @pytest.fixture
            def backend(flavour):
                if flavour == "needs_missing":
                    import repoproof_absent_backend_zz  # noqa: F401
                return flavour
            """
        ),
        encoding="utf-8",
    )
    (tests / "test_widget.py").write_text(
        textwrap.dedent(
            """
            import sys
            sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])
            from widget import render

            def test_render_runtime_import():
                import repoproof_absent_helper_zz  # noqa: F401
                assert render(1) == 2

            def test_render_flavoured(backend):
                assert render(2) == 4

            def test_render_plain():
                assert render(3) == 6
            """
        ),
        encoding="utf-8",
    )
    return repo


def test_probe_keeps_only_nodes_that_really_pass_and_names_missing_modules(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    candidates = select_upstream_test_nodes(repo, ["render"], max_nodes=6)
    assert len(candidates) == 3
    kept, dropped = probe_runnable_nodes(repo, candidates, python=Path(sys.executable), max_nodes=3)
    assert "tests/test_widget.py::test_render_plain" in kept
    assert "tests/test_widget.py::test_render_flavoured[plain]" in kept
    assert all("needs_missing" not in node for node in kept)
    assert all("test_render_runtime_import" not in node for node in kept)
    missing = {row["missing_module"] for row in dropped if row.get("missing_module")}
    assert "repoproof_absent_helper_zz" in missing and "repoproof_absent_backend_zz" in missing


def test_probe_reports_an_empty_selection_when_nothing_runs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "tests" / "test_widget.py").write_text(
        "def test_only():\n    import repoproof_absent_helper_zz  # noqa: F401\n",
        encoding="utf-8",
    )
    kept, dropped = probe_runnable_nodes(
        repo, ["tests/test_widget.py::test_only"], python=Path(sys.executable), max_nodes=3
    )
    assert kept == [] and dropped and dropped[0]["missing_module"] == "repoproof_absent_helper_zz"
