"""Staging / Worktree(RFC-008 §9.2)— 用户项目的隔离工作副本。

Git 项目:`git worktree add --detach`(固定 HEAD;这是 §9.2 明确
授权的对用户 .git 元数据的唯一写动作,remove 时清理)。
非 Git 项目:完整副本 + 逐文件 sha256 preimage 记录。
原项目本体在 APPLY_CONFIRMED(Gate E)之前零修改;Drift 检测基于
分析期记录的树指纹。
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

from repoproof.adoption.analysis.host_analyzer import (
    GIT_PROJECT,
    compute_tree_fingerprint,
    detect_host_mode,
)

_COPY_IGNORE = shutil.ignore_patterns(
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", "node_modules", ".DS_Store")


class StagingError(RuntimeError):
    pass


class StagingInfo(BaseModel):
    mode: str                      # git_worktree / full_copy
    project_path: str
    staging_path: str
    base_git_commit: str = ""      # git 模式
    base_tree_fingerprint: str = ""  # 双模式:Drift 基线
    file_hashes: dict[str, str] = {}  # 非 git 模式:相对路径 → sha256

    def to_dict(self) -> dict:
        return self.model_dump()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in {".git", ".venv", "venv", "__pycache__", ".pytest_cache",
                        ".ruff_cache", ".mypy_cache", "node_modules"} for part in rel.parts):
            continue
        if p.is_file() and p.name != ".DS_Store":
            out[str(rel)] = _sha256_file(p)
    return out


def create_staging(project_path: str | Path, staging_root: str | Path) -> StagingInfo:
    """创建隔离工作副本;绝不修改原项目内容(git 模式仅写 .git/worktrees 元数据)。"""
    src = Path(project_path).expanduser().resolve()
    if not src.is_dir():
        raise StagingError(f"项目路径不存在:{src}")
    dest_root = Path(staging_root).expanduser().resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / f"staging-{src.name}"
    if dest.exists():
        raise StagingError(f"staging 目录已存在,不覆盖:{dest}")

    fingerprint = str(compute_tree_fingerprint(src).value or "")
    if detect_host_mode(src).value == GIT_PROJECT:
        head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10, check=False)
        if head.returncode != 0:
            raise StagingError(f"无法读取项目 HEAD:{head.stderr.strip()[:200]}")
        proc = subprocess.run(
            ["git", "-C", str(src), "worktree", "add", "--detach", str(dest), "HEAD"],
            capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode != 0:
            raise StagingError(f"git worktree 创建失败:{proc.stderr.strip()[:300]}")
        return StagingInfo(mode="git_worktree", project_path=str(src), staging_path=str(dest),
                           base_git_commit=head.stdout.strip(),
                           base_tree_fingerprint=fingerprint)

    shutil.copytree(src, dest, ignore=_COPY_IGNORE)
    return StagingInfo(mode="full_copy", project_path=str(src), staging_path=str(dest),
                       base_tree_fingerprint=fingerprint,
                       file_hashes=_snapshot_hashes(src))


def detect_drift(info: StagingInfo) -> bool:
    """原项目自 staging 创建后是否发生变化(指纹失配 → Drift)。"""
    current = str(compute_tree_fingerprint(Path(info.project_path)).value or "")
    return current != info.base_tree_fingerprint


def remove_staging(info: StagingInfo) -> None:
    """清理 staging;只删除我们创建的目录,git 模式同时清 worktree 记录。"""
    dest = Path(info.staging_path)
    if info.mode == "git_worktree":
        subprocess.run(["git", "-C", info.project_path, "worktree", "remove",
                        "--force", str(dest)],
                       capture_output=True, text=True, timeout=60, check=False)
        subprocess.run(["git", "-C", info.project_path, "worktree", "prune"],
                       capture_output=True, text=True, timeout=30, check=False)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
