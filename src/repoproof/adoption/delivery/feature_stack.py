"""Feature Transaction 栈(源方案 §21-§28;T4 回滚专项的机器层)。

多个已采用 Feature 顺序存在时的事务、撤销、级联与选择性重建:
S0 --F1--> S1 --F2--> S2 --F3--> S3。写回/回滚的执行内核复用
delivery.apply(apply_confirmed / rollback)与 delivery.apply_manifest
——本模块是宿主级特性(改根文件的 PASS 产物)的编排层。铁律:

- 状态同一性 = **git 树对象哈希**(临时 index `add -A` + `write-tree`,
  内容寻址、mtime 无关);compute_tree_fingerprint 只作 Drift 门
  (含 mtime,过敏方向安全,不可用于"恢复到位"断言);
- 栈台账/备份/journal 全部放在**工作树之外**(ledger_dir),状态树
  永不被簿记污染;
- 一切 apply/rollback **先落 journal 再动第一笔**;进程死于中途 →
  `recover_interrupted()` 依 journal+preimage 恢复到父状态并校验树哈希;
  journal 未决时拒绝任何新事务;
- 回滚只走 LIFO:撤中间特性 = 级联(其上有声明依赖者,需逐特性确认)
  或选择性重建(§27:scratch 重建 + 全量验证通过才动真栈,否则
  SELECTIVE_REMOVAL_NOT_SAFE,真栈零改动);
- staged 树 = 栈的 CoW 全量副本 + 特性包施加(created 全文落位 +
  modified.patch 三方施加);冲突仅允许出现在 UNION_FILES(如
  requirements.txt 的尾部追加并置),按决定性 union 消解并验证两侧
  行全数保留——其余任何冲突一律拒绝。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

from repoproof.adoption.analysis.host_analyzer import compute_tree_fingerprint
from repoproof.adoption.delivery.apply import CONFIRM_TOKEN, apply_confirmed, rollback
from repoproof.adoption.delivery.apply_manifest import ApplyManifest, build_apply_manifest

STATUS_APPLIED = "APPLIED"
STATUS_ROLLED_BACK = "ROLLED_BACK"

PHASE_APPLYING = "applying"
PHASE_ROLLING_BACK = "rolling_back"

PLAN_DIRECT = "direct"
PLAN_CASCADE = "cascade"
PLAN_SELECTIVE_REBUILD = "selective_rebuild"

# 允许 union 消解的追加并置冲突面(其余冲突一律硬拒)
UNION_FILES = frozenset({"requirements.txt"})

_GIT_IDENT = ["-c", "user.name=RepoProof FeatureStack",
              "-c", "user.email=feature-stack@repoproof.local"]


class FeatureStackError(RuntimeError):
    pass


class StackJournalPending(FeatureStackError):
    """存在未决 journal(上次 apply/rollback 未终结)——先 recover_interrupted()。"""


class CascadeConfirmationRequired(FeatureStackError):
    """撤销将级联影响其上依赖特性,必须显式逐特性确认(UI 显示影响面)。"""

    def __init__(self, plan: dict):
        self.plan = plan
        super().__init__(
            "撤销 %s 将级联撤销:%s——请确认完整级联清单后重试"
            % (plan["target"], " → ".join(plan["cascade_order"])))


class SelectiveRemovalNotSafe(FeatureStackError):
    """SELECTIVE_REMOVAL_NOT_SAFE:无该中间特性的重建未通过全量验证(或存在声明依赖)。"""


class FeatureBundleError(FeatureStackError):
    pass


# ---------------------------------------------------------------- 数据模型

class StackState(BaseModel):
    state_id: str
    tree_sha: str
    commit_sha: str


class FeatureTransaction(BaseModel):
    """§21 FeatureTransaction 字段子集(host 级特性所需的最小完备面)。"""
    transaction_id: str
    feature_id: str
    feature_name: str
    parent_state_id: str
    result_state_id: str
    parent_tree_sha: str
    result_tree_sha: str
    host_commit: str
    source_repo: str = ""
    source_commit: str = ""
    origin_run_id: str = ""
    origin_verdict: str = ""
    requires_features: list[str] = []
    files_created: list[str] = []
    files_modified: list[str] = []
    dependency_delta: list[str] = []
    rollback_classes: list[str] = []
    manifest_file: str = ""            # ledger_dir 相对路径
    backup_dir: str = ""               # ledger_dir 相对路径
    applied_at: str = ""
    status: str = STATUS_APPLIED
    rollback_verified: bool = False


class StackLedger(BaseModel):
    host_commit: str
    stack_root: str
    states: list[StackState] = []
    active_state: str = ""
    applied_order: list[str] = []      # 当前在栈事务 id,底→顶
    transactions: dict[str, FeatureTransaction] = {}
    seq: int = 0


class FeatureBundle:
    """冻结特性包:feature.yaml + created/ 全文树 + modified.patch。"""

    def __init__(self, root: Path, meta: dict):
        self.root = root
        self.meta = meta
        self.feature_id: str = meta["feature_id"]
        self.feature_name: str = meta.get("feature_name", self.feature_id)
        self.files_created: list[str] = list(meta.get("files_created", []))
        self.files_modified: list[str] = list(meta.get("files_modified", []))
        self.requires_features: list[str] = list(meta.get("requires_features", []))
        self.dependency_delta: list[str] = list(meta.get("dependency_delta", []))
        self.rollback_classes: list[str] = list(meta.get("rollback_classes", []))
        self.origin_run_id: str = meta.get("origin_run_id", "")
        self.origin_verdict: str = meta.get("origin_verdict", "PASS_ADAPTED")
        self.source_repo: str = meta.get("source_repo", "")
        self.source_commit: str = meta.get("source_commit", "")

    @classmethod
    def load(cls, bundle_dir: str | Path) -> "FeatureBundle":
        root = Path(bundle_dir).expanduser().resolve()
        meta_path = root / "feature.yaml"
        if not meta_path.is_file():
            raise FeatureBundleError(f"特性包缺 feature.yaml:{root}")
        import yaml
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict) or not meta.get("feature_id"):
            raise FeatureBundleError(f"feature.yaml 缺 feature_id:{meta_path}")
        bundle = cls(root, meta)
        created_root = root / "created"
        on_disk = set()
        if created_root.is_dir():
            on_disk = {str(p.relative_to(created_root))
                       for p in created_root.rglob("*")
                       if p.is_file() and p.name != ".DS_Store"}
        if on_disk != set(bundle.files_created):
            raise FeatureBundleError(
                f"created/ 与 feature.yaml files_created 不一致:{root}\n"
                f"  仅在磁盘:{sorted(on_disk - set(bundle.files_created))}\n"
                f"  仅在清单:{sorted(set(bundle.files_created) - on_disk)}")
        patch = root / "modified.patch"
        if bundle.files_modified and not patch.is_file():
            raise FeatureBundleError(f"声明了 files_modified 却缺 modified.patch:{root}")
        if patch.is_file() and not bundle.files_modified:
            raise FeatureBundleError(f"存在 modified.patch 却未声明 files_modified:{root}")
        return bundle


# ---------------------------------------------------------------- 工具

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".rp_tmp_{path.name}"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)


def _cow_copy(src: Path, dest: Path) -> None:
    """APFS clonefile 优先(cp -Rc),失败回退逐文件复制;含 .git。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["cp", "-Rc", str(src), str(dest)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(src, dest, symlinks=True)


def _resolve_union(path: Path) -> None:
    """决定性 union:去冲突标记、两侧块按 ours→theirs 并置;两侧行必须全数保留。"""
    text = path.read_text(encoding="utf-8")
    if "<<<<<<<" not in text:
        return
    out: list[str] = []
    ours: list[str] = []
    theirs: list[str] = []
    mode = ""
    for ln in text.splitlines():
        if ln.startswith("<<<<<<<"):
            mode = "ours"
            continue
        if ln.startswith("=======") and mode == "ours":
            mode = "theirs"
            continue
        if ln.startswith(">>>>>>>") and mode == "theirs":
            out.extend(ours)
            out.extend(theirs)
            ours, theirs, mode = [], [], ""
            continue
        if mode == "ours":
            ours.append(ln)
        elif mode == "theirs":
            theirs.append(ln)
        else:
            out.append(ln)
    if mode:
        raise FeatureStackError(f"冲突标记不闭合,拒绝消解:{path}")
    resolved = "\n".join(out) + "\n"
    for ln in ours + theirs:
        if ln and ln not in resolved:
            raise FeatureStackError(f"union 后置校验失败(行丢失):{ln!r} @ {path}")
    path.write_text(resolved, encoding="utf-8")


# ---------------------------------------------------------------- 栈

class FeatureStack:
    """事务栈编排层;stack_root 必须是 git 仓库,ledger_dir 在工作树之外。"""

    def __init__(self, stack_root: str | Path, ledger_dir: str | Path):
        self.root = Path(stack_root).expanduser().resolve()
        self.ledger_dir = Path(ledger_dir).expanduser().resolve()
        if self.ledger_dir == self.root or self.root in self.ledger_dir.parents:
            raise FeatureStackError("ledger_dir 不得位于栈工作树之内")
        self._ledger_path = self.ledger_dir / "stack_ledger.json"
        self._journal_path = self.ledger_dir / "journal.json"
        self.ledger: StackLedger | None = None
        if self._ledger_path.exists():
            self.ledger = StackLedger.model_validate_json(
                self._ledger_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------ git 原语

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True,
             env: dict | None = None) -> subprocess.CompletedProcess:
        proc = subprocess.run(["git", "-C", str(cwd or self.root), *args],
                              capture_output=True, text=True, timeout=120,
                              env=env)
        if check and proc.returncode != 0:
            raise FeatureStackError(
                f"git {' '.join(args[:2])} 失败:{proc.stderr.strip()[:400]}")
        return proc

    def _tree_sha_of(self, root: Path) -> str:
        """内容寻址状态同一性:临时 index add -A + write-tree(不动真 index)。"""
        with tempfile.TemporaryDirectory(prefix="rp_treesha_") as td:
            env = dict(os.environ)
            env["GIT_INDEX_FILE"] = str(Path(td) / "index")
            self._git("add", "-A", ".", cwd=root, env=env)
            out = self._git("write-tree", cwd=root, env=env)
            return out.stdout.strip()

    def tree_sha(self) -> str:
        return self._tree_sha_of(self.root)

    # ------------------------------------------------------------ 台账

    def _save_ledger(self) -> None:
        assert self.ledger is not None
        _atomic_json(self._ledger_path, self.ledger.model_dump())

    def _state(self, state_id: str) -> StackState:
        assert self.ledger is not None
        for s in self.ledger.states:
            if s.state_id == state_id:
                return s
        raise FeatureStackError(f"未知状态:{state_id}")

    def _state_by_tree(self, tree_sha: str) -> StackState | None:
        assert self.ledger is not None
        for s in self.ledger.states:
            if s.tree_sha == tree_sha:
                return s
        return None

    def _require_no_journal(self) -> None:
        if self._journal_path.exists():
            raise StackJournalPending(
                f"存在未决 journal:{self._journal_path}——先执行 recover_interrupted()")

    def _require_intact(self) -> None:
        assert self.ledger is not None
        current = self.tree_sha()
        expect = self._state(self.ledger.active_state).tree_sha
        if current != expect:
            raise FeatureStackError(
                f"栈工作树与台账不符(树 {current[:12]} ≠ 状态 "
                f"{self.ledger.active_state} 记录 {expect[:12]})——栈被外部改动?")

    # ------------------------------------------------------------ 初始化

    @classmethod
    def init(cls, stack_root: str | Path, ledger_dir: str | Path) -> "FeatureStack":
        from repoproof.harness.host_guard import assert_writable_target

        assert_writable_target(stack_root, purpose="以该副本为 Feature 事务栈")
        stack = cls(stack_root, ledger_dir)
        if stack.ledger is not None:
            raise FeatureStackError(f"台账已存在,不重复初始化:{stack._ledger_path}")
        status = stack._git("status", "--porcelain").stdout.strip()
        if status:
            raise FeatureStackError(
                f"栈工作树不洁(untracked/modified),拒绝初始化:\n{status[:600]}")
        head = stack._git("rev-parse", "HEAD").stdout.strip()
        sha = stack.tree_sha()
        stack.ledger = StackLedger(
            host_commit=head, stack_root=str(stack.root),
            states=[StackState(state_id="S0", tree_sha=sha, commit_sha=head)],
            active_state="S0")
        stack.ledger_dir.mkdir(parents=True, exist_ok=True)
        stack._save_ledger()
        return stack

    @classmethod
    def load(cls, stack_root: str | Path, ledger_dir: str | Path) -> "FeatureStack":
        stack = cls(stack_root, ledger_dir)
        if stack.ledger is None:
            raise FeatureStackError(f"台账不存在:{stack._ledger_path}")
        return stack

    # ------------------------------------------------------------ staged 树构建

    def _build_staged(self, bundle: FeatureBundle, base_root: Path,
                      work_dir: Path) -> Path:
        """base 的 CoW 副本 + 特性包施加;冲突仅允许 UNION_FILES 并 union 消解。"""
        staged = work_dir / f"staged-{bundle.feature_id}"
        if staged.exists():
            raise FeatureStackError(f"staged 目录已存在,不覆盖:{staged}")
        _cow_copy(base_root, staged)
        for rel in bundle.files_created:
            src = bundle.root / "created" / rel
            dest = staged / rel
            if dest.exists():
                raise FeatureStackError(
                    f"特性声明新建的文件在基态已存在:{rel}(特性包与状态不符)")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        patch = bundle.root / "modified.patch"
        if bundle.files_modified:
            # CoW 副本 inode 变化会让 index 的 stat 缓存失效 → 先刷新
            self._git("update-index", "-q", "--refresh", cwd=staged, check=False)
            proc = self._git("apply", "--3way", "--whitespace=nowarn", str(patch),
                             cwd=staged, check=False)
            if proc.returncode != 0:
                unmerged = self._git("diff", "--name-only", "--diff-filter=U",
                                     cwd=staged).stdout.split()
                if not unmerged:
                    raise FeatureStackError(
                        f"modified.patch 施加失败(非冲突类):{proc.stderr.strip()[:400]}")
                illegal = [f for f in unmerged if f not in UNION_FILES]
                if illegal:
                    raise FeatureStackError(
                        f"补丁冲突超出 union 允许面,拒绝:{illegal}")
                for rel in unmerged:
                    _resolve_union(staged / rel)
        return staged

    # ------------------------------------------------------------ apply

    def apply_feature(self, bundle: FeatureBundle, *,
                      requires_features: list[str] | None = None,
                      work_dir: str | Path | None = None) -> FeatureTransaction:
        assert self.ledger is not None
        self._require_no_journal()
        self._require_intact()
        for dep in (requires_features if requires_features is not None
                    else bundle.requires_features):
            applied = {self.ledger.transactions[t].feature_id
                       for t in self.ledger.applied_order}
            if dep not in applied:
                raise FeatureStackError(
                    f"依赖未满足:{bundle.feature_id} requires {dep},当前栈 {sorted(applied)}")

        work = Path(work_dir).expanduser().resolve() if work_dir \
            else self.ledger_dir / "work"
        work.mkdir(parents=True, exist_ok=True)
        parent = self._state(self.ledger.active_state)
        staged = self._build_staged(bundle, self.root, work)
        try:
            manifest = build_apply_manifest(
                self.root, staged,
                base_git_commit=parent.commit_sha,
                base_tree_hash=parent.tree_sha,
                dependency_changes=bundle.dependency_delta)
            if manifest.files_deleted:
                raise FeatureStackError(
                    f"staged 树缺失基态文件(构建器缺陷):{manifest.files_deleted[:5]}")
            if set(manifest.files_created) != set(bundle.files_created):
                raise FeatureStackError(
                    "manifest 新建面与特性包声明不符:"
                    f"{sorted(set(manifest.files_created) ^ set(bundle.files_created))}")
            if set(manifest.files_modified) != set(bundle.files_modified):
                raise FeatureStackError(
                    "manifest 修改面与特性包声明不符:"
                    f"{sorted(set(manifest.files_modified) ^ set(bundle.files_modified))}")

            self.ledger.seq += 1
            txid = f"{bundle.feature_id}-{self.ledger.seq:02d}"
            manifest_rel = f"manifests/{txid}.json"
            backup_rel = f"backups/{txid}"
            _atomic_json(self.ledger_dir / manifest_rel, manifest.to_dict())
            staged_sha = self._tree_sha_of(staged)
            _atomic_json(self._journal_path, {
                "phase": PHASE_APPLYING, "transaction_id": txid,
                "feature_id": bundle.feature_id,
                "parent_state_id": parent.state_id,
                "parent_tree_sha": parent.tree_sha,
                "parent_commit": parent.commit_sha,
                "manifest_file": manifest_rel, "backup_dir": backup_rel,
                "written_at": _utcnow()})
            fingerprint = str(compute_tree_fingerprint(self.root).value or "")
            try:
                apply_confirmed(
                    self.root, staged, manifest,
                    backup_dir=self.ledger_dir / backup_rel,
                    verdict=bundle.origin_verdict,
                    baseline_fingerprint=fingerprint,
                    user_viewed_files=True, user_viewed_diff=True,
                    confirm_token=CONFIRM_TOKEN,
                    apply_timestamp=_utcnow())
            except Exception:
                # apply_confirmed 已自回滚;核树后清 journal 再抛
                if self.tree_sha() != parent.tree_sha:
                    raise FeatureStackError(
                        "apply 失败且自动回滚未复位——保留 journal,需 recover_interrupted()")
                self._journal_path.unlink(missing_ok=True)
                raise

            new_sha = self.tree_sha()
            if new_sha != staged_sha:
                raise FeatureStackError(
                    f"写回后树 {new_sha[:12]} ≠ staged {staged_sha[:12]}(写回不完整?)")
            state = self._enter_state(new_sha, f"{bundle.feature_id}: {bundle.feature_name}")
            tx = FeatureTransaction(
                transaction_id=txid, feature_id=bundle.feature_id,
                feature_name=bundle.feature_name,
                parent_state_id=parent.state_id, result_state_id=state.state_id,
                parent_tree_sha=parent.tree_sha, result_tree_sha=new_sha,
                host_commit=self.ledger.host_commit,
                source_repo=bundle.source_repo, source_commit=bundle.source_commit,
                origin_run_id=bundle.origin_run_id, origin_verdict=bundle.origin_verdict,
                requires_features=(requires_features if requires_features is not None
                                   else bundle.requires_features),
                files_created=list(manifest.files_created),
                files_modified=list(manifest.files_modified),
                dependency_delta=bundle.dependency_delta,
                rollback_classes=bundle.rollback_classes,
                manifest_file=manifest_rel, backup_dir=backup_rel,
                applied_at=_utcnow())
            self.ledger.transactions[txid] = tx
            self.ledger.applied_order.append(txid)
            self.ledger.active_state = state.state_id
            self._save_ledger()
            self._journal_path.unlink(missing_ok=True)
            return tx
        finally:
            shutil.rmtree(staged, ignore_errors=True)

    def _enter_state(self, tree_sha: str, message: str) -> StackState:
        """树已在工作区就位:已知树 → 复位到规范 commit;新树 → 提交并登记。"""
        assert self.ledger is not None
        known = self._state_by_tree(tree_sha)
        if known is not None:
            self._git("reset", "-q", known.commit_sha)
            return known
        self._git("add", "-A", ".")
        self._git(*_GIT_IDENT, "commit", "-q", "-m", message)
        commit = self._git("rev-parse", "HEAD").stdout.strip()
        state = StackState(state_id=f"S{len(self.ledger.states)}",
                           tree_sha=tree_sha, commit_sha=commit)
        self.ledger.states.append(state)
        return state

    # ------------------------------------------------------------ rollback

    def rollback_top(self, *, expect_feature_id: str | None = None) -> FeatureTransaction:
        assert self.ledger is not None
        self._require_no_journal()
        if not self.ledger.applied_order:
            raise FeatureStackError("栈为空,无可回滚特性")
        self._require_intact()
        tx = self.ledger.transactions[self.ledger.applied_order[-1]]
        if expect_feature_id and tx.feature_id != expect_feature_id:
            raise FeatureStackError(
                f"栈顶是 {tx.feature_id},不是请求的 {expect_feature_id}(回滚只走 LIFO)")
        manifest = ApplyManifest.model_validate_json(
            (self.ledger_dir / tx.manifest_file).read_text(encoding="utf-8"))
        _atomic_json(self._journal_path, {
            "phase": PHASE_ROLLING_BACK, "transaction_id": tx.transaction_id,
            "feature_id": tx.feature_id,
            "parent_state_id": tx.parent_state_id,
            "parent_tree_sha": tx.parent_tree_sha,
            "parent_commit": self._state(tx.parent_state_id).commit_sha,
            "manifest_file": tx.manifest_file, "backup_dir": tx.backup_dir,
            "written_at": _utcnow()})
        rollback(self.root, manifest, backup_dir=self.ledger_dir / tx.backup_dir)
        self._finalize_rollback(tx)
        return tx

    def _finalize_rollback(self, tx: FeatureTransaction) -> None:
        assert self.ledger is not None
        current = self.tree_sha()
        if current != tx.parent_tree_sha:
            raise FeatureStackError(
                f"回滚后树 {current[:12]} ≠ 父状态 {tx.parent_state_id} 记录 "
                f"{tx.parent_tree_sha[:12]}——保留 journal,人工介入")
        self._git("reset", "-q", self._state(tx.parent_state_id).commit_sha)
        if self.ledger.applied_order and self.ledger.applied_order[-1] == tx.transaction_id:
            self.ledger.applied_order.pop()
        tx.status = STATUS_ROLLED_BACK
        tx.rollback_verified = True
        self.ledger.transactions[tx.transaction_id] = tx
        self.ledger.active_state = tx.parent_state_id
        self._save_ledger()
        self._journal_path.unlink(missing_ok=True)

    # ------------------------------------------------------------ 撤销规划(§25-§27)

    def removal_plan(self, feature_id: str) -> dict:
        assert self.ledger is not None
        order = [self.ledger.transactions[t] for t in self.ledger.applied_order]
        idx = next((i for i, t in enumerate(order) if t.feature_id == feature_id), None)
        if idx is None:
            raise FeatureStackError(f"特性不在栈上:{feature_id}")
        above = order[idx + 1:]
        if not above:
            return {"kind": PLAN_DIRECT, "target": feature_id,
                    "cascade_order": [feature_id], "dependents": [],
                    "independents_above": [],
                    "impact": [f"回滚 {feature_id} → 返回 {order[idx].parent_state_id}"]}
        dependents = [t.feature_id for t in above if feature_id in t.requires_features]
        cascade = [t.feature_id for t in reversed(above)] + [feature_id]
        kind = PLAN_CASCADE if dependents else PLAN_SELECTIVE_REBUILD
        impact = [f"{feature_id} 之上存在 {len(above)} 个特性:"
                  f"{[t.feature_id for t in above]}"]
        if dependents:
            impact.append(f"其中声明依赖 {feature_id} 的:{dependents} → 级联撤销不可避免")
            impact.append(f"级联序(LIFO):{' → '.join(cascade)}")
        else:
            impact.append("无声明依赖 → 走选择性重建(§27):scratch 重建无"
                          f" {feature_id} 的新状态并全量验证,通过才动真栈")
        return {"kind": kind, "target": feature_id, "cascade_order": cascade,
                "dependents": dependents,
                "independents_above": [t.feature_id for t in above
                                       if feature_id not in t.requires_features],
                "impact": impact}

    def cascade_remove(self, feature_id: str, *,
                       confirmed_features: list[str] | None = None) -> dict:
        plan = self.removal_plan(feature_id)
        if plan["kind"] == PLAN_DIRECT:
            self.rollback_top(expect_feature_id=feature_id)
            return plan
        if plan["kind"] != PLAN_CASCADE:
            raise FeatureStackError(
                f"{feature_id} 之上无声明依赖者——按 §27 走 selective_rebuild(),"
                "不得对中间特性做级联挖除")
        if confirmed_features != plan["cascade_order"]:
            raise CascadeConfirmationRequired(plan)
        for fid in plan["cascade_order"]:
            self.rollback_top(expect_feature_id=fid)
        return plan

    def selective_rebuild(self, remove_feature_id: str, *,
                          bundles: dict[str, FeatureBundle],
                          verify_fn, scratch_dir: str | Path) -> dict:
        """§27:从目标下方状态 scratch 重建(跳过目标、重施其上独立特性)
        → verify_fn(scratch) 全量验证 → 通过才在真栈上执行等价变换;
        任何失败真栈零改动,scratch 留存供取证。"""
        assert self.ledger is not None
        self._require_no_journal()
        self._require_intact()
        plan = self.removal_plan(remove_feature_id)
        if plan["kind"] == PLAN_DIRECT:
            raise FeatureStackError(f"{remove_feature_id} 在栈顶——直接 rollback_top()")
        if plan["dependents"]:
            raise SelectiveRemovalNotSafe(
                f"SELECTIVE_REMOVAL_NOT_SAFE:{plan['dependents']} 声明依赖 "
                f"{remove_feature_id},仅级联可行(cascade_remove + 确认)")
        order = [self.ledger.transactions[t] for t in self.ledger.applied_order]
        idx = next(i for i, t in enumerate(order) if t.feature_id == remove_feature_id)
        target = order[idx]
        replay = order[idx + 1:]                       # 底→顶,重施序
        missing = [t.feature_id for t in replay if t.feature_id not in bundles]
        if missing:
            raise FeatureStackError(f"缺重施特性包:{missing}")

        scratch_root = Path(scratch_dir).expanduser().resolve()
        scratch_root.mkdir(parents=True, exist_ok=True)
        scratch = scratch_root / f"rebuild-no-{remove_feature_id}"
        if scratch.exists():
            raise FeatureStackError(f"scratch 已存在,不覆盖:{scratch}")
        _cow_copy(self.root, scratch)
        base_commit = self._state(target.parent_state_id).commit_sha
        self._git("reset", "-q", "--hard", base_commit, cwd=scratch)
        self._git("clean", "-qfd", cwd=scratch)        # 不带 -x:被 ignore 的运行态保留
        for t in replay:
            b = bundles[t.feature_id]
            staged = self._build_staged(b, scratch, scratch_root)
            try:
                man = build_apply_manifest(scratch, staged)
                if man.files_deleted:
                    raise FeatureStackError(
                        f"scratch 重施 {t.feature_id} 出现缺失面:{man.files_deleted[:5]}")
                for rel in (*man.files_created, *man.files_modified):
                    dest = scratch / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(staged / rel, dest)
            finally:
                shutil.rmtree(staged, ignore_errors=True)
            self._git("add", "-A", ".", cwd=scratch)
            self._git(*_GIT_IDENT, "commit", "-q", "-m",
                      f"rebuild: {t.feature_id}", cwd=scratch)

        if not verify_fn(scratch):
            raise SelectiveRemovalNotSafe(
                f"SELECTIVE_REMOVAL_NOT_SAFE:无 {remove_feature_id} 的重建未通过"
                f"全量验证(scratch 留存取证:{scratch});真栈零改动")
        scratch_sha = self._tree_sha_of(scratch)

        # scratch 已证明 → 真栈等价变换:LIFO 退到基态,再重施独立特性
        for fid in plan["cascade_order"]:
            self.rollback_top(expect_feature_id=fid)
        for t in replay:
            self.apply_feature(bundles[t.feature_id],
                               requires_features=[d for d in t.requires_features
                                                  if d != remove_feature_id])
        final = self.tree_sha()
        if final != scratch_sha:
            raise FeatureStackError(
                f"重建不确定:真栈 {final[:12]} ≠ scratch {scratch_sha[:12]}")
        return {"new_state": self.ledger.active_state, "tree_sha": final,
                "scratch": str(scratch), "plan": plan}

    # ------------------------------------------------------------ 崩溃恢复(R-E)

    def recover_interrupted(self) -> dict:
        assert self.ledger is not None
        if not self._journal_path.exists():
            return {"recovered": False, "reason": "无未决 journal"}
        j = json.loads(self._journal_path.read_text(encoding="utf-8"))
        manifest = ApplyManifest.model_validate_json(
            (self.ledger_dir / j["manifest_file"]).read_text(encoding="utf-8"))
        backups = self.ledger_dir / j["backup_dir"]
        if j["phase"] == PHASE_APPLYING:
            # 中断的 apply 一律作废:新建删除、修改复原、临时件清扫
            for rel in manifest.files_created:
                (self.root / rel).unlink(missing_ok=True)
            for rel in manifest.files_modified:
                pre = backups / rel
                if pre.exists():
                    if _sha256_file(pre) != manifest.before_hashes.get(rel, ""):
                        raise FeatureStackError(
                            f"preimage 校验失败,拒绝恢复:{rel}——人工介入")
                    target = self.root / rel
                    tmp = target.parent / f".rp_tmp_{target.name}"
                    tmp.write_bytes(pre.read_bytes())
                    shutil.copymode(pre, tmp)   # preimage 经 copy2 备份,权限位一并复原
                    os.replace(tmp, target)
            for rel in (*manifest.files_created, *manifest.files_modified):
                p = self.root / rel
                (p.parent / f".rp_tmp_{p.name}").unlink(missing_ok=True)
            current = self.tree_sha()
            if current != j["parent_tree_sha"]:
                raise FeatureStackError(
                    f"恢复后树 {current[:12]} ≠ 父状态记录 "
                    f"{j['parent_tree_sha'][:12]}——人工介入")
            self._journal_path.unlink(missing_ok=True)
            return {"recovered": True, "phase": j["phase"],
                    "transaction_id": j["transaction_id"],
                    "restored_to": j["parent_state_id"]}
        if j["phase"] == PHASE_ROLLING_BACK:
            # 幂等重放回滚动作,补完终结
            rollback(self.root, manifest, backup_dir=backups)
            tx = self.ledger.transactions[j["transaction_id"]]
            self._finalize_rollback(tx)
            return {"recovered": True, "phase": j["phase"],
                    "transaction_id": j["transaction_id"],
                    "restored_to": j["parent_state_id"]}
        raise FeatureStackError(f"未知 journal phase:{j['phase']}")
