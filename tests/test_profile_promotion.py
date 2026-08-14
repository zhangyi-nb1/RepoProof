"""Runtime Profile 晋级判据的钉死(判据 G1–G8 冻结在 profile_promotion.py)。

生命周期不是标签,是**对外承诺** —— 它决定别人敢不敢拿这个 profile 的发次
当数。所以两件事必须钉住:判据本身管不管用,以及**声明与留痕对不对得上**。

- P1 **证据缺失一律拒绝**。反例:查不到证据就默认放行 → 这样的闸门与没有
  闸门的区别,只在于它会让人误以为有闸门。
- P2 **别人的体检报告不能拿来给自己晋级**。反例:矩阵证的是 A profile,
  却给 B profile 放行。
- P3 **不得跳级**。反例:experimental 直接跳 qualified → 拿真实发次去替
  "机制站不站得住"背书,而那是两个问题。
- P4 **qualified 必须有真实发次**,且参考实现不算数。反例:我们自己的
  adapter 过了就算 → 那叫出题人自己会做,不叫题目可解。
- P5 **default/deprecated 机器判不了,且判不了 = 不通过**。反例:返回
  "暂且通过" → 把一个取舍伪装成一个测量。
- P6 **声明与留痕一致**:代码里写着 candidate 的 profile,留痕里必须有那
  一次晋级。反例:直接改字段自封 —— 那把"凭什么"这件事整个抹掉了。
- P7 **全捕的判据不读 capture_rate 字符串**。反例:解析失败时顺手当成通过
  —— "闸门看起来在,其实没在"的经典形态。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "benchmarks" / "v2" / "sidecar_conformance"))
sys.path.insert(0, str(REPO / "benchmarks" / "v2" / "receipt_controls"))

import profile as CANARY  # noqa: E402  —— 登记 rt-sidecar-canary-v1

import sidecar as MDIT  # noqa: E402  —— 登记 rt-sidecar-markdown-it-v1

from repoproof.execution.profile_promotion import (  # noqa: E402
    LIFECYCLE_ORDER,
    MIN_HONEST_PASSES,
    MIN_MODEL_PROFILES,
    evaluate_promotion,
)
from repoproof.execution.runtime_profiles import known_profiles  # noqa: E402

PROMOTIONS = REPO / "docs" / "evidence" / "profile_lifecycle" / "promotions.jsonl"


def test_p1_missing_evidence_refuses(tmp_path):
    """P1:证据不在就拒绝晋级,不假设。"""
    v = evaluate_promotion(CANARY.PROFILE_ID, repo=tmp_path, to="candidate")
    assert not v.ok
    ids = {c.id for c in v.failed()}
    assert "G1-G4.evidence" in ids and "G5.mutation" in ids, ids


def test_p2_another_profiles_evidence_does_not_count(tmp_path):
    """P2:矩阵证的是别人,不得给自己放行。"""
    ev = tmp_path / "docs" / "evidence" / "sidecar_conformance"
    ev.mkdir(parents=True)
    real = json.loads((REPO / "docs" / "evidence" / "sidecar_conformance"
                       / "matrix.json").read_text(encoding="utf-8"))
    real["profile_id"] = "rt-somebody-else-v1"
    (ev / "matrix.json").write_text(json.dumps(real, ensure_ascii=False), encoding="utf-8")

    v = evaluate_promotion(CANARY.PROFILE_ID, repo=tmp_path, to="candidate")
    d = next(c.detail for c in v.failed() if c.id == "G1-G4.evidence")
    assert "不是" in d and "体检报告" in d


def test_p3_no_skipping_a_level():
    """P3:experimental 不得直接跳 qualified。"""
    v = evaluate_promotion(MDIT.PROFILE_ID, repo=REPO, to="qualified")
    assert not v.ok
    assert any(c.id == "G0.no_skipping" for c in v.failed())


def test_p4_qualified_needs_real_model_runs():
    """P4:→ qualified 必须有真实发次,参考实现不算数。"""
    v = evaluate_promotion(CANARY.PROFILE_ID, repo=REPO, to="qualified")
    assert not v.ok
    red = {c.id for c in v.failed()}
    assert {"G6.model_profiles", "G6b.honest_pass"} <= red, red
    assert MIN_MODEL_PROFILES >= 2 and MIN_HONEST_PASSES >= 1, (
        "门槛被调低了 —— 这两个数是预先写死的,改它需要新的理由与留痕")


def test_p4b_fake_scripted_runs_never_count_as_real():
    """P4 的具体形态:冒烟发次不得充真实发次。

    反例:`--fake positive` 必定 PASS(harness 自己把正控塞进去的),
    拿它当"模型跑通了"是最容易发生的一种自欺。"""
    src = (REPO / "src" / "repoproof" / "execution"
           / "profile_promotion.py").read_text(encoding="utf-8")
    assert 'startswith("fake")' in src, "真实发次的筛选不再排除 fake-scripted"


def test_p5_default_is_not_machine_decidable():
    """P5:default/deprecated 判不了,而且**判不了 = 不通过**。

    关键在于:那条 Check 自己是 `ok=True`(它是事实陈述,不是没过的判据),
    **压 False 的是 `machine_decidable` 本身**。这样写才使"判不了 = 不通过"
    真的被某样东西执行 —— 若那条 Check 也写成 ok=False,`machine and` 就成了
    死代码,纪律只是碰巧成立(变异闸门 M53e 当场指出了这一点)。"""
    for target in ("default", "deprecated"):
        v = evaluate_promotion(CANARY.PROFILE_ID, repo=REPO, to=target)
        assert v.machine_decidable is False
        assert all(c.ok for c in v.checks), (
            "这一级的 Check 应当是事实陈述(ok=True)—— 否则 machine 那道成死代码")
        assert v.ok is False, "判不了却返回通过 —— 那是把取舍伪装成测量"


def test_p6_declared_lifecycle_matches_the_promotion_ledger():
    """P6:代码里声明的 lifecycle,必须在留痕里找得到对应那次晋级。

    反例:直接改字段自封 candidate —— 把"凭什么"整个抹掉。
    起点 experimental 与内置的 in-process default 不需要留痕(前者是所有新
    profile 的起点,后者是既有全部发次的行为,先于本机制存在)。"""
    recorded: dict[str, str] = {}
    if PROMOTIONS.is_file():
        for line in PROMOTIONS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("ok"):
                    recorded[r["profile_id"]] = r["to"]

    for pid, p in known_profiles().items():
        if p.lifecycle == "experimental" or pid == "rt-inprocess-v1":
            continue
        assert recorded.get(pid) == p.lifecycle, (
            f"{pid} 声明 {p.lifecycle},但留痕里是 {recorded.get(pid)!r} —— "
            "改字段自封等于把'凭什么'抹掉;跑 scripts/promote_profile.py --record")


def test_p7_capture_rate_string_is_not_the_criterion():
    """P7:全捕的判据不读 `capture_rate` 字符串,读逃逸/过期。"""
    src = (REPO / "src" / "repoproof" / "execution"
           / "profile_promotion.py").read_text(encoding="utf-8")
    assert 'ev.get("capture_rate")' not in src, (
        "又去读 capture_rate 了 —— 它的形状变过(101/101 / 100% / 1.0),"
        "解析失败最容易被当成通过")
    assert 'ev.get("escaped")' in src and 'ev.get("stale")' in src


def test_p7b_unparseable_mutation_evidence_fails_closed(tmp_path):
    """P7 的失效方向:读不出逃逸/过期时**判不过**,不是判过。"""
    from repoproof.execution.profile_promotion import _check_mutations

    c = _check_mutations(tmp_path, evidence={
        "capture_rate": "100%", "escaped": "无", "stale": None,
        "results": [{"id": "M49a"}, {"id": "M50a"}, {"id": "M52a"}]})
    assert not c.ok and "读不出" in c.detail


def test_an_empty_registry_of_mutations_does_not_pass(tmp_path):
    """G5 的另一半:登记簿里没有守这套机制的条目 → 不算数。

    反例:捕获率 100% 但一条相关的都没有 —— 那个 100% 与本 profile 无关。"""
    from repoproof.execution.profile_promotion import _check_mutations

    c = _check_mutations(tmp_path, evidence={
        "escaped": [], "stale": [], "results": [{"id": "M30a-unrelated"}]})
    assert not c.ok and "缺守护条目" in c.detail


def test_canary_is_candidate_and_still_earns_g1_to_g4():
    """接线:canary 是 candidate,且 G1–G4 **现算**仍然全过。

    为什么这里不现算 G5:变异证据按 HEAD 命名,**每个 commit 一份**,而
    刚提交的 commit 上还没跑过 —— 现算必然报"这个 commit 上没有证据"。
    那不是缺陷,正是 G5 想要的严格性(旧 commit 的绿不为新代码背书)。

    于是分工:G1–G4 的证据(conformance 矩阵)是稳定的落盘件,这里现算;
    G5 属于"晋级那一刻的事实",由留痕(P6)与晋级脚本负责。想现场复核,
    跑 `scripts/mutation_gate.py` 之后再跑 `scripts/promote_profile.py`。"""
    assert CANARY.PROFILE.lifecycle == "candidate"
    v = evaluate_promotion(CANARY.PROFILE_ID, repo=REPO, to="candidate")
    assert {c.id for c in v.checks} == {
        "G1.topology", "G2.no_false_kill", "G3.reds_where_declared",
        "G4.discrimination", "G5.mutation"}
    live = {c.id: c for c in v.checks if c.id != "G5.mutation"}
    assert all(c.ok for c in live.values()), [c.detail for c in live.values() if not c.ok]


def _tiny_repo(tmp_path: Path, *, guarded_rel: str = "src/guarded.py") -> tuple[Path, str]:
    """造一个最小 git 仓:一个提交 + 一份指向它的变异证据。"""
    import subprocess

    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a],                 # noqa: S603
                       capture_output=True, check=True)

    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / guarded_rel).write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "unrelated.md").write_text("hi\n", encoding="utf-8")
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "base")
    head = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"],   # noqa: S603
                          capture_output=True, text=True, check=True).stdout.strip()

    d = tmp_path / "docs" / "evidence" / "mutation_gate"
    d.mkdir(parents=True)
    (d / f"{head[:12]}.json").write_text(json.dumps({
        "head_commit": head, "escaped": [], "stale": [],
        "results": [{"id": "M49a", "file": guarded_rel,
                     "catchers": ["tests/test_guarded.py"]},
                    {"id": "M50a", "file": guarded_rel, "catchers": []},
                    {"id": "M52a", "file": guarded_rel, "catchers": []}]}),
        encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "evidence")
    return tmp_path, head


def _commit(repo: Path, msg: str) -> None:
    import subprocess

    subprocess.run(["git", "-C", str(repo), "add", "-A"],                # noqa: S603
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", msg],       # noqa: S603
                   capture_output=True, check=True)


def test_g5_needs_a_git_head_to_judge_evidence(tmp_path):
    """G5:不是 git 仓 → 判不过(而不是"目录里只有一份就用那份")。"""
    from repoproof.execution.profile_promotion import _check_mutations

    d = tmp_path / "docs" / "evidence" / "mutation_gate"
    d.mkdir(parents=True)
    (d / "deadbeefcafe.json").write_text(json.dumps(
        {"head_commit": "deadbeefcafe", "escaped": [], "stale": [],
         "results": [{"id": "M49a"}, {"id": "M50a"}, {"id": "M52a"}]}),
        encoding="utf-8")
    assert not _check_mutations(tmp_path).ok


def test_g5_evidence_survives_an_unrelated_change(tmp_path):
    """G5 语义(一侧):**不相干的改动不该让证据作废**。

    反例(前一版实现):只认 HEAD 那一份 → 提交证据本身就产生新 HEAD,
    于是 HEAD 上永远没有证据,G5 永远过不了。一道永远过不了的判据不是严格,
    是墙(LESSONS #44)。

    这条同时挡住"把钉死写成读真仓当前状态"那个错法 —— 那样任何一次改动
    守护文件都会让套件红,而 verify_integrity 是先跑套件再跑变异闸门,
    一趟永远绿不了。判据要考的是**函数的语义**,不是仓库此刻的状态。"""
    from repoproof.execution.profile_promotion import _mutation_evidence_for_head

    repo, _ = _tiny_repo(tmp_path)
    (repo / "unrelated.md").write_text("changed\n", encoding="utf-8")
    _commit(repo, "docs only")

    ev, why = _mutation_evidence_for_head(repo)
    assert ev is not None, f"不相干的改动把证据判废了:{why}"
    assert "未触及" in why


def test_g5_evidence_expires_when_a_guarded_file_changes(tmp_path):
    """G5 语义(另一侧):**相干的改动必须让证据作废**。

    反例:改了被变异守护的源文件却仍拿旧证据背书 —— 与"改完不重跑"没区别。

    两侧都要考:只考这一侧会写出一道永远作废的判据,只考另一侧会写出一道
    永远有效的判据 —— 两种都不携带信息。"""
    from repoproof.execution.profile_promotion import _mutation_evidence_for_head

    repo, _ = _tiny_repo(tmp_path)
    (repo / "src" / "guarded.py").write_text("X = 2\n", encoding="utf-8")
    _commit(repo, "touch guarded")

    ev, why = _mutation_evidence_for_head(repo)
    assert ev is None, "守护的文件改过,证据却仍被接受"
    assert "守护的文件此后改过" in why


def test_g5_evidence_from_a_foreign_branch_does_not_count(tmp_path):
    """G5:head_commit 不是 HEAD 祖先的证据不算数(别的分支跑出来的绿)。"""
    from repoproof.execution.profile_promotion import _mutation_evidence_for_head

    repo, _ = _tiny_repo(tmp_path)
    (repo / "docs" / "evidence" / "mutation_gate" / "ffffffffffff.json").write_text(
        json.dumps({"head_commit": "f" * 40, "escaped": [], "stale": [],
                    "results": [{"id": "M49a"}, {"id": "M50a"}, {"id": "M52a"}]}),
        encoding="utf-8")
    _commit(repo, "alien evidence")

    ev, why = _mutation_evidence_for_head(repo)
    assert ev is not None, why
    assert ev.get("head_commit") != "f" * 40, "外来分支的证据被选中了"


def test_lifecycle_order_is_frozen():
    """顺序本身是判据的一部分(P3 靠它判跳级)。"""
    assert LIFECYCLE_ORDER == ("experimental", "candidate", "qualified",
                               "default", "deprecated")


@pytest.mark.parametrize("pid", ["rt-inprocess-v1"])
def test_inprocess_profile_untouched(pid):
    """既有 in-process profile 的 lifecycle 不得被本机制改动。"""
    assert known_profiles()[pid].lifecycle == "default"
