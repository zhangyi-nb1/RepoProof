"""Apply / Rollback(RFC-008 §9.3/9.5,Gate E)— 写回用户项目的执行层。

三级协议的第 3 级(APPLY_CONFIRMED)。铁律(全部测试钉死):
- 写回前重算树指纹,Drift → PROJECT_DRIFT_DETECTED,拒绝强行应用;
- 显式确认三要素缺一不可:看过文件清单、看过 Diff、二次确认令牌;
- 目标路径逐个做 resolve/绝对路径/父目录穿越/符号链接检查;
- 写入原子:同目录临时文件 + os.replace;先备份 preimage 再动手;
- 中途失败 → 自动回滚已写部分,项目回到 apply 前状态;
- 回滚只恢复 manifest 记录的文件、幂等、绝不递归删除;
- Gate E 只在测试 fixture 项目上验证;首次写入真实用户项目前必须
  停止并获得用户明确授权(流程停点,不是代码可绕过的开关)。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from repoproof.adoption.analysis.host_analyzer import compute_tree_fingerprint
from repoproof.adoption.delivery.apply_manifest import (
    RESULT_APPLIED,
    RESULT_DRIFT,
    RESULT_ROLLED_BACK,
    ApplyManifest,
)


class ApplyError(RuntimeError):
    pass


class DriftDetected(ApplyError):
    pass


class ConfirmationMissing(ApplyError):
    pass


CONFIRM_TOKEN = "我已核对文件清单与改动,确认写入我的项目"


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_target(project_root: Path, rel: str) -> Path:
    """路径安全:相对、不上跳、解析后仍在项目内、途中无符号链接。"""
    if not rel or rel.startswith(("/", "~")) or ".." in Path(rel).parts:
        raise ApplyError(f"非法目标路径:{rel!r}")
    target = (project_root / rel)
    resolved_root = project_root.resolve()
    # 已存在的每一级路径都不允许是符号链接(防跳出项目)
    probe = target
    while True:
        if probe.exists() and probe.is_symlink():
            raise ApplyError(f"目标路径含符号链接,拒绝写入:{probe}")
        if probe == project_root or probe.parent == probe:
            break
        probe = probe.parent
    if resolved_root not in target.resolve().parents and target.resolve() != resolved_root:
        raise ApplyError(f"目标路径逃逸项目根,拒绝写入:{rel!r}")
    return target


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.parent / f".rp_tmp_{target.name}"
    tmp.write_bytes(data)
    os.replace(tmp, target)


def apply_confirmed(
    project_root: str | Path,
    staged_root: str | Path,
    manifest: ApplyManifest,
    *,
    backup_dir: str | Path,
    verdict: str,
    baseline_fingerprint: str,
    user_viewed_files: bool,
    user_viewed_diff: bool,
    confirm_token: str,
    apply_timestamp: str,
) -> ApplyManifest:
    """把 manifest 描述的 created/modified 从 staging 写回项目。

    全部前置满足才动第一笔;任何一笔失败 → 自动回滚已写部分并抛错。
    成功返回 result_state=APPLIED 的 manifest(含 preimage 备份位置)。
    """
    project = Path(project_root).expanduser().resolve()
    staged = Path(staged_root).expanduser().resolve()
    backups = Path(backup_dir).expanduser().resolve()

    if verdict not in ("PASS_DIRECT", "PASS_ADAPTED"):
        raise ApplyError(f"最终判定为 {verdict},不满足写回条件(需 PASS_DIRECT/PASS_ADAPTED)")
    if not user_viewed_files:
        raise ConfirmationMissing("你尚未查看将写入的文件清单")
    if not user_viewed_diff:
        raise ConfirmationMissing("你尚未查看改动 Diff")
    if confirm_token != CONFIRM_TOKEN:
        raise ConfirmationMissing("二次确认令牌不符——必须逐字确认写入声明")
    if not manifest.rollback_actions and (manifest.files_created or manifest.files_modified):
        raise ApplyError("回滚方案缺失,拒绝写入")

    current = str(compute_tree_fingerprint(project).value or "")
    if current != baseline_fingerprint:
        manifest.result_state = RESULT_DRIFT
        raise DriftDetected(
            "你的项目自分析后发生了变化(指纹失配)——已停止,请重新分析后再试;绝不强行应用")

    # 预检所有目标路径 + 备份 preimage
    backups.mkdir(parents=True, exist_ok=True)
    targets: dict[str, Path] = {}
    for rel in (*manifest.files_created, *manifest.files_modified):
        targets[rel] = _safe_target(project, rel)
    for rel in manifest.files_modified:
        t = targets[rel]
        if not t.exists():
            raise ApplyError(f"待修改文件不存在:{rel}(与账本不符,拒绝)")
        pre = backups / rel
        pre.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(t, pre)
        if _sha256_file(pre) != manifest.before_hashes.get(rel, ""):
            raise ApplyError(f"文件 {rel} 当前内容与账本 before_hash 不符(Drift),拒绝")
    for rel in manifest.files_created:
        if targets[rel].exists():
            raise ApplyError(f"待新建文件已存在:{rel}(拒绝覆盖)")

    written: list[str] = []
    try:
        for rel in (*manifest.files_created, *manifest.files_modified):
            src = staged / rel
            if not src.is_file():
                raise ApplyError(f"staging 缺少来源文件:{rel}")
            data = src.read_bytes()
            if hashlib.sha256(data).hexdigest() != manifest.after_hashes.get(rel, ""):
                raise ApplyError(f"staging 文件 {rel} 与账本 after_hash 不符,拒绝")
            _atomic_write(targets[rel], data)
            written.append(rel)
    except Exception:
        # 中途失败:自动回滚已写部分——项目回到 apply 前状态
        _rollback_written(project, manifest, backups, written)
        raise

    manifest.result_state = RESULT_APPLIED
    manifest.apply_timestamp = apply_timestamp
    manifest.commands_executed = list(manifest.commands_executed)
    (backups / "apply_manifest.applied.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8")
    return manifest


def _rollback_written(project: Path, manifest: ApplyManifest,
                      backups: Path, written: list[str]) -> None:
    created = set(manifest.files_created)
    for rel in written:
        target = project / rel
        if rel in created:
            target.unlink(missing_ok=True)
        else:
            pre = backups / rel
            if pre.exists():
                _atomic_write(target, pre.read_bytes())


def rollback(
    project_root: str | Path,
    manifest: ApplyManifest,
    *,
    backup_dir: str | Path,
) -> ApplyManifest:
    """按账本回滚:只动 manifest 列出的文件;幂等;绝不递归删除。"""
    project = Path(project_root).expanduser().resolve()
    backups = Path(backup_dir).expanduser().resolve()
    for action in manifest.rollback_actions:
        target = _safe_target(project, action.path)
        if action.kind == "delete_created":
            target.unlink(missing_ok=True)  # 幂等:不存在即跳过
        elif action.kind == "restore_preimage":
            pre = backups / action.path
            if not pre.exists():
                raise ApplyError(f"缺少 preimage 备份,无法恢复:{action.path}")
            if _sha256_file(pre) != action.preimage_sha256:
                raise ApplyError(f"preimage 校验失败,拒绝恢复:{action.path}")
            _atomic_write(target, pre.read_bytes())
        else:  # 结构上不存在第三种动作;防御性拒绝
            raise ApplyError(f"未知回滚动作:{action.kind}")
    manifest.result_state = RESULT_ROLLED_BACK
    return manifest
