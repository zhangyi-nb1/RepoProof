"""HB1 宿主部署脚本的纯函数钉死(HB-PCDELTA-1 出题工程,2026-08-16)。

只钉三样纯东西 + 一条复用纪律,不碰封存池、不碰 bench、不建 venv:

    P1  judge_baseline:failed 必须为 0 才 READY;skip 不拦(v2 卫生判据,
        用户裁决 b —— 平台常量 skip 如实入档,不写死预期值);零收集拒判。
    P2  extract_fingerprints:只取非测试文件的新增行;'+++ ' 文件头不算;
        strip 后 >20 才算;去重;re.escape(正则元字符当字面量搜)。
    P3  file_diff:缺 / 多 / 内容不符三类分开列,任一非空即不 ok ——
        "digest 相等"只是总闸,出事必须能指出哪个文件。
    P4  量法复用不复制:摘要/计分/离线环境必须是 blind_attack_admission
        的原件(复制一份会在原件改动后静默漂移,M58a 的形状)。

第二轮裁决(2026-08-16,delivery 实测含攻击者终态)加钉三条:

    P5  construction_check:V(delivery∩parent)与期望推导(parent −
        .github/** − test_files − extra_drop)必须恰好相等;不等时两侧
        差异都得点名 —— tripwire 只判不裁,停下与否是调用方的义务。
        裁决二(tripwire 首跑触发后):两条推导双双剔除 __pycache__/** 与
        *.pyc,V 一律不含字节码 —— 被剥测试文件的 parent 侧 .pyc 是指向
        隐藏 oracle 的结构性箭头且可反编译。
    P6  attacker_residue:攻击者新建/改过的文件逐条留痕,一条不漏。
    P7  calibrate_fingerprints:parent 已有的指纹(含子串重合)剔除且留名,
        其余保留 —— "零命中"必须能对账是校准换来的还是真干净。
"""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "prepare_hb1_hosts", REPO / "scripts" / "prepare_hb1_hosts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------ P1 judge_baseline
def _score(total=3, passed=3, skipped=0, failed_nodes=(), skip_nodes=()):
    return {"total": total, "passed": passed, "skipped": skipped,
            "failed_nodes": sorted(failed_nodes),
            "skipped_nodes": sorted(skip_nodes)}


def test_judge_baseline_green_and_skips_do_not_block():
    m = _load()
    v = m.judge_baseline(_score(total=30, passed=4, skipped=26,
                                skip_nodes=[f"t::s{i}" for i in range(26)]))
    assert v["status"] == "READY"
    assert v["problems"] == []


def test_judge_baseline_any_red_is_not_ready():
    m = _load()
    v = m.judge_baseline(_score(total=3, passed=2,
                                failed_nodes=["tests.t::test_x"]))
    assert v["status"] == "NOT_READY"
    assert any("tests.t::test_x" in p for p in v["problems"])


def test_judge_baseline_zero_collection_is_not_ready():
    m = _load()
    v = m.judge_baseline(_score(total=0, passed=0))
    assert v["status"] == "NOT_READY"
    assert v["problems"]


# ------------------------------------------------------ P2 extract_fingerprints
_PATCH = """\
diff --git a/src/pkg/mod.py b/src/pkg/mod.py
--- a/src/pkg/mod.py
+++ b/src/pkg/mod.py
@@ -1,3 +1,8 @@
 context line stays here untouched
+x = 1
+aaaaaaaaaaaaaaaaaaaa
+bbbbbbbbbbbbbbbbbbbbb
+result = compute_the_answer(x, y) * 42
+result = compute_the_answer(x, y) * 42
+if value.startswith("(special)") and flag:
diff --git a/src/pkg/newmod.py b/src/pkg/newmod.py
--- /dev/null
+++ b/src/pkg/newmod.py
@@ -0,0 +1,1 @@
+brand_new_module_line_long_enough_to_count
diff --git a/src/pkg/gone.py b/src/pkg/gone.py
--- a/src/pkg/gone.py
+++ /dev/null
@@ -1,1 +0,0 @@
-old_line_removed_from_deleted_file_here
diff --git a/tests/test_mod.py b/tests/test_mod.py
--- a/tests/test_mod.py
+++ b/tests/test_mod.py
@@ -1,2 +1,4 @@
 import pkg
+def test_added_secret_oracle_line_is_long():
+    assert compute_the_answer(1, 2) == 84
"""


