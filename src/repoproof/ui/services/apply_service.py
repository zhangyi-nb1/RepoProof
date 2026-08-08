"""Apply 服务(Gate E)— UI 与 delivery 写回层之间的薄编排。

页面零写调用;真实写动作全部发生在 core(delivery.apply / apply_flow),
且必须带齐三要素(清单已看、Diff 已看、逐字令牌)。staging 与
preimage 备份都放在 RepoProof 工作区(runs/_apply/),用户项目在
确认写回前保持只读。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def stage(root: Path, project_path: str, bundle_dir: str) -> dict:
    from repoproof.adoption.delivery.apply_flow import (
        ApplyFlowError,
        diff_preview,
        stage_bundle,
    )
    from repoproof.adoption.delivery.staging import StagingError

    if not (project_path or "").strip():
        return {"ok": False, "error": "请先填写你的项目路径。"}
    staging_root = root / "runs" / "_apply" / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    try:
        info, manifest, bm = stage_bundle(project_path, bundle_dir, staging_root)
    except (ApplyFlowError, StagingError) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "staging": info.to_dict(),
        "manifest": manifest.to_dict(),
        "verdict": bm.get("verdict"),
        "created": manifest.files_created,
        "modified": manifest.files_modified,
        "deps": manifest.dependency_changes,
        "diff": diff_preview(info.project_path, info.staging_path, manifest),
        "backup_dir": str(staging_root / "preimages"),
    }


def apply(root: Path, staged_state: dict, *, viewed_files: bool,
          viewed_diff: bool, token: str) -> dict:
    from repoproof.adoption.delivery.apply import (
        ApplyError,
        apply_confirmed,
    )
    from repoproof.adoption.delivery.apply_manifest import ApplyManifest
    from repoproof.adoption.delivery.staging import StagingInfo

    info = StagingInfo.model_validate(staged_state["staging"])
    manifest = ApplyManifest.model_validate(staged_state["manifest"])
    try:
        out = apply_confirmed(
            info.project_path, info.staging_path, manifest,
            backup_dir=staged_state["backup_dir"],
            verdict=str(staged_state.get("verdict")),
            baseline_fingerprint=info.base_tree_fingerprint,
            user_viewed_files=viewed_files,
            user_viewed_diff=viewed_diff,
            confirm_token=token,
            apply_timestamp=datetime.now(UTC).isoformat(),
        )
    except ApplyError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "manifest": out.to_dict(),
            "project": info.project_path,
            "backup_dir": staged_state["backup_dir"],
            "note": f"已写入你的项目({len(out.files_created)} 新增 / "
                    f"{len(out.files_modified)} 修改);preimage 备份与账本在 "
                    f"{staged_state['backup_dir']};可随时回滚。"}


def roll_back(root: Path, applied_state: dict) -> dict:
    from repoproof.adoption.delivery.apply import ApplyError, rollback
    from repoproof.adoption.delivery.apply_manifest import ApplyManifest

    manifest = ApplyManifest.model_validate(applied_state["manifest"])
    try:
        out = rollback(applied_state["project"], manifest,
                       backup_dir=applied_state["backup_dir"])
    except ApplyError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "manifest": out.to_dict(),
            "note": "已回滚:仅恢复账本记录的文件,无关文件未被触碰;重复回滚是安全的。"}
