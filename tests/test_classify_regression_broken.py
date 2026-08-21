"""classify_regression_broken 的钉死(R3 台账细分)。

分桶判官 classify_node 每个桶各有一条守着;oracle_stdout 解析器的
fail-closed 分支(截断/解析不出/无小节)单独钉 —— 分类学要是把截断列表
当完整列表读,细分读数就会静默少算,必须炸在测试里。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from classify_regression_broken import (  # noqa: E402
    DELTA_NODE_IN_REGRESSION,
    EXTRACTION_FAILED,
    STRIPPED_NEW,
    STRIPPED_OLD_INTACT,
    STRIPPED_OLD_MODIFIED,
    VISIBLE_TREE,
    classify_node,
    extract_test_source,
    node_func_name,
    node_in_file,
    parse_regression_broken,
)

_BASE = '''\
import unittest


class TestThing(unittest.TestCase):
    def test_old_intact(self) -> None:
        self.assertEqual(1, 1)

    @unittest.skip("legacy")
    def test_old_modified(self) -> None:
        self.assertEqual("old", "old")


def test_module_level():
    assert True
'''

_POST = '''\
import unittest


class TestThing(unittest.TestCase):
    def test_old_intact(self) -> None:
        self.assertEqual(1, 1)

    @unittest.skip("legacy")
    def test_old_modified(self) -> None:
        self.assertEqual("new", "new")

    def test_brand_new(self) -> None:
        self.assertEqual(2, 2)

    def test_delta_a(self) -> None:
        self.assertEqual(3, 3)


def test_module_level():
    assert True
'''

_KW = dict(
    delta_nodes={"tests.test_thing.TestThing::test_delta_a"},
    post_files=["tests/test_thing.py"],
    post_text={"tests/test_thing.py": _POST},
    base_text={"tests/test_thing.py": _BASE},
)


def test_bucket_old_intact():
    assert classify_node("tests.test_thing.TestThing::test_old_intact",
                         **_KW) == STRIPPED_OLD_INTACT


def test_bucket_old_modified_is_flagged_not_intact():
    # post 版改了断言内容 —— 伪回归警报桶,绝不能混进 INTACT
    assert classify_node("tests.test_thing.TestThing::test_old_modified",
                         **_KW) == STRIPPED_OLD_MODIFIED


def test_bucket_new_green_on_parent():
    assert classify_node("tests.test_thing.TestThing::test_brand_new",
                         **_KW) == STRIPPED_NEW


def test_bucket_visible_tree():
    assert classify_node("tests.test_other.TestOther::test_x",
                         **_KW) == VISIBLE_TREE


def test_bucket_delta_leak_is_alarm():
    assert classify_node("tests.test_thing.TestThing::test_delta_a",
                         **_KW) == DELTA_NODE_IN_REGRESSION


def test_bucket_extraction_failed_fail_closed():
    assert classify_node("tests.test_thing.TestThing::test_ghost",
                         **_KW) == EXTRACTION_FAILED


def test_module_level_node_and_parametrize_suffix():
    assert classify_node("tests.test_thing::test_module_level[case-1]",
                         **_KW) == STRIPPED_OLD_INTACT
    assert node_func_name("a.b::test_x[p[0]]") == "test_x"
    assert node_in_file("tests.test_thing::test_module_level", "tests/test_thing.py")
    assert not node_in_file("tests.test_thingy.T::t", "tests/test_thing.py")


def test_extract_includes_decorator_and_stops_at_sibling():
    fn = extract_test_source(_POST, "test_old_modified")
    assert fn is not None and fn.startswith('    @unittest.skip("legacy")')
    assert "test_brand_new" not in fn
    assert extract_test_source(_BASE, "nope") is None


# ---------------------------------------------------------- 解析器 fail-closed

_LOG_TWO = """\
.......F.                                                                [100%]
=================================== FAILURES ===================================
_________________________ test_h2_no_regression_broken _________________________

    def test_h2_no_regression_broken(_r):