def test_fingerprints_take_only_nontest_added_lines_over_20():
    m = _load()
    fps = m.extract_fingerprints(_PATCH, ["tests/test_mod.py"])
    raws = [f["raw"] for f in fps]
    # 去重后恰四条:两条实现行 + 21 字符边界行 + 新文件行
    assert raws == ["bbbbbbbbbbbbbbbbbbbbb",
                    "result = compute_the_answer(x, y) * 42",
                    'if value.startswith("(special)") and flag:',
                    "brand_new_module_line_long_enough_to_count"]
    # 20 字符(恰不达标)与短行被拒;'+++ ' 文件头不算新增行
    assert "aaaaaaaaaaaaaaaaaaaa" not in raws
    assert not any("+++" in r or r.startswith("b/") for r in raws)
    # 测试文件的新增行(delta 试件内容)一条不进指纹
    assert not any("test_added_secret_oracle" in r or "== 84" in r
                   for r in raws)


def test_fingerprints_are_escaped_literals():
    m = _load()
    fps = m.extract_fingerprints(_PATCH, ["tests/test_mod.py"])
    special = next(f for f in fps if "(special)" in f["raw"])
    # 元字符被 escape:pattern 与 raw 不同,但对 raw 本身必须命中
    assert special["pattern"] == re.escape(special["raw"])
    assert special["pattern"] != special["raw"]
    assert re.search(special["pattern"], special["raw"])
    # 未 escape 的话 '(special)' 是捕获组,对含字面括号的行不命中
    assert re.search(special["pattern"],
                     'if value.startswith("(special)") and flag:')


def test_fingerprints_empty_patch_yields_nothing():
    m = _load()
    assert m.extract_fingerprints("", []) == []


# ---------------------------------------------------------------- P3 file_diff
def test_file_diff_equal_maps_ok():
    m = _load()
    d = m.file_diff({"a": "1", "b": "2"}, {"a": "1", "b": "2"})
    assert d["ok"] and d["missing"] == d["extra"] == d["mismatch"] == []


def test_file_diff_lists_all_three_kinds():
    m = _load()
    d = m.file_diff({"a": "1", "b": "2", "c": "3"},
                    {"a": "1", "b": "XX", "d": "4"})
    assert not d["ok"]
    assert d["missing"] == ["c"]
    assert d["extra"] == ["d"]
    assert d["mismatch"] == ["b"]


def test_file_diff_on_synthetic_trees(tmp_path):
    """tmp_path 合成小树:改一字节 / 删一件 / 多一件,三类各自被点名。"""
    m = _load()
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "keep.txt").write_bytes(b"same bytes")
    (src / "sub" / "mut.txt").write_bytes(b"original")
    (src / "lost.txt").write_bytes(b"will vanish")
    dst = tmp_path / "dst"
    shutil.copytree(src, dst)
    assert m.file_diff(m._file_map(src), m._file_map(dst))["ok"]

    (dst / "sub" / "mut.txt").write_bytes(b"originaX")     # 同长改一字节
    (dst / "lost.txt").unlink()
    (dst / "extra.txt").write_bytes(b"stowaway")
    d = m.file_diff(m._file_map(src), m._file_map(dst))
    assert not d["ok"]
    assert d["missing"] == ["lost.txt"]
    assert d["extra"] == ["extra.txt"]
    assert d["mismatch"] == ["sub/mut.txt"]


