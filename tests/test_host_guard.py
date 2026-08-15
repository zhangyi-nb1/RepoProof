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


# ---------------- bench 根环境卫生门(T2 批 1 实证教训) ----------------

def test_bench_hygiene_clean_root_passes(tmp_path: Path) -> None:
    from repoproof.harness.host_guard import bench_root_strays
    for name in ("offerclaw-t2-odr", "wheelhouse-offerclaw-85278e6", "_sessions"):
        (tmp_path / name).mkdir()
    (tmp_path / ".DS_Store").write_text("")
    assert bench_root_strays(tmp_path) == []


def test_bench_hygiene_stray_workspace_detected(tmp_path: Path) -> None:
    """批 1 实录形态:正控工作区/兼容实验场/真实数据备份必须全部报警。"""
    from repoproof.harness.host_guard import bench_root_strays
    (tmp_path / "offerclaw-t2-odr").mkdir()
    for stray in ("_scratch_t2_positive", "_scratch_odr_compat",
                  "_offerclaw_untracked_backup_20260809", "notes.txt"):
        p = tmp_path / stray
        (p.mkdir() if not stray.endswith(".txt") else p.write_text("x"))
    assert bench_root_strays(tmp_path) == [
        "_offerclaw_untracked_backup_20260809", "_scratch_odr_compat",
        "_scratch_t2_positive", "notes.txt"]


def test_bench_hygiene_env_extra_prefix_allowed(tmp_path: Path, monkeypatch) -> None:
    from repoproof.harness.host_guard import bench_root_strays
    (tmp_path / "localflow-t9-copy").mkdir()
    assert bench_root_strays(tmp_path) == ["localflow-t9-copy"]
    monkeypatch.setenv("REPOPROOF_BENCH_ALLOWED", "localflow-")
    assert bench_root_strays(tmp_path) == []


def test_bench_hygiene_missing_root_is_clean(tmp_path: Path) -> None:
    from repoproof.harness.host_guard import bench_root_strays
    assert bench_root_strays(tmp_path / "nope") == []


def test_bench_hygiene_offerclaw_prefix_is_not_a_free_pass(tmp_path: Path) -> None:
    """2026-08-12 实录(LESSONS #29):前缀白名单把 T4 事务栈放行了。

    `offerclaw-transaction-stack/` 里装的是 T1/T2/T3 三份**已验证 PASS 解**,
    只因名字以 `offerclaw-` 开头就被当成宿主副本放行——而 agent 一条
    `ls ..` 就能读到 bench 根。名单必须精确到"就是那三个宿主副本"。
    """
    from repoproof.harness.host_guard import bench_root_strays
    for name in ("offerclaw-t1-fastapi-mcp", "offerclaw-t2-odr",
                 "offerclaw-t3-browser-use", "_sessions"):
        (tmp_path / name).mkdir()
    assert bench_root_strays(tmp_path) == [], "三个具名宿主副本必须放行"

    for name in ("offerclaw-transaction-stack",
                 "offerclaw-transaction-stack-ledger",
                 "offerclaw-t9-not-registered"):
        (tmp_path / name).mkdir()
    assert bench_root_strays(tmp_path) == [
        "offerclaw-t9-not-registered",
        "offerclaw-transaction-stack",
        "offerclaw-transaction-stack-ledger",
    ], "带 offerclaw- 前缀不等于是登记过的宿主副本"


def test_bench_hygiene_flags_vendored_upstream(tmp_path: Path) -> None:
    """T4 栈的兄弟目录 `upstream/`(F2 运行时 vendor)也不得留在 bench 根。

    它本身无害(干净上游快照),但它的存在意味着整个 T4 栈就在隔壁——
    真正该迁走的是那一整套,不是给它开个口子。
    """
    from repoproof.harness.host_guard import bench_root_strays
    (tmp_path / "offerclaw-t3-browser-use").mkdir()
    (tmp_path / "upstream").mkdir()
    assert bench_root_strays(tmp_path) == ["upstream"]


_REPO = Path(__file__).resolve().parents[1]


def test_bench_allowlist_is_two_levels_deep():
    """放行一个目录**不等于**放行它装的一切(LESSONS #29 同型第二次)。

    2026-08-15 对抗性搜捕实录:`host2-flask-smorest/` 在白名单里,于是它里面
    同时装着交付树 `host/`、**未挖空的原件 `repo/`(含 .git 与 554 条隐藏
    oracle)**、一个 `.pth` 指回原件的 venv —— 全部一张票放行。一条
    `cat .pth` 就把被挖的 12 个函数体逐字节取回。

    这与 #29 那次完全同型:`offerclaw-transaction-stack/` 内含三份已验证
    PASS 解被整个放行。当时的结论是"改精确名单",但只改了一层 ——
    **一层名单挡不住"合法目录里装着不该有的东西"。**
    """
    import sys

    sys.path.insert(0, str(_REPO / "src"))
    from repoproof.harness.host_guard import (
        _BENCH_ALLOWED_ENTRIES,
        bench_root_strays,
    )

    assert "host2-flask-smorest" in _BENCH_ALLOWED_ENTRIES
    assert _BENCH_ALLOWED_ENTRIES["host2-flask-smorest"] == frozenset({"host", "wheelhouse"})

    root = Path("~/RepoProofBench").expanduser()
    if not root.is_dir():
        pytest.skip("bench 根不在本机")
    assert bench_root_strays() == [], f"bench 根不干净:{bench_root_strays()}"

    # 判别力:登记目录里塞一样不该有的,必须报出来(带目录前缀,好定位)
    probe = root / "host2-flask-smorest" / "_rp_probe_stray"
    if not (root / "host2-flask-smorest").is_dir():
        pytest.skip("第二宿主不在本机")
    try:
        probe.mkdir()
        got = bench_root_strays()
        assert "host2-flask-smorest/_rp_probe_stray" in got, (
            f"登记目录内部的杂物没被报出来:{got}")
    finally:
        probe.rmdir()