>       assert _r["regression_broken"] == [], _r["regression_broken"][:10]
E       AssertionError: ['tests.test_thing.TestThing::test_old_intact', 'tests.test_thing.TestThing::test_brand_new']
E       assert ['tests.test_...st_brand_new'] == []
E         \n\
E         Left contains 2 more items, first extra item: 'tests.test_thing.TestThing::test_old_intact'
E         Use -v to get more diff
=========================== short test summary info ============================
FAILED oracle/test_hidden_delta.py::test_h2_no_regression_broken
"""


def test_parse_two_items_complete():
    r = parse_regression_broken(_LOG_TWO)
    assert r["nodes"] == ["tests.test_thing.TestThing::test_old_intact",
                          "tests.test_thing.TestThing::test_brand_new"]
    assert r["truncated"] is False and r["total_claimed"] == 2
    assert r["problem"] is None


def test_parse_one_more_item_wording():
    log = _LOG_TWO.replace(
        "E       AssertionError: ['tests.test_thing.TestThing::test_old_intact', 'tests.test_thing.TestThing::test_brand_new']",
        "E       AssertionError: ['tests.test_thing.TestThing::test_old_intact']",
    ).replace("Left contains 2 more items", "Left contains one more item")
    r = parse_regression_broken(log)
    assert r["nodes"] == ["tests.test_thing.TestThing::test_old_intact"]
    assert r["truncated"] is False and r["total_claimed"] == 1


def test_parse_truncated_list_is_flagged():
    # 断言消息只带 [:10],全列表 12 条 → 必须亮截断旗,不得当完整读
    log = _LOG_TWO.replace("Left contains 2 more items",
                           "Left contains 12 more items")
    r = parse_regression_broken(log)
    assert r["truncated"] is True and r["total_claimed"] == 12


def test_parse_no_h2_section_means_green():
    r = parse_regression_broken("......... 9 passed in 60s\n")
    assert r["nodes"] == [] and r["problem"] is None


def test_parse_garbled_section_fail_closed():
    log = _LOG_TWO.replace("AssertionError: [", "AssertionError: <")
    r = parse_regression_broken(log)
    assert r["problem"] == "ASSERT_LIST_UNPARSED" and r["nodes"] == []


def test_parse_multiline_list():
    log = _LOG_TWO.replace(
        "E       AssertionError: ['tests.test_thing.TestThing::test_old_intact', 'tests.test_thing.TestThing::test_brand_new']",
        "E       AssertionError: ['tests.test_thing.TestThing::test_old_intact',\n"
        "E        'tests.test_thing.TestThing::test_brand_new']",
    )
    r = parse_regression_broken(log)
    assert r["nodes"] == ["tests.test_thing.TestThing::test_old_intact",
                          "tests.test_thing.TestThing::test_brand_new"]


def test_load_texts_missing_parent_tree_fails_closed(tmp_path):
    """错的 --pool-candidate 必须炸,不许静默分类(2026-08-21 实测:空基线
    把 STRIPPED_OLD_INTACT 判成 STRIPPED_NEW,整份分类学被毒而不自知)。"""
    import pytest
    from classify_regression_broken import load_texts

    task = tmp_path / "task"
    (task / "oracle").mkdir(parents=True)
    (task / "oracle" / "delta_manifest.json").write_text(
        '{"post_files": [], "delta_nodes": []}', encoding="utf-8")
    with pytest.raises(SystemExit, match="parent_tree"):
        load_texts(task, tmp_path / "no_such_candidate")


# ------------------------------------------------- P1-d:批选发次必须按任务过滤
# 2026-08-21 实测撞出:`--batch` 一次选了同批里九发,其中八发是别的任务 ——
# 它们拿 --task-dir 那一份 manifest 分桶,桶名俱在、逐条是假话。跳过的必须
# 落进证据(不静默丢),选空必须炸(不空判)。

def _row(run_id: str, task_id: str, batch: str = "B1") -> dict:
    return {"run_id": run_id, "task_id": task_id, "batch": batch,
            "model": "gpt-5.6", "verdict": "FAIL",
            "bundle_path": f"/tmp/{run_id}"}


def test_batch_selection_filters_by_task_and_records_the_skips() -> None:
    from classify_regression_broken import select_ledger_targets

    rows = [_row("r1", "hb1-sqlglot-8042-v2"), _row("r2", "hb1-click-3581-v2"),
            _row("r3", "hb1-sqlglot-8042-v2"), _row("r4", "hb1-click-3407-v2"),
            _row("r5", "hb1-sqlglot-8042-v2", batch="OTHER")]
    picked, skipped = select_ledger_targets(
        rows, task_id="hb1-sqlglot-8042-v2", batches=["B1"])
    assert [t["run_id"] for t in picked] == ["r1", "r3"]
    # 别的任务的发次不是"没有",是"跳过了" —— 逐条留名
    assert [s["run_id"] for s in skipped] == ["r2", "r4"]
    assert {s["task_id"] for s in skipped} == {"hb1-click-3581-v2",
                                               "hb1-click-3407-v2"}


def test_batch_selection_returns_nothing_when_task_absent() -> None:
    """任务/批对不上 → 选空(调用方据此 fail-closed 炸掉,不空判)。"""
    from classify_regression_broken import select_ledger_targets

    picked, skipped = select_ledger_targets(
        [_row("r1", "hb1-click-3581-v2")], task_id="hb1-sqlglot-8042-v2",
        batches=["B1"])
    assert picked == [] and len(skipped) == 1
