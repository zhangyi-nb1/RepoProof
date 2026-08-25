"""delta oracle 驱动引擎的钉死(U 系,HB-PCDELTA-1)。

引擎是判卷器,它的每个失效方向都要有人守:缺料必须拒判(U3)、delta 节点
缺席必须算红(U6)、回归破坏不得掺进 delta 账(U4)、量具面被动必须看见
(U5/U7)、判完必须还原(U8)。合成小世界跑真 pytest 子进程 —— 判卷器的
钉死不许 mock 掉判卷本身。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from delta_oracle_lib import (  # noqa: E402
    ABSENT,
    guarded_root_state,
    instrument_problems,
    run_delta_oracle,
)
from delta_oracle_lib import tests_tree_digest as _tree_digest  # noqa: E402

# 别名导入:裸名以 tests_ 开头会被 pytest 当测试项收集


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _mini_world(tmp_path: Path, *, with_marker: bool) -> tuple[Path, Path]:
    """合成宿主 + oracle 目录。delta 测试 = marker 文件存在(=实现到位)。"""
    host = tmp_path / "host"
    (host / "tests").mkdir(parents=True)
    (host / "tests" / "test_old.py").write_text(
        "def test_old():\n    assert True\n", encoding="utf-8")
    if with_marker:
        (host / "marker.txt").write_text("impl\n", encoding="utf-8")

    post_body = ("from pathlib import Path\n\n\n"
                 "def test_new():\n    assert Path('marker.txt').exists()\n")
    oracle = tmp_path / "oracle"
    (oracle / "post_tests" / "tests").mkdir(parents=True)
    (oracle / "post_tests" / "tests" / "test_new.py").write_text(
        post_body, encoding="utf-8")
    manifest = {
        "candidate": "mini",
        "delta_nodes": ["tests.test_new::test_new"],
        "post_files": [{"path": "tests/test_new.py",
                        "sha256": _sha(post_body.encode())}],
        "tests_tree_sha256": _tree_digest(host),
        "guarded_root_files": guarded_root_state(host),
        "suite_timeout_s": 120,
    }
    (oracle / "delta_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    return oracle, host


def test_u1_positive_delta_goes_green_and_tree_restored(tmp_path):
    oracle, host = _mini_world(tmp_path, with_marker=True)
    r = run_delta_oracle(oracle, host)
    assert r["problems"] == [] and r["instrument_problems"] == []
    assert r["node_detail"]["tests.test_new::test_new"] == "PASSED"
    assert r["regression_broken"] == []
    assert r["restored_ok"]
    assert not (host / "tests" / "test_new.py").exists()   # 铺进去的必须撤走


def test_u2_missing_impl_delta_stays_red(tmp_path):
    oracle, host = _mini_world(tmp_path, with_marker=False)
    r = run_delta_oracle(oracle, host)
    assert r["node_detail"]["tests.test_new::test_new"] == "FAILED"
    assert r["regression_broken"] == []                    # 老测试仍绿,不掺账


def test_u3_missing_material_refuses_to_judge(tmp_path):
    oracle, host = _mini_world(tmp_path, with_marker=True)
    (oracle / "post_tests" / "tests" / "test_new.py").unlink()
    r = run_delta_oracle(oracle, host)
    assert any(p.startswith("MATERIALIZATION_MISSING") for p in r["problems"])
    assert r["passed_nodes"] == set()                      # 缺料不产任何绿


def test_u3b_digest_mismatch_refuses_to_judge(tmp_path):
    oracle, host = _mini_world(tmp_path, with_marker=True)
    f = oracle / "post_tests" / "tests" / "test_new.py"
    f.write_text(f.read_text() + "\n# drift\n", encoding="utf-8")
    r = run_delta_oracle(oracle, host)
    assert any("DIGEST_MISMATCH" in p for p in r["problems"])


def test_u4_regression_breakage_lands_in_its_own_bucket(tmp_path):
    oracle, host = _mini_world(tmp_path, with_marker=True)
    (host / "tests" / "test_old.py").write_text(
        "def test_old():\n    assert False\n", encoding="utf-8")
    # 量具面守卫会先红(tests/ 动了)—— 这里更新 manifest 假装出题态如此,
    # 单独考"回归破坏分桶"这一条判断。
    m = json.loads((oracle / "delta_manifest.json").read_text())
    m["tests_tree_sha256"] = _tree_digest(host)
    (oracle / "delta_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    r = run_delta_oracle(oracle, host)
    assert r["regression_broken"] == ["tests.test_old::test_old"]
    assert r["node_detail"]["tests.test_new::test_new"] == "PASSED"


def test_u5_touched_tests_tree_is_visible(tmp_path):
    oracle, host = _mini_world(tmp_path, with_marker=True)
    (host / "tests" / "test_old.py").write_text(
        "def test_old():\n    assert 1\n", encoding="utf-8")
    probs = instrument_problems(host, json.loads(
        (oracle / "delta_manifest.json").read_text()))
    assert any("TESTS_TREE_MODIFIED" in p for p in probs)


def test_u6_node_missing_is_red_not_silent(tmp_path):
    """fail-closed:junitxml 两头不见的 delta 节点 = 红(量具第 4 次被救的病)。"""
    oracle, host = _mini_world(tmp_path, with_marker=True)
    m = json.loads((oracle / "delta_manifest.json").read_text())
    m["delta_nodes"].append("tests.test_new::test_ghost")
    (oracle / "delta_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    r = run_delta_oracle(oracle, host)
    assert r["node_detail"]["tests.test_new::test_ghost"].startswith("NODE_MISSING")


def test_u7_planted_root_conftest_is_visible(tmp_path):
    """根 conftest.py 猴补丁是全绿伪造的现成路径 —— 出现即红。"""
    oracle, host = _mini_world(tmp_path, with_marker=True)
    (host / "conftest.py").write_text("# hook\n", encoding="utf-8")
    probs = instrument_problems(host, json.loads(
        (oracle / "delta_manifest.json").read_text()))
    assert any("GUARDED_FILE_MODIFIED:conftest.py" in p for p in probs)
    assert guarded_root_state(host)["conftest.py"] != ABSENT


def test_u8_lay_target_occupied_refuses(tmp_path):
    """delta 落点被占(agent 在剥离路径上写了同名文件)→ 拒铺拒判,不覆盖。

    落点被占是 agent 动了量具面,必须挂 h1 桶:挂 h0 会让归因倒挂成
    HARNESS_FAILURE(h0 优先级更高),等于把篡改记成"我们自己的故障"。
    """
    oracle, host = _mini_world(tmp_path, with_marker=True)
    (host / "tests" / "test_new.py").write_text("def test_new():\n    pass\n",
                                               encoding="utf-8")
    m = json.loads((oracle / "delta_manifest.json").read_text())
    m["tests_tree_sha256"] = _tree_digest(host)      # 隔离:只考占位判断
    (oracle / "delta_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    r = run_delta_oracle(oracle, host)
    assert any(p.startswith("LAY_TARGET_OCCUPIED")
               for p in r["instrument_problems"])
    assert not any("LAY_TARGET_OCCUPIED" in p for p in r["problems"])
    assert (host / "tests" / "test_new.py").read_text().startswith("def test_new")


# ---- 2026-08-16 可搬运性审查 blocking 的钉死(两条独立伪绿通道)----

_TAMPER_SITECUSTOMIZE = (
    "import _pytest.python as _rp\n"
    "_rp.Function.runtest = lambda self: None   # 全绿伪造\n")


def test_u9_planted_sitecustomize_is_visible(tmp_path):
    """blocking [1a]:根级 sitecustomize.py 在解释器起点自动 import,先于
    pytest 一切配置 —— 它不在守卫面里,零实现就能把真红压成绿。"""
    oracle, host = _mini_world(tmp_path, with_marker=False)
    (host / "sitecustomize.py").write_text(_TAMPER_SITECUSTOMIZE, encoding="utf-8")
    probs = instrument_problems(host, json.loads(
        (oracle / "delta_manifest.json").read_text()))
    assert any("GUARDED_FILE_MODIFIED:sitecustomize.py" in p for p in probs)


def test_u9b_judging_subprocess_drops_inherited_pythonpath(tmp_path, monkeypatch):
    """[1a] 的注入通道:外层 _run_oracle 注 PYTHONPATH=<宿主根>,若被判卷子
    进程继承,宿主根就在 site 处理时刻上 sys.path,载荷自动生效。守卫是第一
    道防线,env 净化是第二道 —— 这里单独考第二道:守卫故意放行(把载荷登记
    进出题态),判卷仍必须真红。"""
    oracle, host = _mini_world(tmp_path, with_marker=False)
    (host / "sitecustomize.py").write_text(_TAMPER_SITECUSTOMIZE, encoding="utf-8")
    m = json.loads((oracle / "delta_manifest.json").read_text())
    m["guarded_root_files"] = guarded_root_state(host)      # 隔离:只考 env 净化
    (oracle / "delta_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(host))
    r = run_delta_oracle(oracle, host)
    assert r["instrument_problems"] == []                   # 守卫已放行
    assert r["node_detail"]["tests.test_new::test_new"] == "FAILED"  # 仍真红


def test_u10_subdir_conftest_global_plugin_is_out_of_collection(tmp_path):
    """blocking [1b]:子目录 conftest.py 里 pytest_configure + pluginmanager
    .register() 的插件是**全局**作用域,不受目录过滤约束;裸 pytest 收整棵树
    时,任何新建目录都是入口(sqlglot 无 testpaths,正是这么被攻破的)。
    收集面限定到冻结子树后,该 conftest 根本不被加载。"""
    oracle, host = _mini_world(tmp_path, with_marker=False)
    evil = host / "evil"
    evil.mkdir()
    (evil / "conftest.py").write_text(
        "class _P:\n"
        "    def pytest_runtest_makereport(self, item, call):\n"
        "        from _pytest.runner import TestReport\n"
        "        return TestReport(item.nodeid, (), {}, 'passed', None, call.when)\n"
        "def pytest_configure(config):\n"
        "    config.pluginmanager.register(_P())\n", encoding="utf-8")
    (evil / "test_anchor.py").write_text("def test_anchor():\n    pass\n",
                                         encoding="utf-8")
    r = run_delta_oracle(oracle, host)
    assert r["instrument_problems"] == []       # evil/ 在 tests/ 外,守卫不覆盖
    assert r["node_detail"]["tests.test_new::test_new"] == "FAILED"   # 仍真红
    assert "evil.test_anchor::test_anchor" not in r["passed_nodes"]   # 压根没收


def test_u11_guard_subtree_equals_collection_subtree(tmp_path):
    """守 A 收 B 是 [1b] 的一般形:两处必须取同一个 manifest 字段。"""
    oracle, host = _mini_world(tmp_path, with_marker=True)
    (host / "suite").mkdir()
    (host / "suite" / "test_x.py").write_text("def test_x():\n    pass\n",
                                              encoding="utf-8")
    m = json.loads((oracle / "delta_manifest.json").read_text())
    m["tests_subdir"] = "suite"
    m["tests_tree_sha256"] = _tree_digest(host, "suite")
    (oracle / "delta_manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert instrument_problems(host, m) == []            # 守的是 suite/
    r = run_delta_oracle(oracle, host)
    assert "suite.test_x::test_x" in r["passed_nodes"]   # 收的也是 suite/
    assert "tests.test_old::test_old" not in r["passed_nodes"]


# ---- 构造法 v2(R1,2026-08-21):base 版测试文件留树,lay 变 save/覆写/放回

_BASE_BODY = "def test_kept_from_base():\n    assert True\n"


def _mini_world_v2(tmp_path: Path, *, with_marker: bool) -> tuple[Path, Path]:
    """v2 合成世界:delta 所在文件的 base 版**在树里**;post = base + 新测试。"""
    host = tmp_path / "host"
    (host / "tests").mkdir(parents=True)
    (host / "tests" / "test_old.py").write_text(
        "def test_old():\n    assert True\n", encoding="utf-8")
    (host / "tests" / "test_feature.py").write_text(_BASE_BODY, encoding="utf-8")
    if with_marker:
        (host / "marker.txt").write_text("impl\n", encoding="utf-8")

    post_body = ("from pathlib import Path\n\n\n" + _BASE_BODY
                 + "\n\ndef test_new():\n    assert Path('marker.txt').exists()\n")
    oracle = tmp_path / "oracle"
    (oracle / "post_tests" / "tests").mkdir(parents=True)
    (oracle / "post_tests" / "tests" / "test_feature.py").write_text(
        post_body, encoding="utf-8")
    manifest = {
        "candidate": "mini-v2",
        "construction_law": "v2",
        "delta_nodes": ["tests.test_feature::test_new"],
        "post_files": [{"path": "tests/test_feature.py",
                        "sha256": _sha(post_body.encode())}],
        "base_files": [{"path": "tests/test_feature.py",
                        "sha256": _sha(_BASE_BODY.encode())}],
        "tests_tree_sha256": _tree_digest(host),
        "guarded_root_files": guarded_root_state(host),
        "suite_timeout_s": 120,
    }
    (oracle / "delta_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    return oracle, host


def test_u12_v2_base_file_saved_overwritten_and_put_back(tmp_path):
    """v2 正向:落点在场是应然(不是 LAY_TARGET_OCCUPIED)—— 判卷时铺 post,
    判后放回 base 字节;base 里的旧测试与 post 里的新测试都真跑了。"""
    oracle, host = _mini_world_v2(tmp_path, with_marker=True)
    r = run_delta_oracle(oracle, host)
    assert r["problems"] == [] and r["instrument_problems"] == []
    assert r["node_detail"]["tests.test_feature::test_new"] == "PASSED"
    assert "tests.test_feature::test_kept_from_base" in r["passed_nodes"]
    assert r["regression_broken"] == []
    assert r["restored_ok"]
    assert (host / "tests" / "test_feature.py").read_text(
        encoding="utf-8") == _BASE_BODY          # 放回的是 base,不是 post


def test_u12b_v2_agent_modified_base_is_h1_red_but_still_judged(tmp_path):
    """v2 下 agent 改了 base 测试文件:H1(tests_tree)红、归因 agent 侧,
    判卷照跑不失明;判后放回的是 **lay 前态**(agent 的字节),digest 复核
    语义不变 —— 篡改已由 H1 记账,还原不负责抹掉它。"""
    oracle, host = _mini_world_v2(tmp_path, with_marker=True)
    agent_body = _BASE_BODY + "\n\ndef test_agent_added():\n    assert True\n"
    (host / "tests" / "test_feature.py").write_text(agent_body, encoding="utf-8")
    r = run_delta_oracle(oracle, host)
    assert any("TESTS_TREE_MODIFIED" in p for p in r["instrument_problems"])
    assert not any("LAY_TARGET_OCCUPIED" in p for p in r["instrument_problems"])
    assert r["node_detail"]["tests.test_feature::test_new"] == "PASSED"
    assert r["restored_ok"]
    assert (host / "tests" / "test_feature.py").read_text(
        encoding="utf-8") == agent_body


def test_u12c_v2_deleted_base_file_recorded_and_absence_restored(tmp_path):
    """v2 下 agent 删了 base 测试文件:记 BASE_FILE_MISSING(h1 桶,与
    tests_tree 摘要互证),照铺照判,判后撤走恢复缺席态。"""
    oracle, host = _mini_world_v2(tmp_path, with_marker=True)
    (host / "tests" / "test_feature.py").unlink()
    r = run_delta_oracle(oracle, host)
    assert any(p.startswith("BASE_FILE_MISSING:tests/test_feature.py")
               for p in r["instrument_problems"])
    assert any("TESTS_TREE_MODIFIED" in p for p in r["instrument_problems"])
    assert r["node_detail"]["tests.test_feature::test_new"] == "PASSED"
    assert r["restored_ok"]
    assert not (host / "tests" / "test_feature.py").exists()
