"""ApplyManifest(RFC-008 §9.4)— 写回用户项目的完整可回滚账本。

Gate C 只负责「构建」manifest(staging 与原项目的差异 + 回滚动作);
真正执行 Apply/Rollback 在 Gate E。铁律先钉进数据结构:
- 只记录、只允许恢复 manifest 中列出的文件;
- 禁止任何递归删除用户目录的动作(结构上不存在这种 action);
- 每个文件带 before/after sha256,回滚校验成对出现。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel

RESULT_EXPORT_READY = "EXPORT_READY"
RESULT_STAGED = "INTEGRATION_STAGED"
RESULT_APPLIED = "APPLIED"
RESULT_ROLLED_BACK = "ROLLED_BACK"
RESULT_DRIFT = "PROJECT_DRIFT_DETECTED"

_SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache",
               ".ruff_cache", ".mypy_cache", "node_modules"}


class RollbackAction(BaseModel):
    kind: str          # delete_created / restore_preimage
    path: str          # 相对用户项目根
    preimage_sha256: str = ""  # restore_preimage 必填


class ApplyManifest(BaseModel):
    base_project_path_fingerprint: str
    base_git_commit: str = ""
    base_tree_hash: str = ""
    files_created: list[str] = []
    files_modified: list[str] = []
    files_deleted: list[str] = []      # 结构保留;RepoProof 产品线不生成删除动作
    before_hashes: dict[str, str] = {}
    after_hashes: dict[str, str] = {}
    dependency_changes: list[str] = []
    commands_executed: list[str] = []
    apply_timestamp: str = ""
    rollback_actions: list[RollbackAction] = []
    result_state: str = RESULT_EXPORT_READY

    def to_dict(self) -> dict:
        return self.model_dump()


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _files(root: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in _SKIP_PARTS for part in rel.parts) or p.name == ".DS_Store":
            continue
        if p.is_file():
            out[str(rel)] = p
    return out


def build_apply_manifest(
    original_root: Path,
    staged_root: Path,
    *,
    base_git_commit: str = "",
    base_tree_hash: str = "",
    dependency_changes: list[str] | None = None,
) -> ApplyManifest:
    """对比 原项目 vs staging 副本 → 写回账本(不执行任何写)。

    staging 中被删除的文件不会生成删除动作——产品线禁止代表用户删
    文件;此类差异记录在 files_deleted 供人工审查,回滚动作只覆盖
    created/modified。
    """
    orig = _files(original_root)
    staged = _files(staged_root)
    created = sorted(set(staged) - set(orig))
    deleted = sorted(set(orig) - set(staged))
    common = sorted(set(orig) & set(staged))

    before = {rel: _sha256_file(orig[rel]) for rel in common}
    after: dict[str, str] = {}
    modified: list[str] = []
    for rel in common:
        h = _sha256_file(staged[rel])
        if h != before[rel]:
            modified.append(rel)
            after[rel] = h
    for rel in created:
        after[rel] = _sha256_file(staged[rel])
    before = {rel: h for rel, h in before.items() if rel in modified}

    rollback = [RollbackAction(kind="delete_created", path=rel) for rel in created]
    rollback += [RollbackAction(kind="restore_preimage", path=rel,
                                preimage_sha256=before[rel]) for rel in modified]

    fingerprint = hashlib.sha256(
        "\n".join(f"{r}\0{h}" for r, h in sorted(after.items())).encode()).hexdigest()
    return ApplyManifest(
        base_project_path_fingerprint=hashlib.sha256(
            str(original_root.resolve()).encode()).hexdigest()[:16],
        base_git_commit=base_git_commit,
        base_tree_hash=base_tree_hash or fingerprint,
        files_created=created,
        files_modified=modified,
        files_deleted=deleted,
        before_hashes=before,
        after_hashes=after,
        dependency_changes=list(dependency_changes or []),
        rollback_actions=rollback,
    )
