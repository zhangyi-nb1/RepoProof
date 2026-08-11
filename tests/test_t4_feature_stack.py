"""T4 Feature Transaction 栈钉死测试(源方案 §21-§28;仅合成 fixture 仓库)。

覆盖:初始化纪律 / apply 全链(manifest·journal·状态登记·树哈希)/
union 决定性消解 / LIFO 回滚与状态复用 / 撤销规划三态(direct·cascade·
selective_rebuild)/ 级联确认门 / 选择性重建(通过·不安全两路)/
journal 崩溃恢复(applying·rolling_back 两相,KeyboardInterrupt 模拟
硬中断——绕过 except Exception,与 kill 同构)。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

import repoproof.adoption.delivery.apply as apply_mod
from repoproof.adoption.delivery.feature_stack import (
    CascadeConfirmationRequired,
    FeatureBundle,
    FeatureStack,
    FeatureStackError,
    SelectiveRemovalNotSafe,
    StackJournalPending,
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True, text=True, check=True)
    return proc.stdout.strip()


REQ_BASE = "flask>=2.0\npytest>=8.0\n"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "hostproj"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "app.py").write_text("print('host')\n", encoding="utf-8")
    (root / "requirements.txt").write_text(REQ_BASE, encoding="utf-8")
    (root / ".gitignore").write_text("runtime_data/\n", encoding="utf-8")
    (root / "runtime_data").mkdir()
    (root / "runtime_data" / "db.bin").write_bytes(b"\x00runtime")  # ignored 运行态
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "S0 base")
    return root


def _mk_bundle(tmp_path: Path, base_repo: Path, fid: str, *,
               created: dict[str, str],
               req_append: str = "",
               requires: list[str] | None = None) -> FeatureBundle:
    """特性包生成:modified.patch 一律相对 S0 基线生成(模拟真实特性
    各自出身不同基线;叠加顺序冲突走 union)。"""
    root = tmp_path / f"bundle-{fid}"
    files_modified: list[str] = []
    if req_append:
        work = tmp_path / f"patchwork-{fid}"
        subprocess.run(["cp", "-R", str(base_repo), str(work)], check=True)
        _git(work, "reset", "-q", "--hard")
        req = work / "requirements.txt"
        req.write_text(req.read_text(encoding="utf-8") + req_append, encoding="utf-8")
        patch = _git(work, "diff")
        (root / "created").mkdir(parents=True, exist_ok=True)
        (root / "modified.patch").parent.mkdir(parents=True, exist_ok=True)
        (root / "modified.patch").write_text(patch + "\n", encoding="utf-8")
        files_modified = ["requirements.txt"]
    for rel, body in created.items():
        p = root / "created" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (root / "feature.yaml").write_text(yaml.safe_dump({
        "feature_id": fid, "feature_name": f"Feature {fid}",
        "files_created": sorted(created), "files_modified": files_modified,
        "requires_features": requires or [],
        "rollback_classes": ["PURE_FILE"] + (["DEPENDENCY_LOCK"] if req_append else []),
        "origin_run_id": f"synthetic-{fid}", "origin_verdict": "PASS_ADAPTED",
    }, allow_unicode=True), encoding="utf-8")
    return FeatureBundle.load(root)


@pytest.fixture()
def stack(repo: Path, tmp_path: Path) -> FeatureStack:
    return FeatureStack.init(repo, tmp_path / "ledger")


@pytest.fixture()
def b_a(tmp_path: Path, repo: Path) -> FeatureBundle:
    return _mk_bundle(tmp_path, repo, "f_a",
                      created={"feature_a.py": "A = 1\n"},
                      req_append="pkg-a==1.0\n")


@pytest.fixture()
def b_b(tmp_path: Path, repo: Path) -> FeatureBundle:
    return _mk_bundle(tmp_path, repo, "f_b",
                      created={"feature_b.py": "B = 2\n"},
                      req_append="pkg-b==2.0\n")


@pytest.fixture()
def b_c(tmp_path: Path, repo: Path) -> FeatureBundle:
    return _mk_bundle(tmp_path, repo, "f_c",
                      created={"feature_c.py": "C = 3\n"},
                      requires=["f_b"])


# ---------------------------------------------------------------- 初始化

def test_init_records_s0_and_refuses_dirty(repo: Path, tmp_path: Path) -> None:
    st = FeatureStack.init(repo, tmp_path / "led1")
    assert st.ledger.active_state == "S0"
    assert st.ledger.states[0].tree_sha == st.tree_sha()
    (repo / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FeatureStackError, match="不洁"):
        FeatureStack.init(repo, tmp_path / "led2")
    (repo / "stray.txt").unlink()


def test_ledger_inside_tree_refused(repo: Path) -> None:
    with pytest.raises(FeatureStackError, match="工作树之内"):
        FeatureStack(repo, repo / "ledger")


# ---------------------------------------------------------------- apply

def test_apply_feature_full_chain(stack: FeatureStack, b_a: FeatureBundle,
                                  repo: Path) -> None:
    tx = stack.apply_feature(b_a)
    assert tx.result_state_id == "S1" and tx.parent_state_id == "S0"
    assert (repo / "feature_a.py").read_text(encoding="utf-8") == "A = 1\n"
    assert "pkg-a==1.0" in (repo / "requirements.txt").read_text(encoding="utf-8")
    assert stack.tree_sha() == tx.result_tree_sha
    assert (stack.ledger_dir / tx.manifest_file).exists()
    assert not (stack.ledger_dir / "journal.json").exists()
    assert stack.ledger.applied_order == [tx.transaction_id]
    # 运行态(gitignored)不进状态面,也不被 apply 触碰
    assert (repo / "runtime_data" / "db.bin").read_bytes() == b"\x00runtime"
    # git 簿记:每状态一提交,工作区洁净
    assert _git(repo, "status", "--porcelain") == ""


def test_apply_union_when_two_features_append_requirements(
        stack: FeatureStack, b_a: FeatureBundle, b_b: FeatureBundle,
        repo: Path) -> None:
    stack.apply_feature(b_a)
    stack.apply_feature(b_b)
    req = (repo / "requirements.txt").read_text(encoding="utf-8")
    assert "pkg-a==1.0" in req and "pkg-b==2.0" in req
    assert req.index("pkg-a==1.0") < req.index("pkg-b==2.0")  # ours→theirs 序
    assert "<<<<<<<" not in req


def test_apply_requires_gate(stack: FeatureStack, b_c: FeatureBundle) -> None:
    with pytest.raises(FeatureStackError, match="依赖未满足"):
        stack.apply_feature(b_c)


def test_apply_preserves_executable_bit_and_rollback_restores(
        stack: FeatureStack, tmp_path: Path, repo: Path) -> None:
    """T4 真发现 #1 钉死:755 created 文件曾在写回时掉成 644,git 树
    100755≠100644 被写回后树校验拒绝(f3 sidecar 构建脚本实况)。"""
    b = _mk_bundle(tmp_path, repo, "f_exec",
                   created={"scripts/build.sh": "#!/bin/sh\necho build\n"})
    script = Path(b.root) / "created" / "scripts" / "build.sh"
    os.chmod(script, 0o755)
    s0_sha = stack.tree_sha()
    tx = stack.apply_feature(b)          # 修复前此处抛"写回后树 ≠ staged"
    landed = repo / "scripts" / "build.sh"
    assert os.stat(landed).st_mode & 0o777 == 0o755
    assert stack.tree_sha() == tx.result_tree_sha
    stack.rollback_top(expect_feature_id="f_exec")
    assert not landed.exists() and stack.tree_sha() == s0_sha


# ---------------------------------------------------------------- rollback

def test_rollback_top_restores_exact_tree_and_state_reuse(
        stack: FeatureStack, b_a: FeatureBundle, repo: Path) -> None:
    s0_sha = stack.tree_sha()
    tx = stack.apply_feature(b_a)
    out = stack.rollback_top(expect_feature_id="f_a")
    assert out.status == "ROLLED_BACK" and out.rollback_verified
    assert stack.tree_sha() == s0_sha
    assert not (repo / "feature_a.py").exists()
    assert "pkg-a" not in (repo / "requirements.txt").read_text(encoding="utf-8")
    assert stack.ledger.active_state == "S0" and stack.ledger.applied_order == []
    # 状态复用:重施同特性 → 回到同一状态 id 与树
    tx2 = stack.apply_feature(b_a)
    assert tx2.result_state_id == "S1"
    assert tx2.result_tree_sha == tx.result_tree_sha


def test_rollback_lifo_only(stack: FeatureStack, b_a: FeatureBundle,
                            b_b: FeatureBundle) -> None:
    stack.apply_feature(b_a)
    stack.apply_feature(b_b)
    with pytest.raises(FeatureStackError, match="LIFO"):
        stack.rollback_top(expect_feature_id="f_a")


def test_rollback_empty_stack(stack: FeatureStack) -> None:
    with pytest.raises(FeatureStackError, match="栈为空"):
        stack.rollback_top()


# ---------------------------------------------------------------- 撤销规划

def test_removal_plan_three_kinds(stack: FeatureStack, b_a: FeatureBundle,
                                  b_b: FeatureBundle, b_c: FeatureBundle) -> None:
    stack.apply_feature(b_a)
    stack.apply_feature(b_b)
    stack.apply_feature(b_c)          # f_c requires f_b
    assert stack.removal_plan("f_c")["kind"] == "direct"
    plan_b = stack.removal_plan("f_b")
    assert plan_b["kind"] == "cascade"
    assert plan_b["dependents"] == ["f_c"]
    assert plan_b["cascade_order"] == ["f_c", "f_b"]
    plan_a = stack.removal_plan("f_a")
    assert plan_a["kind"] == "selective_rebuild"
    assert plan_a["dependents"] == []
    with pytest.raises(FeatureStackError, match="不在栈上"):
        stack.removal_plan("ghost")


def test_cascade_requires_explicit_confirmation(
        stack: FeatureStack, b_a: FeatureBundle, b_b: FeatureBundle,
        b_c: FeatureBundle, repo: Path) -> None:
    stack.apply_feature(b_a)
    s1_sha = stack.tree_sha()
    stack.apply_feature(b_b)
    stack.apply_feature(b_c)
    with pytest.raises(CascadeConfirmationRequired) as ei:
        stack.cascade_remove("f_b")
    assert ei.value.plan["cascade_order"] == ["f_c", "f_b"]
    # 半吊子确认同样拒绝
    with pytest.raises(CascadeConfirmationRequired):
        stack.cascade_remove("f_b", confirmed_features=["f_b"])
    stack.cascade_remove("f_b", confirmed_features=["f_c", "f_b"])
    assert stack.tree_sha() == s1_sha
    assert not (repo / "feature_b.py").exists()
    assert not (repo / "feature_c.py").exists()
    assert [stack.ledger.transactions[t].feature_id
            for t in stack.ledger.applied_order] == ["f_a"]


def test_cascade_refused_when_no_dependents(
        stack: FeatureStack, b_a: FeatureBundle, b_b: FeatureBundle) -> None:
    stack.apply_feature(b_a)
    stack.apply_feature(b_b)
    with pytest.raises(FeatureStackError, match="selective_rebuild"):
        stack.cascade_remove("f_a", confirmed_features=["f_b", "f_a"])


# ---------------------------------------------------------------- 选择性重建

def test_selective_rebuild_happy(stack: FeatureStack, b_a: FeatureBundle,
                                 b_b: FeatureBundle, repo: Path,
                                 tmp_path: Path) -> None:
    stack.apply_feature(b_a)
    stack.apply_feature(b_b)

    def verify(root: Path) -> bool:
        req = (root / "requirements.txt").read_text(encoding="utf-8")
        return ((root / "feature_b.py").exists()
                and not (root / "feature_a.py").exists()
                and "pkg-b==2.0" in req and "pkg-a" not in req)

    out = stack.selective_rebuild("f_a", bundles={"f_b": b_b},
                                  verify_fn=verify,
                                  scratch_dir=tmp_path / "scratch")
    assert out["tree_sha"] == stack.tree_sha()
    assert not (repo / "feature_a.py").exists()
    assert (repo / "feature_b.py").exists()
    req = (repo / "requirements.txt").read_text(encoding="utf-8")
    assert "pkg-b==2.0" in req and "pkg-a" not in req
    assert [stack.ledger.transactions[t].feature_id
            for t in stack.ledger.applied_order] == ["f_b"]


def test_selective_rebuild_tolerates_verify_side_effects(
        stack: FeatureStack, b_a: FeatureBundle, b_b: FeatureBundle,
        repo: Path, tmp_path: Path) -> None:
    """T4 R-C 首跑真发现 E4 钉死:全量验证会向 scratch 注入测试基建
    (公开面套件、fixtures)。确定性比对必须取 verify 前的构建时树,
    否则注入物入树 → 真栈重演后被误判"重建不确定"(栈已动,报错误导)。"""
    stack.apply_feature(b_a)
    stack.apply_feature(b_b)

    def verify_with_injection(root: Path) -> bool:
        (root / "public_tests").mkdir()
        (root / "public_tests" / "test_injected.py").write_text(
            "def test_ok(): pass\n", encoding="utf-8")   # 模拟台架注入
        return (root / "feature_b.py").exists() and not (root / "feature_a.py").exists()

    out = stack.selective_rebuild("f_a", bundles={"f_b": b_b},
                                  verify_fn=verify_with_injection,
                                  scratch_dir=tmp_path / "scratch-inj")
    assert out["tree_sha"] == stack.tree_sha()          # 修复前此处以"重建不确定"炸
    assert not (repo / "public_tests").exists()          # 注入物绝不进真栈
    assert not (repo / "feature_a.py").exists()
    assert (repo / "feature_b.py").exists()


def test_selective_rebuild_unsafe_leaves_stack_untouched(
        stack: FeatureStack, b_a: FeatureBundle, b_b: FeatureBundle,
        tmp_path: Path) -> None:
    stack.apply_feature(b_a)
    stack.apply_feature(b_b)
    before = stack.tree_sha()
    with pytest.raises(SelectiveRemovalNotSafe, match="SELECTIVE_REMOVAL_NOT_SAFE"):
        stack.selective_rebuild("f_a", bundles={"f_b": b_b},
                                verify_fn=lambda _root: False,
                                scratch_dir=tmp_path / "scratch2")
    assert stack.tree_sha() == before
    assert [stack.ledger.transactions[t].feature_id
            for t in stack.ledger.applied_order] == ["f_a", "f_b"]


def test_selective_rebuild_refused_on_declared_dependency(
        stack: FeatureStack, b_a: FeatureBundle, b_b: FeatureBundle,
        b_c: FeatureBundle, tmp_path: Path) -> None:
    stack.apply_feature(b_a)
    stack.apply_feature(b_b)
    stack.apply_feature(b_c)
    with pytest.raises(SelectiveRemovalNotSafe, match="声明依赖"):
        stack.selective_rebuild("f_b", bundles={"f_c": b_c},
                                verify_fn=lambda _root: True,
                                scratch_dir=tmp_path / "scratch3")


# ---------------------------------------------------------------- 崩溃恢复

class _Boom(KeyboardInterrupt):
    """硬中断模拟:BaseException 绕过 except Exception——与进程被杀同构。"""


def _interrupt_atomic_write_after(monkeypatch, n: int):
    real = apply_mod._atomic_write
    count = {"v": 0}

    def wrapper(target, data, **kw):
        count["v"] += 1
        if count["v"] > n:
            raise _Boom()
        real(target, data, **kw)

    monkeypatch.setattr(apply_mod, "_atomic_write", wrapper)
    return count


def test_recover_interrupted_apply(stack: FeatureStack, b_a: FeatureBundle,
                                   b_b: FeatureBundle, repo: Path,
                                   monkeypatch) -> None:
    stack.apply_feature(b_a)
    s1_sha = stack.tree_sha()
    _interrupt_atomic_write_after(monkeypatch, 1)   # 第 2 笔写时"进程死亡"
    with pytest.raises(KeyboardInterrupt):
        stack.apply_feature(b_b)
    monkeypatch.undo()
    # journal 未决:一切新事务被拒
    with pytest.raises(StackJournalPending):
        stack.apply_feature(b_b)
    with pytest.raises(StackJournalPending):
        stack.rollback_top()
    report = stack.recover_interrupted()
    assert report["recovered"] and report["phase"] == "applying"
    assert report["restored_to"] == "S1"
    assert stack.tree_sha() == s1_sha
    assert not (repo / "feature_b.py").exists()
    # 恢复后可正常继续
    tx = stack.apply_feature(b_b)
    assert tx.result_state_id == "S2"


def test_recover_reaps_dead_staging_left_by_hard_kill(
        stack: FeatureStack, b_a: FeatureBundle, b_b: FeatureBundle,
        monkeypatch) -> None:
    """T4 R-E(b) 真发现 E5 钉死:进程内异常 finally 会清 staging,
    kill -9 不会——残留 staged-<fid> 曾把复活后的同特性重试挡死。
    recover 必须收殓 journal 点名事务的 staging;无关残留仍守卫。"""
    stack.apply_feature(b_a)
    _interrupt_atomic_write_after(monkeypatch, 1)
    with pytest.raises(KeyboardInterrupt):
        stack.apply_feature(b_b)
    monkeypatch.undo()
    # 复刻进程死亡:finally 清掉的 staging 重新在盘(kill -9 时它就在)
    dead = stack.ledger_dir / "work" / "staged-f_b"
    dead.mkdir(parents=True)
    (dead / "leftover.txt").write_text("orphan", encoding="utf-8")
    other = stack.ledger_dir / "work" / "staged-unrelated"
    other.mkdir(parents=True)
    stack.recover_interrupted()
    assert not dead.exists()                       # 死事务 staging 被收殓
    assert other.exists()                          # 无关残留不动(仍守卫)
    tx = stack.apply_feature(b_b)                  # 修复前此处被"不覆盖"挡死
    assert tx.result_state_id == "S2"


def test_recover_interrupted_rollback(stack: FeatureStack, b_a: FeatureBundle,
                                      repo: Path, monkeypatch) -> None:
    s0_sha = stack.tree_sha()
    stack.apply_feature(b_a)
    _interrupt_atomic_write_after(monkeypatch, 0)   # 回滚第 1 笔恢复写即死
    with pytest.raises(KeyboardInterrupt):
        stack.rollback_top()
    monkeypatch.undo()
    report = stack.recover_interrupted()
    assert report["recovered"] and report["phase"] == "rolling_back"
    assert stack.tree_sha() == s0_sha
    assert stack.ledger.active_state == "S0"
    assert stack.ledger.applied_order == []
    assert not (repo / "feature_a.py").exists()


def test_recover_noop_without_journal(stack: FeatureStack) -> None:
    assert stack.recover_interrupted() == {"recovered": False, "reason": "无未决 journal"}


# ---------------------------------------------------------------- union 细节

def test_conflict_outside_union_allowlist_refused(
        stack: FeatureStack, tmp_path: Path, repo: Path) -> None:
    """app.py 上下文不可合(非 UNION_FILES)→ 硬拒,栈零改动。"""
    bad = tmp_path / "patchwork-z"
    subprocess.run(["cp", "-R", str(repo), str(bad)], check=True)
    _git(bad, "reset", "-q", "--hard")
    (bad / "app.py").write_text("totally different base\n", encoding="utf-8")
    _git(bad, "add", "-A")
    _git(bad, "commit", "-qm", "diverge")
    (bad / "app.py").write_text("totally different base\nplus feature x\n",
                                encoding="utf-8")
    patch = _git(bad, "diff")
    root = tmp_path / "bundle-x"
    (root / "created").mkdir(parents=True)
    (root / "modified.patch").write_text(patch + "\n", encoding="utf-8")
    (root / "feature.yaml").write_text(yaml.safe_dump({
        "feature_id": "f_x", "files_created": [],
        "files_modified": ["app.py"], "origin_verdict": "PASS_ADAPTED",
    }), encoding="utf-8")
    bx = FeatureBundle.load(root)
    before = stack.tree_sha()
    with pytest.raises(FeatureStackError):
        stack.apply_feature(bx)
    assert stack.tree_sha() == before


def test_bundle_manifest_mismatch_refused(tmp_path: Path, repo: Path) -> None:
    root = tmp_path / "bundle-bad"
    (root / "created").mkdir(parents=True)
    (root / "created" / "one.py").write_text("1\n", encoding="utf-8")
    (root / "feature.yaml").write_text(yaml.safe_dump({
        "feature_id": "f_bad", "files_created": ["one.py", "two.py"],
        "files_modified": [],
    }), encoding="utf-8")
    with pytest.raises(FeatureStackError, match="不一致"):
        FeatureBundle.load(root)
