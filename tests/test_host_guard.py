"""主目录硬护栏 + 保护目录指纹对账(Phase 0 ①,TESTPLAN-V2 §4 第 1/6 层)。

钉死:路径变体(大小写/软链/~/子路径)全拦截;apply/stage/rollback
三个写入口无旁路;指纹对 untracked 新增、内容改动、git refs 变动
全部报警;无改动则对账通过。
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from repoproof.harness.host_guard import (
    EXTERNAL,
    SELF,
    HostGuardError,
    SelfWriteWindow,
    assert_writable_target,
    dir_fingerprint,
    is_protected,
    snapshot_protected,
    verify_protected_unchanged,
)


def _prot(tmp_path: Path) -> tuple[Path, list[str]]:
    # 保护表登记**真实大小写** realpath(protected_dirs 现行为)——lower
    # 键只活在比对侧;登记 lower 路径在 ext4 上根本 stat 不到,快照会
    # 静默漏保护(CI Linux 预演实测)。大小写变体拦截语义由
    # test_path_variants_all_blocked 钉。
    real = tmp_path / "XIANGMU" / "offerclaw"
    (real / "src").mkdir(parents=True)
    (real / "src" / "app.py").write_text("X = 1\n", encoding="utf-8")
    import os

    return real, [os.path.realpath(str(real))]


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


# ---------------- 变动归因:谁写的(2026-08-17,邻仓活写手拖红实证) ----------------
# 背景:保护清单含 XIANGMU 下全部邻仓,而 offerclaw 的 logs/llm_usage.jsonl
# 每 7–28 秒落盘一次。冒烟链 83 秒里会话只存在 1.24 秒,外部写手压倒性地落在
# "会话根本不存在"的时段。归因层要做的是把这两类分开——**而不是把闸门掏空**:
# 下面每一条"降级"用例都配一条"照样红"的负控,一一对应。


def _bg_writer(path: Path, stop: threading.Event, period_s: float = 0.02):
    """模拟外部活写手:持续改同一条路径,直到被叫停。"""
    def loop() -> None:
        i = 0
        while not stop.is_set():
            i += 1
            path.write_text(f"tick {i}\n" * i, encoding="utf-8")
            time.sleep(period_s)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


def _only(out: dict) -> dict:
    """唯一一条 mismatch 的 attribution(用例都构造成只动一处)。"""
    assert len(out["mismatches"]) == 1, out["mismatches"]
    return out["mismatches"][0]["attribution"]


def _reason_of(attr: dict, rel: str) -> str:
    for c in attr["self_changes"] + attr["external_changes"]:
        if c["path"] == rel:
            return c["reason"]
    raise AssertionError(f"{rel} 未出现在归因明细里:{attr}")


def test_write_outside_self_window_is_attributed_external(tmp_path: Path) -> None:
    """窗外发生的写 = 会话当时根本不存在 → 免罪,但严判 ok 照样为 False。"""
    real, prot = _prot(tmp_path)
    before = snapshot_protected(prot)
    # 尺寸必须变:Linux 内核 mtime 粒度 ~1ms,快照后亚毫秒内的**同尺寸**
    # 重写两平台可见性不同(CI 预演实测);size 分量不依赖时钟。
    (real / "src" / "app.py").write_text("X = 2 + 40\n", encoding="utf-8")

    now = time.time()
    out = verify_protected_unchanged(          # 窗口整个落在未来 → 此写在窗外
        before, prot, self_window=SelfWriteWindow(start=now + 100, end=now + 200),
        probe_s=0.3, probe_interval_s=0.05)

    assert not out["ok"]                       # 严判语义一字未改:守卫仍抓到了
    assert out["self_ok"]                      # 归因后不算在本链头上
    attr = _only(out)
    assert attr["verdict"] == EXTERNAL
    assert _reason_of(attr, "src/app.py") == "EXTERNAL_OUT_OF_WINDOW"


def test_quiet_write_inside_self_window_stays_red(tmp_path: Path) -> None:
    """**负控**:窗内写、拆除后不再动 → 只能是本链干的,照样红。"""
    real, prot = _prot(tmp_path)
    before = snapshot_protected(prot)
    (real / "src" / "app.py").write_text("X = 2 + 40\n", encoding="utf-8")   # 尺寸变 → 跨平台确定可见

    now = time.time()
    out = verify_protected_unchanged(
        before, prot, self_window=SelfWriteWindow(start=now - 10, end=now + 10),
        probe_s=0.3, probe_interval_s=0.05)

    assert not out["ok"] and not out["self_ok"]
    attr = _only(out)
    assert attr["verdict"] == SELF
    assert _reason_of(attr, "src/app.py") == "SELF_IN_WINDOW_QUIESCENT"


def test_live_writer_inside_window_is_attributed_external(tmp_path: Path) -> None:
    """窗内动过、拆除后**还在动** → 有外部活写手,免罪(理由逐条留痕)。"""
    real, prot = _prot(tmp_path)
    before = snapshot_protected(prot)
    stop = threading.Event()
    _bg_writer(real / "src" / "app.py", stop)
    time.sleep(0.1)                            # 让它先写一笔,制造 mismatch
    try:
        now = time.time()
        out = verify_protected_unchanged(
            before, prot, self_window=SelfWriteWindow(start=now - 10, end=now + 10),
            probe_s=2.0, probe_interval_s=0.05)
    finally:
        stop.set()

    assert not out["ok"] and out["self_ok"]
    attr = _only(out)
    assert attr["verdict"] == EXTERNAL
    assert _reason_of(attr, "src/app.py") == "EXTERNAL_LIVE_WRITER"
    assert attr["probe"]["samples"] >= 1


def test_busy_sibling_does_not_launder_a_quiet_self_write(tmp_path: Path) -> None:
    """**负控**:同目录里有个忙文件,不给隔壁那条静默自写洗白。

    探针只盯路径本身、不看兄弟不看父目录——否则热闹目录就成了洗白通道
    (LESSONS #29 同型:放行一个目录不等于放行它装的一切)。"""
    real, prot = _prot(tmp_path)
    (real / "src" / "busy.log").write_text("0\n", encoding="utf-8")
    before = snapshot_protected(prot)

    (real / "src" / "app.py").write_text("X = 2 + 40\n", encoding="utf-8")   # 尺寸变 → 跨平台确定可见   # 静默自写
    stop = threading.Event()
    _bg_writer(real / "src" / "busy.log", stop)                         # 忙邻居
    time.sleep(0.1)
    try:
        now = time.time()
        out = verify_protected_unchanged(
            before, prot, self_window=SelfWriteWindow(start=now - 10, end=now + 10),
            probe_s=1.0, probe_interval_s=0.05)
    finally:
        stop.set()

    assert not out["ok"] and not out["self_ok"]      # 忙邻居没能把整条 mismatch 洗白
    attr = _only(out)
    assert attr["verdict"] == SELF
    assert _reason_of(attr, "src/app.py") == "SELF_IN_WINDOW_QUIESCENT"
    assert _reason_of(attr, "src/busy.log") == "EXTERNAL_LIVE_WRITER"


def test_deletion_has_no_timestamp_so_it_stays_red(tmp_path: Path) -> None:
    """**负控**:删除拿不到作案时刻 → 免罪的正面证据不存在 → 继续红。"""
    real, prot = _prot(tmp_path)
    before = snapshot_protected(prot)
    (real / "src" / "app.py").unlink()

    now = time.time()
    out = verify_protected_unchanged(          # 连"窗口全在未来"都不给免
        before, prot, self_window=SelfWriteWindow(start=now + 100, end=now + 200),
        probe_s=0.3, probe_interval_s=0.05)

    assert not out["ok"] and not out["self_ok"]
    assert _reason_of(_only(out), "src/app.py") == "SELF_NO_TIMESTAMP"


def test_without_window_nothing_is_ever_exonerated(tmp_path: Path) -> None:
    """**负控**:不传窗口 = 没有归因依据 → `self_ok` 恒等于 `ok`。

    这条护住正式 run 那条路径(`runner/host_guided.py` 不传窗口):
    有 agent 在场时归因只作证据,一个字节的免罪权都没有。"""
    real, prot = _prot(tmp_path)
    before = snapshot_protected(prot)
    (real / "src" / "app.py").write_text("X = 2 + 40\n", encoding="utf-8")   # 尺寸变 → 跨平台确定可见

    out = verify_protected_unchanged(before, prot)
    assert not out["ok"] and not out["self_ok"] and not out["attributed"]
    assert _reason_of(_only(out), "src/app.py") == "SELF_NO_WINDOW"


def test_baseline_without_entries_is_not_amnesty(tmp_path: Path) -> None:
    """**负控**:基线指纹没有 entries(旧格式)→ 无从比对 → 继续红。

    此处最阴的失效方向是"当成空 dict 硬比":满树文件全算成新增,再各按
    自己的 mtime 大面积免罪 —— 一条守卫会因为读不到基线而当场自宫。"""
    real, prot = _prot(tmp_path)
    before = snapshot_protected(prot)
    legacy = {d: {k: v for k, v in fp.items() if k != "entries"}
              for d, fp in before.items()}          # 退化成旧格式指纹
    (real / "src" / "app.py").write_text("X = 2 + 40\n", encoding="utf-8")   # 尺寸变 → 跨平台确定可见

    now = time.time()
    out = verify_protected_unchanged(               # 窗口全在未来也不许免
        legacy, prot, self_window=SelfWriteWindow(start=now + 100, end=now + 200),
        probe_s=0.3, probe_interval_s=0.05)

    assert not out["ok"] and not out["self_ok"], out
    assert _reason_of(_only(out), "<no-baseline-entries>") == "SELF_NO_TIMESTAMP"


def test_hash_mismatch_with_no_listable_change_is_not_amnesty(tmp_path: Path) -> None:
    """**负控**:哈希对不上却列不出改动 → 说不清,不许免罪。

    空改动表在 Python 里恒假,顺着写就会把"列不出可疑改动"读成"没有可疑
    改动"而自动免罪 —— 闸门被一个 bug 打开,而且是静悄悄地开。"""
    from repoproof.harness.host_guard import _attribute

    now = time.time()
    attr = _attribute(tmp_path, [], SelfWriteWindow(start=now - 10, end=now + 10),
                      probe_s=0.3, probe_interval_s=0.05)
    assert attr["verdict"] == SELF and attr["n_self"] == 1, attr
    assert attr["self_changes"][0]["reason"] == "SELF_NO_EVIDENCE"


def test_git_refs_without_witnesses_is_not_amnesty(tmp_path: Path) -> None:
    """**负控**:refs 变了但找不到证人文件 → 拿不到作案时刻 → 继续红。"""
    real, prot = _prot(tmp_path)
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1"]):
        subprocess.run(["git", "-C", str(real), *args], check=True)
    before = snapshot_protected(prot)
    shutil.rmtree(real / ".git")                    # 证人没了(refs 摘要随之变)

    now = time.time()
    out = verify_protected_unchanged(
        before, prot, self_window=SelfWriteWindow(start=now + 100, end=now + 200),
        probe_s=0.3, probe_interval_s=0.05)

    assert not out["ok"] and not out["self_ok"], out
    assert out["mismatches"][0]["field"] == "git_refs"
    assert _reason_of(_only(out), ".git") == "SELF_NO_TIMESTAMP"


def test_git_refs_change_attributed_by_witness_mtime(tmp_path: Path) -> None:
    """refs 变动按证人文件(HEAD/refs/logs)的 mtime 定责,两个方向各钉一次。"""
    real, prot = _prot(tmp_path)
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "v1"]):
        subprocess.run(["git", "-C", str(real), *args], check=True)
    before = snapshot_protected(prot)
    subprocess.run(["git", "-C", str(real), "-c", "user.email=t@t", "-c",
                    "user.name=t", "commit", "-qm", "v2", "--allow-empty"], check=True)

    now = time.time()
    outside = verify_protected_unchanged(      # 证人都在窗外 → 不是本链改的
        before, prot, self_window=SelfWriteWindow(start=now + 100, end=now + 200),
        probe_s=0.3, probe_interval_s=0.05)
    assert not outside["ok"] and outside["self_ok"]
    assert outside["mismatches"][0]["field"] == "git_refs"
    assert outside["mismatches"][0]["attribution"]["verdict"] == EXTERNAL

    inside = verify_protected_unchanged(       # **负控**:证人在窗内 → 照样红
        before, prot, self_window=SelfWriteWindow(start=now - 30, end=now + 10),
        probe_s=0.3, probe_interval_s=0.05)
    assert not inside["ok"] and not inside["self_ok"]
    assert inside["mismatches"][0]["attribution"]["verdict"] == SELF


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
