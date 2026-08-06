"""Adaptation zone freezing.

The agent's persistent products live in ``adaptation/``. After the
agent (or, in Gate 2.x, the scripted sequence) finishes, the zone is
FROZEN: an AdaptationManifest inventories every file (path, sha256,
line count), computes a deterministic tree root hash, and the zone is
made physically read-only. Verifiers consume ONLY the frozen manifest
+ content hashes, and re-check the tree hash before and after
verification. ``adaptation_present`` is derived here — never a caller
supplied bool.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from repoproof.domain.models import AdaptationManifest, Budgets
from repoproof.harness.oracle_guard import make_read_only


class PatchBudgetExceeded(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _tree_root(files: list[dict]) -> str:
    canon = json.dumps(
        [{"path": f["path"], "sha256": f["sha256"]} for f in files],
        sort_keys=True,
    )
    return hashlib.sha256(canon.encode()).hexdigest()


def inventory(adaptation_dir: Path) -> AdaptationManifest:
    """Non-freezing inventory (also used to re-verify a frozen zone)."""
    files: list[dict] = []
    total_lines = 0
    root = Path(adaptation_dir)
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise PatchBudgetExceeded(f"symlink not allowed in adaptation zone: {p}")
        if not p.is_file():
            continue
        data = p.read_bytes()
        lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        total_lines += lines
        files.append(
            {
                "path": str(p.relative_to(root)),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "lines": lines,
            }
        )
    return AdaptationManifest(
        files=files,
        total_files=len(files),
        total_lines=total_lines,
        tree_root_sha256=_tree_root(files),
        frozen=False,
    )


def freeze_adaptation(adaptation_dir: Path, budgets: Budgets) -> AdaptationManifest:
    """Inventory + patch-budget enforcement + physical write-lock.

    Every added line counts against ``max_patch_lines`` (versus the
    empty baseline zone, all content is additions).
    """
    manifest = inventory(adaptation_dir)
    if manifest.total_files > budgets.max_patch_files:
        raise PatchBudgetExceeded(
            f"adaptation files {manifest.total_files} > max_patch_files {budgets.max_patch_files}"
        )
    if manifest.total_lines > budgets.max_patch_lines:
        raise PatchBudgetExceeded(
            f"adaptation lines {manifest.total_lines} > max_patch_lines {budgets.max_patch_lines}"
        )
    make_read_only(adaptation_dir)
    return manifest.model_copy(update={"frozen": True})


def verify_frozen(adaptation_dir: Path, manifest: AdaptationManifest) -> tuple[bool, str]:
    """Re-inventory and compare against the frozen manifest."""
    current = inventory(adaptation_dir)
    if current.tree_root_sha256 != manifest.tree_root_sha256:
        return False, (
            f"adaptation tree changed: {current.tree_root_sha256[:12]} != frozen {manifest.tree_root_sha256[:12]}"
        )
    return True, "adaptation tree matches frozen manifest"
