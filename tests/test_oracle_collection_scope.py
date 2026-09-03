"""Oracle 验收的收集范围守卫(incident-oracle-fixture-collection-scope-v1)。

不变量:隐藏验收只能执行 oracle 自己的测试模块;冻结 fixture 数据是
**数据**,永不作为测试被收集 —— 否则(a)合法交付 tests/ 目录的工作区
在收集期就撞车(同名 test 模块 import mismatch,假拦截);(b)fixture
内嵌测试若被执行并通过,会虚增 junit passed_checks(false-success 方向,
尺子把不属于尺子的东西计了数)。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from repoproof.runner.host_guided import oracle_pytest_targets


def _snapshot_with_fixture_tests(tmp_path: Path) -> Path:
    snap = tmp_path / "oracle_snapshot"
    snap.mkdir()
    (snap / "test_capability.py").write_text(
        "def test_capability_check():\n    assert True\n",
        encoding="utf-8",
    )
    (snap / "semantic_verifier.py").write_text(
        "def verify(a, b):\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    for scenario in ("alpha", "beta"):
        tests_dir = snap / "fixtures" / scenario / "expected" / "project" / "tests"
        tests_dir.mkdir(parents=True)
        # 同名模块 + 无包结构:目录级收集必然 import mismatch;
        # 且断言必失败 —— 若被执行,还会污染失败计数。
        (tests_dir / "test_smoke.py").write_text(
            "def test_smoke():\n    assert False\n",
            encoding="utf-8",
        )
    return snap


def test_oracle_targets_exclude_fixture_data(tmp_path: Path) -> None:
    snap = _snapshot_with_fixture_tests(tmp_path)
    targets = oracle_pytest_targets(snap)
    assert targets == [str(snap / "test_capability.py")]


def test_oracle_targets_keep_every_top_level_test_module(tmp_path: Path) -> None:
    snap = _snapshot_with_fixture_tests(tmp_path)
    (snap / "test_extra_surface.py").write_text(
        "def test_extra():\n    assert True\n",
        encoding="utf-8",
    )
    targets = oracle_pytest_targets(snap)
    assert targets == [
        str(snap / "test_capability.py"),
        str(snap / "test_extra_surface.py"),
    ]


def test_oracle_run_over_targets_is_clean_while_directory_mode_crashes(
    tmp_path: Path,
) -> None:
    """行为级反事实:目录收集撞车(旧行为),目标收集只跑 oracle 自检。"""
    snap = _snapshot_with_fixture_tests(tmp_path)

    directory_mode = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(snap)],
        capture_output=True, text=True, timeout=120, cwd=tmp_path,
    )
    assert directory_mode.returncode != 0, "目录级收集本应撞 fixture 数据"

    target_mode = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         *oracle_pytest_targets(snap)],
        capture_output=True, text=True, timeout=120, cwd=tmp_path,
    )
    assert target_mode.returncode == 0, target_mode.stdout + target_mode.stderr
    assert "1 passed" in target_mode.stdout


def test_oracle_targets_fall_back_to_directory_when_no_test_module(tmp_path: Path) -> None:
    """守恒:没有顶层 test 模块的旧谱系快照保持原目录语义。"""
    snap = tmp_path / "legacy_snapshot"
    snap.mkdir()
    (snap / "data.json").write_text("{}", encoding="utf-8")
    assert oracle_pytest_targets(snap) == [str(snap)]
