"""Gate E(RFC-008 §9.3/9.5)— Apply/Rollback 钉死测试(仅 fixture 项目)。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repoproof.adoption.analysis.host_analyzer import compute_tree_fingerprint
from repoproof.adoption.delivery.apply import (
    CONFIRM_TOKEN,
    ApplyError,
    ConfirmationMissing,
    DriftDetected,
    apply_confirmed,
    rollback,
)
from repoproof.adoption.delivery.apply_manifest import build_apply_manifest


def _fixture(tmp_path: Path):
    """fixture 用户项目 + staging 副本(1 改 1 增 1 无关)。"""
    proj = tmp_path / "userproj"
    proj.mkdir()
    (proj / "app.py").write_text("print('v1')\n", encoding="utf-8")
    (proj / "unrelated.txt").write_text("keep me\n", encoding="utf-8")
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "app.py").write_text("print('v2')\n", encoding="utf-8")
    (staged / "unrelated.txt").write_text("keep me\n", encoding="utf-8")
    (staged / "adopted").mkdir()
    (staged / "adopted" / "adapter.py").write_text("def run(v): return v\n", encoding="utf-8")
    manifest = build_apply_manifest(proj, staged, base_git_commit="")
    fp = str(compute_tree_fingerprint(proj).value)
    return proj, staged, manifest, fp


def _ok_kwargs(fp: str, backups: Path) -> dict:
    return dict(backup_dir=backups, verdict="PASS_ADAPTED",
                baseline_fingerprint=fp, user_viewed_files=True,
                user_viewed_diff=True, confirm_token=CONFIRM_TOKEN,
                apply_timestamp="2026-08-08T00:00:00Z")


def test_apply_success_and_manifest_state(tmp_path: Path) -> None:
    proj, staged, m, fp = _fixture(tmp_path)
    out = apply_confirmed(proj, staged, m, **_ok_kwargs(fp, tmp_path / "bk"))
    assert out.result_state == "APPLIED"
    assert (proj / "app.py").read_text(encoding="utf-8") == "print('v2')\n"
    assert (proj / "adopted" / "adapter.py").exists()
    assert (proj / "unrelated.txt").read_text(encoding="utf-8") == "keep me\n"
    assert (tmp_path / "bk" / "apply_manifest.applied.json").exists()


def test_drift_blocks_apply(tmp_path: Path) -> None:
    proj, staged, m, fp = _fixture(tmp_path)
    (proj / "drifted.py").write_text("x", encoding="utf-8")  # 确认后项目又变了
    with pytest.raises(DriftDetected, match="发生了变化"):
        apply_confirmed(proj, staged, m, **_ok_kwargs(fp, tmp_path / "bk"))
    assert (proj / "app.py").read_text(encoding="utf-8") == "print('v1')\n"  # 未动


def test_user_refusal_paths(tmp_path: Path) -> None:
    proj, staged, m, fp = _fixture(tmp_path)
    kw = _ok_kwargs(fp, tmp_path / "bk")
    for field, bad in (("user_viewed_files", False), ("user_viewed_diff", False),
                       ("confirm_token", "我同意")):
        with pytest.raises(ConfirmationMissing):
            apply_confirmed(proj, staged, m, **{**kw, field: bad})
    with pytest.raises(ApplyError, match="不满足写回条件"):
        apply_confirmed(proj, staged, m, **{**kw, "verdict": "FAIL"})
    assert (proj / "app.py").read_text(encoding="utf-8") == "print('v1')\n"


def test_midway_failure_auto_rolls_back(tmp_path: Path) -> None:
    """staging 在确认后被篡改 → 第二笔写入前校验失败 → 已写部分自动回滚。"""
    proj, staged, m, fp = _fixture(tmp_path)
    # 账本生成后篡改 staging 的 app.py(after_hash 失配;adapter 先写成功)
    (staged / "app.py").write_text("print('tampered')\n", encoding="utf-8")
    with pytest.raises(ApplyError, match="after_hash 不符"):
        apply_confirmed(proj, staged, m, **_ok_kwargs(fp, tmp_path / "bk"))
    # 项目回到 apply 前状态:新建的 adapter 被清掉,原文件未动
    assert not (proj / "adopted" / "adapter.py").exists()
    assert (proj / "app.py").read_text(encoding="utf-8") == "print('v1')\n"


def test_rollback_success_idempotent_and_scoped(tmp_path: Path) -> None:
    proj, staged, m, fp = _fixture(tmp_path)
    backups = tmp_path / "bk"
    apply_confirmed(proj, staged, m, **_ok_kwargs(fp, backups))
    out = rollback(proj, m, backup_dir=backups)
    assert out.result_state == "ROLLED_BACK"
    assert (proj / "app.py").read_text(encoding="utf-8") == "print('v1')\n"
    assert not (proj / "adopted" / "adapter.py").exists()
    assert (proj / "unrelated.txt").exists()  # 无关文件永不删除
    # 幂等:再滚一次不报错、状态不变
    out2 = rollback(proj, m, backup_dir=backups)
    assert out2.result_state == "ROLLED_BACK"
    assert (proj / "unrelated.txt").exists()


def test_rollback_refuses_corrupt_preimage(tmp_path: Path) -> None:
    proj, staged, m, fp = _fixture(tmp_path)
    backups = tmp_path / "bk"
    apply_confirmed(proj, staged, m, **_ok_kwargs(fp, backups))
    (backups / "app.py").write_text("corrupted", encoding="utf-8")
    with pytest.raises(ApplyError, match="preimage 校验失败"):
        rollback(proj, m, backup_dir=backups)


def test_path_traversal_and_symlink_rejected(tmp_path: Path) -> None:
    proj, staged, m, fp = _fixture(tmp_path)
    m.files_created.append("../escape.py")
    m.after_hashes["../escape.py"] = "0" * 64
    with pytest.raises(ApplyError, match="非法目标路径"):
        apply_confirmed(proj, staged, m, **_ok_kwargs(fp, tmp_path / "bk"))
    # 符号链接目录:项目内 adopted → 项目外
    (tmp_path / "second").mkdir()
    proj2, staged2, m2, _fp2 = _fixture(tmp_path / "second")
    outside = tmp_path / "outside"
    outside.mkdir()
    (proj2 / "adopted").symlink_to(outside)
    fp2 = str(compute_tree_fingerprint(proj2).value)
    m2b = build_apply_manifest(proj2, staged2)
    with pytest.raises(ApplyError, match="符号链接"):
        apply_confirmed(proj2, staged2, m2b, **_ok_kwargs(fp2, tmp_path / "bk2"))
    assert not any(outside.iterdir())  # 项目外目录零写入


def test_apply_is_atomic_per_file_no_tmp_left(tmp_path: Path) -> None:
    proj, staged, m, fp = _fixture(tmp_path)
    apply_confirmed(proj, staged, m, **_ok_kwargs(fp, tmp_path / "bk"))
    assert not list(proj.rglob(".rp_tmp_*"))


def test_no_recursive_delete_action_possible(tmp_path: Path) -> None:
    """结构性:回滚动作只有两种;伪造第三种 → 拒绝执行。"""
    proj, staged, m, fp = _fixture(tmp_path)
    backups = tmp_path / "bk"
    apply_confirmed(proj, staged, m, **_ok_kwargs(fp, backups))
    from repoproof.adoption.delivery.apply_manifest import RollbackAction

    m.rollback_actions.append(RollbackAction(kind="rmtree", path="."))
    with pytest.raises(ApplyError, match="未知回滚动作"):
        rollback(proj, m, backup_dir=backups)
    assert (proj / "unrelated.txt").exists()


def test_apply_source_has_no_shutil_rmtree_on_project(tmp_path: Path) -> None:
    """静态钉死:apply.py 对用户项目没有任何递归删除调用。"""
    src = (Path(__file__).resolve().parent.parent / "src" / "repoproof" /
           "adoption" / "delivery" / "apply.py").read_text(encoding="utf-8")
    assert "rmtree" not in src.replace("未知回滚动作", "")
    assert "unlink(missing_ok=True)" in src  # 仅逐文件、幂等


@pytest.mark.skipif(os.name != "posix", reason="posix only")
def test_created_file_parent_dirs_inside_project_only(tmp_path: Path) -> None:
    proj, staged, m, fp = _fixture(tmp_path)
    apply_confirmed(proj, staged, m, **_ok_kwargs(fp, tmp_path / "bk"))
    created = proj / "adopted" / "adapter.py"
    assert created.resolve().is_relative_to(proj.resolve())