# ------------------------------------------------- P5 construction_check(V 树)
def test_construction_check_exact_match_ok():
    m = _load()
    parent = {"src/a.py", "src/b.py", "tests/test_a.py", "tests/test_keep.py",
              ".github/ci.yml", "CHANGELOG.md", "README.md"}
    # delivery = parent 剥掉 .github / delta 测试文件 / CHANGELOG,再"改"了内容
    # (路径集不变);攻击者新建文件不在 parent,自然被 ∩ 剔除
    delivery = {"src/a.py", "src/b.py", "tests/test_keep.py", "README.md",
                "src/attacker_new_helper.py"}
    c = m.construction_check(delivery, parent, ["tests/test_a.py"],
                             extra_drop={"CHANGELOG.md"})
    assert c["ok"]
    assert c["missing_from_v"] == [] and c["unexpected_in_v"] == []
    assert c["v_count"] == c["expected_count"] == 4


def test_construction_check_mismatch_names_both_sides():
    m = _load()
    parent = {"src/a.py", "docs/extra.md", "tests/test_a.py", ".github/ci.yml"}
    # delivery 缺 parent 的 docs/extra.md(期望推导包含它)→ 期望有而 V 无;
    # delivery 还保住了本该剔除的 delta 测试文件 → V 有而期望无
    delivery = {"src/a.py", "tests/test_a.py"}
    c = m.construction_check(delivery, parent, ["tests/test_a.py"])
    assert not c["ok"]
    assert c["missing_from_v"] == ["docs/extra.md"]
    assert c["unexpected_in_v"] == ["tests/test_a.py"]


def test_construction_check_bytecode_excluded_from_both_derivations():
    """裁决二:pycache 不对称不再触发 tripwire,且 V 一律不含字节码。"""
    m = _load()
    parent = {"src/a.py", "src/__pycache__/a.cpython-312.pyc",
              "tests/__pycache__/test_a.cpython-312-pytest-9.1.1.pyc",
              "stray.pyc", "tests/test_a.py"}
    # delivery 与 parent 的 pyc 集合不一致(parent 独有两份、双方共有一份)
    delivery = {"src/a.py", "src/__pycache__/a.cpython-312.pyc"}
    c = m.construction_check(delivery, parent, ["tests/test_a.py"])
    assert c["ok"]
    assert c["v_paths"] == ["src/a.py"]      # 共有的 pyc 也进不了 V
    assert c["v_count"] == c["expected_count"] == 1


def test_is_bytecode_predicate():
    m = _load()
    assert m.is_bytecode("a/__pycache__/b.cpython-312.pyc")
    assert m.is_bytecode("__pycache__/x.py")     # 目录整段剔除
    assert m.is_bytecode("a/b.pyc")
    assert not m.is_bytecode("a/pycache.py")     # 名字里含 pycache 不算
    assert not m.is_bytecode("src/a.py")


def test_construction_check_github_subtree_excluded_from_expectation():
    m = _load()
    parent = {"src/a.py", ".github/workflows/ci.yml", ".github/FUNDING.yml"}
    c = m.construction_check({"src/a.py"}, parent, [])
    assert c["ok"] and c["expected_count"] == 1


# ----------------------------------------- 构造法 v2(R1,2026-08-21)
def test_construction_check_v2_keeps_base_test_files():
    """law=v2:base 版测试文件并回 V(内容取 parent 版),期望推导不再减
    test_files;extra_drop(CHANGELOG 泄漏轴)照旧剥。与 v1 同世界对照:
    唯一差异 = tests/test_a.py 在 V 里。"""
    m = _load()
    parent = {"src/a.py", "src/b.py", "tests/test_a.py", "tests/test_keep.py",
              ".github/ci.yml", "CHANGELOG.md", "README.md"}
    delivery = {"src/a.py", "src/b.py", "tests/test_keep.py", "README.md",
                "src/attacker_new_helper.py"}
    c = m.construction_check(delivery, parent, ["tests/test_a.py"],
                             extra_drop={"CHANGELOG.md"}, law="v2")
    assert c["ok"], (c["missing_from_v"], c["unexpected_in_v"])
    assert "tests/test_a.py" in c["v_paths"]
    assert c["v_count"] == c["expected_count"] == 5
    assert "CHANGELOG.md" not in c["v_paths"]
    assert c["law"] == "v2"
    # 同世界 v1 对照:base 测试文件不在 V(既有语义字面不变)
    c1 = m.construction_check(delivery, parent, ["tests/test_a.py"],
                              extra_drop={"CHANGELOG.md"})
    assert c1["ok"] and "tests/test_a.py" not in c1["v_paths"]
    assert c1["law"] == "v1"


