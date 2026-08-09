"""Upstream Provenance 最小版(Phase 0 ⑤)——语义替代底线钉死。

历史实例:rank_bm25 任务中 agent 手写 335 行 BM25 而非采用上游
(SEMANTIC_SUBSTITUTION)。本检查钉住底线:改动文件里必须存在对
目标库的真实 import。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.verification.provenance import FAILURE_TYPE, check_upstream_provenance


def test_real_import_forms_all_accepted(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("import casbin\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from casbin import Enforcer\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("    import casbin.util as u\n", encoding="utf-8")
    for f in ("a.py", "b.py", "c.py"):
        out = check_upstream_provenance(tmp_path, [f], "casbin")
        assert out["ok"] and out["imports"][0]["file"] == f


def test_reimplementation_is_flagged(tmp_path: Path) -> None:
    """无 import = 疑似自行重写 → 典型化失败(非静默通过)。"""
    (tmp_path / "adapter.py").write_text(
        "def enforce(sub, obj, act):\n"
        "    return obj.get('owner_id') == sub\n", encoding="utf-8")
    out = check_upstream_provenance(tmp_path, ["adapter.py"], "casbin")
    assert not out["ok"] and FAILURE_TYPE in out["reason"] and "casbin" in out["reason"]


def test_similar_module_names_do_not_false_pass(tmp_path: Path) -> None:
    """`import casbin_like` 不能冒充 `casbin`;注释/字符串提及也不算。"""
    (tmp_path / "x.py").write_text(
        "import casbin_like\n# import casbin\nS = 'from casbin import Enforcer'\n",
        encoding="utf-8")
    assert not check_upstream_provenance(tmp_path, ["x.py"], "casbin")["ok"]


def test_non_python_and_missing_files_ignored(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("import casbin\n", encoding="utf-8")
    out = check_upstream_provenance(tmp_path, ["notes.md", "gone.py"], "casbin")
    assert not out["ok"]  # 非 .py 不计入证据,仍报语义替代嫌疑
