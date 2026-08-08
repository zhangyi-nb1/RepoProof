"""宿主快照排除 + 合成替身 + PII 出口扫描(Phase 0 ③)。

钉死:密钥/运行态/PII 载体不进快照;宿主需要的 PII 文件被合成替身
顶替(真实内容零外泄);排除清单漏项由出口扫描兜底报警。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.harness.host_snapshot import (
    SnapshotError,
    prepare_host_snapshot,
    scan_for_pii,
)


def _fake_host(tmp_path: Path) -> Path:
    h = tmp_path / "host_copy"
    (h / "app").mkdir(parents=True)
    (h / "app" / "main.py").write_text("X = 1\n", encoding="utf-8")
    (h / "tests").mkdir()
    (h / "tests" / "test_x.py").write_text("def test_x(): assert True\n", encoding="utf-8")
    # 应被排除的东西
    (h / ".env").write_text("OPENAI_API_KEY=sk-REAL-SECRET\n", encoding="utf-8")
    (h / "gap_store.json.lock").write_text("", encoding="utf-8")
    (h / "chroma_db").mkdir()
    (h / "chroma_db" / "vectors.bin").write_text("simulated 真实简历向量", encoding="utf-8")
    (h / "_local_notes").mkdir()
    (h / "_local_notes" / "private.md").write_text("私密", encoding="utf-8")
    (h / "__pycache__").mkdir()
    (h / "__pycache__" / "x.pyc").write_text("junk", encoding="utf-8")
    # 真实 PII 文件(会被合成替身覆盖)
    (h / "user_profile.md").write_text(
        "姓名:张三\n手机:13800138000\n邮箱:real.person@gmail.com\n", encoding="utf-8")
    return h


def test_snapshot_excludes_secrets_runtime_and_pii(tmp_path: Path) -> None:
    src = _fake_host(tmp_path)
    out = prepare_host_snapshot(src, tmp_path / "snap")
    snap = tmp_path / "snap"

    assert (snap / "app" / "main.py").exists() and (snap / "tests" / "test_x.py").exists()
    for gone in (".env", "gap_store.json.lock", "chroma_db/vectors.bin",
                 "_local_notes/private.md", "__pycache__/x.pyc"):
        assert not (snap / gone).exists(), gone
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in snap.rglob("*") if p.is_file())
    assert "sk-REAL-SECRET" not in blob        # 密钥零外泄
    assert "真实简历向量" not in blob          # 向量库零外泄
    assert out["excluded"] and "user_profile.md" in out["substituted"]


def test_pii_files_replaced_by_synthetic_substitutes(tmp_path: Path) -> None:
    src = _fake_host(tmp_path)
    prepare_host_snapshot(src, tmp_path / "snap")
    body = (tmp_path / "snap" / "user_profile.md").read_text(encoding="utf-8")
    assert "张三" not in body and "13800138000" not in body
    assert "real.person@gmail.com" not in body
    assert "合成测试档案" in body and "test@example.invalid" in body  # 文件仍在,内容是合成的


def test_exit_scan_catches_missed_exclusion(tmp_path: Path) -> None:
    """纵深防御:排除清单漏项时,出口扫描必须报警(不静默放行)。"""
    src = _fake_host(tmp_path)
    (src / "leaked_notes.md").write_text(
        "联系人 13912345678,邮箱 someone@company.com\n", encoding="utf-8")
    prepare_host_snapshot(src, tmp_path / "snap")  # 该文件不在排除清单 → 进了快照
    hits = scan_for_pii(tmp_path / "snap")
    kinds = {h["kind"] for h in hits}
    assert "手机号" in kinds or "邮箱" in kinds
    assert any(h["path"] == "leaked_notes.md" for h in hits)
    assert all("13912345678" not in h["sample"] for h in hits)  # 报警本身不复述 PII


def test_clean_snapshot_scans_clean_and_dst_must_be_empty(tmp_path: Path) -> None:
    src = _fake_host(tmp_path)
    prepare_host_snapshot(src, tmp_path / "snap")
    assert scan_for_pii(tmp_path / "snap") == []  # 合成替身用 example.invalid,不误报
    with pytest.raises(SnapshotError, match="非空"):
        prepare_host_snapshot(src, tmp_path / "snap")
    with pytest.raises(SnapshotError, match="不存在"):
        prepare_host_snapshot(tmp_path / "nope", tmp_path / "snap2")


def test_git_dir_is_all_or_nothing(tmp_path: Path) -> None:
    """真实副本实测教训:`logs` 模式误伤 `.git/logs`(reflog),
    部分排除会破坏 git 完整性。.git 必须整体保留或整体排除。"""
    src = _fake_host(tmp_path)
    g = src / ".git"
    (g / "logs" / "refs").mkdir(parents=True)
    (g / "logs" / "HEAD").write_text("reflog\n", encoding="utf-8")
    (g / "config").write_text("[core]\n", encoding="utf-8")

    prepare_host_snapshot(src, tmp_path / "keep")
    assert (tmp_path / "keep" / ".git" / "logs" / "HEAD").exists()  # 不被 logs 模式误伤
    assert (tmp_path / "keep" / ".git" / "config").exists()

    prepare_host_snapshot(src, tmp_path / "drop", extra_excludes=(".git",))
    assert not (tmp_path / "drop" / ".git").exists()  # 显式排除则整体不进