def test_construction_check_v2_does_not_invent_pr_new_test_files():
    """v2 只并回 parent 里**存在**的测试文件 —— PR 新建的测试文件无 base
    内容可铺,不得被发明出来。"""
    m = _load()
    parent = {"src/a.py", "tests/test_a.py"}
    delivery = {"src/a.py"}
    c = m.construction_check(delivery, parent,
                             ["tests/test_a.py", "tests/test_brand_new.py"],
                             law="v2")
    assert c["ok"]
    assert c["v_paths"] == ["src/a.py", "tests/test_a.py"]


def test_construction_check_rejects_unknown_law():
    m = _load()
    try:
        m.construction_check(set(), set(), [], law="v3")
    except ValueError as e:
        assert "v3" in str(e)
    else:
        raise AssertionError("未知构造法必须拒绝,不许静默走 v1")


# ---------------------------------------------- P6 attacker_residue(逐条留痕)
def test_attacker_residue_lists_added_and_modified():
    m = _load()
    parent = {"src/a.py": "h1", "src/b.py": "h2", "tests/test_a.py": "h3"}
    delivery = {"src/a.py": "h1",          # 未动
                "src/b.py": "hX",          # 攻击者改过
                "src/new.py": "h9"}        # 攻击者新建
    r = m.attacker_residue(delivery, parent)
    assert r == {"added": ["src/new.py"], "modified": ["src/b.py"]}


def test_attacker_residue_clean_delivery_is_empty():
    m = _load()
    same = {"src/a.py": "h1", "README.md": "h2"}
    assert m.attacker_residue(dict(same), dict(same)) == {"added": [],
                                                          "modified": []}


# ------------------------------------- P7 calibrate_fingerprints(round2 同法)
def test_calibrate_drops_parent_preexisting_including_substring():
    m = _load()
    fps = m.extract_fingerprints(
        "--- a/src/m.py\n+++ b/src/m.py\n"
        "+columns: list[str] = []\n"
        "+truly_novel_answer_only_line = compute(x)\n", [])
    parent_blob = "def f():\n    pre_pivot_columns: list[str] = []\n"
    kept, dropped = m.calibrate_fingerprints(fps, parent_blob)
    # 子串重合也算 parent 已有 —— 剔除且留名
    assert [f["raw"] for f in dropped] == ["columns: list[str] = []"]
    assert [f["raw"] for f in kept] == ["truly_novel_answer_only_line = compute(x)"]


def test_calibrate_keeps_all_when_parent_has_none():
    m = _load()
    fps = m.extract_fingerprints(
        "--- a/src/m.py\n+++ b/src/m.py\n"
        "+truly_novel_answer_only_line = compute(x)\n", [])
    kept, dropped = m.calibrate_fingerprints(fps, "unrelated parent text")
    assert dropped == [] and len(kept) == 1


# ------------------------------------------------------------------ P4 复用纪律
def test_measurement_helpers_are_reused_not_copied():
    m = _load()
    for name in ("digest_tree", "score_from_junit", "offline_env", "venv_env"):
        assert getattr(m, name).__module__ == "blind_attack_admission", (
            f"{name} 必须 import 盲攻测量驱动器的原件 —— "
            "复制一份会在原件改动后静默漂移")
