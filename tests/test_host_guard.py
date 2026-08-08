"""主目录硬护栏 + 保护目录指纹对账(Phase 0 ①,TESTPLAN-V2 §4 第 1/6 层)。

钉死:路径变体(大小写/软链/~/子路径)全拦截;apply/stage/rollback
三个写入口无旁路;指纹对 untracked 新增、内容改动、git refs 变动
全部报警;无改动则对账通过。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repoproof.harness.host_guard import (
    HostGuardError,
    assert_writable_target,
    dir_fingerprint,
    is_protected,
    snapshot_protected,
    verify_protected_unchanged,
)


def _prot(tmp_path: Path) -> tuple[Path, list[str]]:
    real = tmp_path / "XIANGMU" / "offerclaw"
    (real / "src").mkdir(parents=True)
    (real / "src" / "app.py").write_text("X = 1\n", encoding="utf-8")
    import os

    return real, [os.path.realpath(str(real)).lower()]


def test_path_variants_all_blocked(tmp_path: Path) -> None:
    real, prot = _prot(tmp_path)
    assert is_protected(real, prot)
    assert is_protected(str(real).upper(), prot)  # APFS 大小写不敏感
    assert is_protected(real / "src" / "app.py", prot)  # 子路径
    link = tmp_path / "shortcut"
    link.symlink_to(real)  # 软链指向保护目录
    assert is_protected(link, prot)
    assert is_protected(link / "src", prot)
    # 相对路径(经 cwd 解析后命中)
    import os

    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert is_protected("XIANGMU/offerclaw/src", prot)
    finally:
        os.chdir(old)
    # 非保护路径放行
    assert not is_protected(tmp_path / "RepoProofBench" / "copy", prot)
    with pytest.raises(HostGuardError, match="无旁路"):
        assert_writable_target(real, purpose="测试写入", protected=prot)


def test_default_protected_covers_real_dev_dirs() -> None:
    assert is_protected("~/Desktop/XIANGMU/offerclaw")
    assert is_protected("~/Desktop/XIANGMU/OfferClaw/anything")  # 大小写变体
    assert is_protected("~/Desktop/XIANGMU/RepoProof/src")
    assert not is_protected("~/RepoProofBench/offerclaw-t1-fastapi-mcp")


def test_apply_stage_rollback_have_no_bypass(tmp_path: Path, monkeypatch) -> None:
    """三个写入口逐一验证:命中保护目录即拒,发生在任何其他检查之前。"""
    monkeypatch.setenv("REPOPROOF_PROTECTED_DIRS", str(tmp_path / "protected_proj"))
    proj = tmp_path / "protected_proj"
    proj.mkdir()

    from repoproof.adoption.delivery.apply import apply_confirmed, rollback
    from repoproof.adoption.delivery.apply_flow import stage_bundle
    from repoproof.adoption.delivery.apply_manifest import ApplyManifest

    with pytest.raises(HostGuardError):
        stage_bundle(proj, tmp_path / "nonexistent_bundle", tmp_path / "stg")
    m = ApplyManifest(base_project_path_fingerprint="fp")
    with pytest.raises(HostGuardError):
        apply_confirmed(proj, tmp_path, m, backup_dir=tmp_path / "b",
                        verdict="PASS_ADAPTED", baseline_fingerprint="x",
                        user_viewed_files=True, user_viewed_diff=True,
                        confirm_token="错的也无所谓——护栏必须先拦",
                        apply_timestamp="t")
    with pytest.raises(HostGuardError):
        rollback(proj, m, backup_dir=tmp_path / "b")


def test_fingerprint_detects_untracked_content_and_git_refs(tmp_path: Path) -> None:
    real, prot = _prot(tmp_path)
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1"]):
        subprocess.run(["git", "-C", str(real), *args], check=True)

    before = snapshot_protected(prot)
    assert prot[0] in before and before[prot[0]]["files"] >= 1
    assert verify_protected_unchanged(before, prot)["ok"]  # 无改动 → 通过

    (real / "sneaky_untracked.txt").write_text("x", encoding="utf-8")  # untracked 新增
    out = verify_protected_unchanged(before, prot)
    assert not out["ok"] and out["mismatches"][0]["field"] == "tree"

    (real / "sneaky_untracked.txt").unlink()
    subprocess.run(["git", "-C", str(real), "-c", "user.email=t@t", "-c",
                    "user.name=t", "commit", "-qm", "v2", "--allow-empty"], check=True)
    out2 = verify_protected_unchanged(before, prot)  # 历史/refs 被动 → 报警
    assert not out2["ok"] and any(m["field"] == "git_refs" for m in out2["mismatches"])


def test_fingerprint_ignores_noise_dirs(tmp_path: Path) -> None:
    real, prot = _prot(tmp_path)
    before = dir_fingerprint(real)
    (real / "__pycache__").mkdir()
    (real / "__pycache__" / "junk.pyc").write_text("x", encoding="utf-8")
    (real / ".venv").mkdir()
    (real / ".venv" / "lib.py").write_text("x", encoding="utf-8")
    assert dir_fingerprint(real)["tree"] == before["tree"]  # 噪声目录不误报
