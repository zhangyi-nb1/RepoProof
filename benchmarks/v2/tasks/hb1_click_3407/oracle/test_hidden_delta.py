"""隐藏 oracle(纯接线;判据 = 上游同 PR 自带测试,D1 严口径)。

结局语义见 delta_oracle_lib 模块 docstring:h0 红=判卷器缺料(HARNESS 侧)、
h1 红=量具面被动(agent 侧,INSTRUMENT_TAMPERED)、delta 节点逐个判、
回归破坏单列。本文件三个任务包逐字节相同,由 build_hb1_task_packages.py
生成并钉死 —— 判卷器不许各任务各长一个样。
"""

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from delta_oracle_lib import load_manifest, run_delta_oracle  # noqa: E402

_M = load_manifest(HERE)


@pytest.fixture(scope="session")
def _r():
    return run_delta_oracle(HERE, Path(os.environ["REPOPROOF_HOST_ROOT"]))


def test_h0_oracle_operable(_r):
    assert not _r["problems"], _r["problems"]


def test_h1_instrument_surface_untouched(_r):
    assert not _r["instrument_problems"], _r["instrument_problems"]


@pytest.mark.parametrize("node", _M["delta_nodes"])
def test_delta_node(_r, node):
    assert _r["node_detail"].get(node) == "PASSED", \
        f"{node}: {_r['node_detail'].get(node, 'ORACLE_NOT_RUN')}"


def test_h2_no_regression_broken(_r):
    assert _r["regression_broken"] == [], _r["regression_broken"][:10]


def test_h3_tree_restored(_r):
    assert _r["restored_ok"]
