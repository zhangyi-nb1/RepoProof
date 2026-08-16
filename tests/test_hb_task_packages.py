"""HB-PCDELTA-1 任务包一致性钉死(P 系)。

任务包由 scripts/build_hb1_task_packages.py 唯一产出。这里守的是包与包、
包与源之间**不许漂移**的关系,以及"答案进不了公开仓"的铁律。物化件
(post_tests / answer patch)在新克隆上合法缺席 —— 只在在场时核对内容,
缺席时由 oracle 驱动器 H0 在运行期 fail-closed(tests/test_delta_oracle_lib
U3 已钉),这里只钉 gitignore 真的把它们挡在 git 外(P6)。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PKGS = ["hb1_click_3581", "hb1_click_3407", "hb1_sqlglot_8042"]
CIDS = {"hb1_click_3581": "click-3581", "hb1_click_3407": "click-3407",
        "hb1_sqlglot_8042": "sqlglot-8042"}
TASKS = REPO / "benchmarks/v2/tasks"

sys.path.insert(0, str(REPO / "src"))
from repoproof.runner.host_guided import (  # noqa: E402
    HostContract,
    _expected_regression_passed,
)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_p1_oracle_lib_copies_byte_equal_to_source():
    src = REPO / "scripts/delta_oracle_lib.py"
    for pkg in PKGS:
        copy = TASKS / pkg / "oracle/delta_oracle_lib.py"
        assert copy.is_file(), f"{pkg} 缺 oracle 驱动器副本"
        assert _sha(copy) == _sha(src), \
            f"{pkg} 的驱动器副本与 scripts/ 源漂移 —— 判卷器不一致,重跑生成器"


def test_p2_wrapper_and_conftest_identical_across_packages():
    for rel in ("oracle/test_hidden_delta.py", "oracle/conftest.py"):
        shas = {_sha(TASKS / pkg / rel) for pkg in PKGS}
        assert len(shas) == 1, f"{rel} 在三个任务包间不一致"


def test_p3_contracts_load_and_pin_prereg_values():
    for pkg in PKGS:
        c, _ = HostContract.load(TASKS / pkg / "contract.yaml")
        assert c.task_id.startswith("hb1-")          # 台账阶段前缀隔离
        assert c.prompt_profile == "hb-delta-v1"
        assert c.source_repo is None                 # G1:宿主即上游
        assert c.host.pii_scan_profile == "public-oss-tree"
        assert c.host.oracle_env_sanitized is True   # 审查 blocking [1a]
        b = c.budgets                                 # 预注册 §9 冻结值
        assert (b.semantics, b.max_rounds, b.max_model_calls, b.max_commands,
                b.max_patch_files, b.max_patch_lines, b.max_wall_time_minutes,
                b.max_input_tokens_total, b.max_output_tokens_total) == (
            "per_round", 3, 30, 100, 15, 1500, 60, 600000, 80000)
        assert "INSTRUMENT_TAMPERED" in c.failure_taxonomy_expected
        # 公开面与回归是同一套件,只差解释器写法约定(公开命令以 "python"
        # 开头供 _public_argv 剥去再前置会话 venv;回归命令直接 exec)
        assert c.acceptance.public_test_command[0] == "python"
        assert c.acceptance.public_test_command[1:] == c.host.regression_command[1:]
        assert _expected_regression_passed(c.host.regression_baseline) > 0
        stmt = (TASKS / pkg / "statement.md").read_text(encoding="utf-8")
        assert c.capability.statement == stmt        # 题面原文,一字不动


def test_p4_manifest_nodes_match_frozen_hygiene_evidence():
    for pkg in PKGS:
        m = json.loads((TASKS / pkg / "oracle/delta_manifest.json")
                       .read_text(encoding="utf-8"))
        hyg = json.loads((REPO / "docs/evidence/d5_hunt/hygiene" /
                          f"{CIDS[pkg]}.json").read_text(encoding="utf-8"))
        assert m["delta_nodes"] == hyg["delta_nodes"], \
            f"{pkg} 的 delta 节点集与准入冻结件不一致"
        assert m["post_files"], f"{pkg} manifest 没有 post 文件清单"
        # 物化件在场才核内容;缺席由 H0 运行期拒判(U3),不在这里造假绿
        for item in m["post_files"]:
            f = TASKS / pkg / "oracle/post_tests" / item["path"]
            if f.is_file():
                assert _sha(f) == item["sha256"], f"{pkg}/{item['path']} 物化件漂移"


def test_p4b_manifest_pins_guard_and_collection_subtree():
    """守卫子树与判卷收集子树同取一个字段(审查 blocking [1b]);根级量具面
    必须含解释器启动面,且出题态是 ABSENT(有内容 = 出题时就带着后门)。"""
    for pkg in PKGS:
        m = json.loads((TASKS / pkg / "oracle/delta_manifest.json")
                       .read_text(encoding="utf-8"))
        assert m["tests_subdir"] == "tests"
        g = m["guarded_root_files"]
        for name in ("conftest.py", "pyproject.toml", "setup.cfg", "setup.py",
                     "pytest.ini", "tox.ini", "sitecustomize.py",
                     "usercustomize.py"):
            assert name in g, f"{pkg} 守卫面漏了 {name}"
        assert g["sitecustomize.py"] == "ABSENT"
        assert g["usercustomize.py"] == "ABSENT"


def test_p5_negative_controls_shape():
    for pkg in PKGS:
        null_patch = (TASKS / pkg / "controls/nc_null_submission/apply.patch"
                      ).read_text(encoding="utf-8")
        assert "RP_NULL_SUBMISSION" in null_patch
        assert null_patch.count("diff --git") == 1   # 惰性提交只动一个标记文件
        sab = (TASKS / pkg / "controls/nc_regression_break/sabotage.patch"
               ).read_text(encoding="utf-8")
        assert "rp-nc-sabotage" in sab
        assert sab.count("diff --git") == 1          # 窄破坏只动一个靶文件
        assert "tests/" not in sab.split("\n")[0]    # 靶不许是测试文件
        # 负控三(审查 blocking [1a] 的原样复现):零实现 + 根级 sitecustomize
        tamper = (TASKS / pkg / "controls/nc_instrument_tamper/apply.patch"
                  ).read_text(encoding="utf-8")
        assert tamper.count("diff --git") == 1
        assert "b/sitecustomize.py" in tamper
        assert "runtest" in tamper                   # 载荷是真伪造,不是空壳
        assert "src/" not in tamper and "sqlglot/" not in tamper  # 零实现


@pytest.mark.parametrize("rel", [
    "oracle/post_tests/tests/anything.py",
    "controls/positive/apply.patch",
    "controls/nc_regression_break/apply.patch",
])
def test_p6_materialized_answer_paths_are_gitignored(rel):
    """答案不进公开仓(repo_scan 铁律)—— 用 git 自己回答,不看 .gitignore 文本。"""
    for pkg in PKGS:
        r = subprocess.run(
            ["git", "-C", str(REPO), "check-ignore", "-q",
             f"benchmarks/v2/tasks/{pkg}/{rel}"],
            capture_output=True)
        assert r.returncode == 0, f"{pkg}/{rel} 没被 gitignore 覆盖 —— 答案会进公开仓"


def test_p7_generator_refuses_round1_polluted_evidence(tmp_path, monkeypatch):
    """证据缺第二轮标记(attacker_residue)= 攻击者树上量的数,拒生成。"""
    sys.path.insert(0, str(REPO / "scripts"))
    import build_hb1_task_packages as g
    fake = tmp_path / "prepare-hb1.json"
    fake.write_text(json.dumps({"hosts": {
        "click-3581": {"baseline": {"passed": 1, "skipped": 0}},
        "click-3407": {"baseline": {"passed": 1, "skipped": 0}},
        "sqlglot-8042": {"baseline": {"passed": 1, "skipped": 0}},
    }}), encoding="utf-8")
    monkeypatch.setattr(g, "EVIDENCE", fake)
    with pytest.raises(SystemExit, match="attacker_residue"):
        g._load_round2_evidence()


def test_p8_answer_patch_filter_drops_all_test_segments():
    """正控 patch 过滤是纯函数:tests/** 的段必须整段消失(隐藏判据不进正控)。"""
    sys.path.insert(0, str(REPO / "scripts"))
    from build_hb1_task_packages import _filter_answer_patch
    patch = ("diff --git a/src/x.py b/src/x.py\n--- a/src/x.py\n+++ b/src/x.py\n"
             "@@ -1 +1 @@\n-o\n+n\n"
             "diff --git a/tests/test_x.py b/tests/test_x.py\n"
             "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1 +1 @@\n-a\n+b\n"
             "diff --git a/docs/y.md b/docs/y.md\n--- a/docs/y.md\n+++ b/docs/y.md\n"
             "@@ -1 +1 @@\n-c\n+d\n")
    out = _filter_answer_patch(patch)
    assert "tests/test_x.py" not in out
    assert "src/x.py" in out and "docs/y.md" in out


def test_p6b_committed_oracle_carries_no_upstream_test_bodies():
    """入 git 的 oracle 件里不得有上游测试函数体(manifest 只许载 sha256)。"""
    for pkg in PKGS:
        m = (TASKS / pkg / "oracle/delta_manifest.json").read_text(encoding="utf-8")
        for banned in ("def test_custom_version_option", "def test_chained_pivots",
                       "def test_param_type_input_parameter"):
            assert banned not in m
