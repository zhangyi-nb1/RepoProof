"""Apply 编排(RFC-008 §9,Gate E)— bundle → staging → manifest → 写回。

UI/CLI 的唯一入口;三级协议按序走,任何一步失败都停在原地:
1) stage_bundle:把 bundle 的 adapter/ 落进用户项目的 **staging 副本**
   指定子目录(默认 adopted/<task_id>/),原项目零修改;
2) manifest_from_staging:staging vs 原项目 → ApplyManifest + Diff 预览;
3) 写回(apply_confirmed)与回滚(rollback)在 delivery.apply,
   需要判定 PASS、无 Drift、看过清单与 Diff、逐字确认令牌。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from repoproof.adoption.delivery.apply_manifest import ApplyManifest, build_apply_manifest
from repoproof.adoption.delivery.staging import StagingInfo, create_staging


class ApplyFlowError(RuntimeError):
    pass


def stage_bundle(
    project_path: str | Path,
    bundle_dir: str | Path,
    staging_root: str | Path,
    *,
    dest_rel: str = "",
) -> tuple[StagingInfo, ApplyManifest, dict]:
    """创建 staging 副本并把 bundle 适配件落入其中;返回
    (staging 信息, 写回账本, bundle 清单)。原项目在本函数中只读。"""
    from repoproof.harness.host_guard import assert_writable_target

    assert_writable_target(project_path, purpose="以该项目为写回目标建立 staging")
    bundle = Path(bundle_dir).expanduser().resolve()
    bm_path = bundle / "bundle_manifest.json"
    if not bm_path.exists():
        raise ApplyFlowError(f"不是有效的结果包(缺 bundle_manifest.json):{bundle}")
    bm = json.loads(bm_path.read_text(encoding="utf-8"))
    adapter_src = bundle / "adapter"
    if not adapter_src.is_dir() or not any(adapter_src.rglob("*")):
        raise ApplyFlowError("结果包中没有适配产物(失败运行的包只用于查看报告,不能应用)")
    if bm.get("verdict") not in ("PASS_DIRECT", "PASS_ADAPTED"):
        raise ApplyFlowError(
            f"结果包判定为 {bm.get('verdict')},不满足应用条件(需 PASS)——仍可查看报告与产物")

    info = create_staging(project_path, staging_root)
    staged = Path(info.staging_path)
    rel = dest_rel or f"adopted/{bm.get('task_id', 'capability')}"
    if ".." in Path(rel).parts or Path(rel).is_absolute():
        raise ApplyFlowError(f"非法目标子目录:{rel!r}")
    dest = staged / rel
    if dest.exists():
        raise ApplyFlowError(f"staging 中目标子目录已存在:{rel}(换一个目录名)")
    for p in sorted(adapter_src.rglob("*")):
        if p.is_file():
            out = dest / p.relative_to(adapter_src)
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)

    manifest = build_apply_manifest(
        Path(info.project_path), staged,
        base_git_commit=info.base_git_commit,
        base_tree_hash=info.base_tree_fingerprint,
        dependency_changes=[d for d in (bm.get("task_id"),) if d],
    )
    return info, manifest, bm


def diff_preview(project_path: str | Path, staged_root: str | Path,
                 manifest: ApplyManifest, *, max_lines: int = 120) -> str:
    """人类可读 Diff 预览(新增全文摘要 + 修改前后行数),供 UI 展示。"""
    project = Path(project_path)
    staged = Path(staged_root)
    lines: list[str] = []
    for rel in manifest.files_created:
        body = (staged / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        lines.append(f"+ 新增 {rel}({len(body)} 行)")
        lines += [f"    + {ln}" for ln in body[:20]]
        if len(body) > 20:
            lines.append(f"    …(其余 {len(body) - 20} 行见 staging)")
    for rel in manifest.files_modified:
        before = (project / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        after = (staged / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        lines.append(f"~ 修改 {rel}({len(before)} → {len(after)} 行)")
    for rel in manifest.files_deleted:
        lines.append(f"! staging 中不存在(不会代表你删除):{rel}")
    return "\n".join(lines[:max_lines]) or "(无文件级差异)"
