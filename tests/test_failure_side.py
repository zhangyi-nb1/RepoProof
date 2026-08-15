"""失败侧的钉死 —— 判据**红了之后**那一段。

控制矩阵跑到"红在哪"为止;红之后那一段(归因分流 → capability 合并 →
completion gate → verdict → 台账 failure_types)它一步都没走过。PQ 首批
四发全过,于是那一段至今**零现场实例** —— S1/S2 的归因分流只有合成证据。

这里两层:

- **链路层**(快):直接喂结论字典走 `_receipt_failure_side` → 合成 capability
  → `completion_gate.decide`,考它出 FAIL 还是 BLOCKED。不起会话、不跑浏览器。
- **现场层**(读证据):`scripts/failure_side_matrix.py` 把七个负控真跑完整条
  链路后落的盘。发次由人跑(每个 6–9 分钟),这里只校对结论。

为什么两层都要:只有链路层,等于又一次"合成证据"(那正是要修的病);
只有现场层,证据一旦过期就无人能复现判定逻辑(M50a:两条路互为冗余时,
把其中一条掏掉没人看得见)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
TASK = REPO / "benchmarks" / "v2" / "tasks" / "t3_sidecar_v1"
MATRIX = REPO / "docs" / "evidence" / "t3_sidecar_failure_side" / "matrix.json"


def _decide(rv: dict):
    """把一份回执核验结论走完 host_guided 的分流 + gate,返回 verdict。"""
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.domain.models import AdaptationManifest, VerificationResult
    from repoproof.runner.host_guided import HostGuidedRunner
    from repoproof.verification import completion_gate
    from repoproof.verification.verifiers import REPLAY_MODE_CLEAN

    green = VerificationResult(verifier="x", passed=True, detail="ok")
    # oracle 全绿 + 重放全绿 —— **故意的**:要考的正是"行为对了但没用上游"
    cap = VerificationResult(verifier="CapabilityVerifier", passed=True,
                             detail="passed_checks=4, failed_checks=0")
    rep = VerificationResult(verifier="ReplayVerifier", passed=True, detail="ok",
                             extra={"mode": REPLAY_MODE_CLEAN})
    missing: list[str] = []
    if HostGuidedRunner._receipt_failure_side(None, rv) == "harness":
        missing.append("RECEIPT_VERIFICATION_FAILED:" + str(rv.get("reason")))
        ftype = None
    else:
        ftype = HostGuidedRunner._adoption_failure_type(None, rv)
        cap = VerificationResult(verifier="capability+adoption", passed=False,
                                 detail="采纳不成立", extra={"failure_type": ftype})
    gate = completion_gate.decide(
        capability=cap, regression=green, policy=green, replay=rep,
        adaptation=AdaptationManifest(files=[{"path": "page_facts.py"}],
                                      total_files=1, total_lines=1,
                                      tree_root_sha256="0" * 64),
        missing_external=missing, budget_exhausted=None)
    return gate.verdict.value, ftype


def _red(*checks):
    return {"ok": False, "reason": "RECEIPT_VERIFICATION_FAILED",
            "findings": [{"check": c, "ok": False, "detail": ""} for c in checks]}


# ------------------------------------------------------------------ 链路层
def test_f1_adoption_failure_reaches_fail_not_blocked():
    """F1:**采纳不成立要走到 FAIL。**

    这是整道题存在的理由。走 BLOCKED 的话,"没真用上游"就被塞进"不算模型
    失败、可重跑"那一格 —— 判出来了却不算数,等于白判。

    注意这里 oracle 与重放**都是绿的** —— 那正是这道判据的用武之地:
    oracle 只验行为,它给绿不代表用了上游。
    """
    for checks in (("U4.adoption",), ("U3.coverage", "U4.adoption"),
                   ("U2.symbol", "U3.coverage", "U4.adoption")):
        verdict, ftype = _decide(_red(*checks))
        assert verdict == "FAIL", (
            f"{checks} → {verdict};BLOCKED 的含义是'不是被测方的错、可重跑'")
        assert ftype, f"{checks} 没归到任何 taxonomy 类型 —— 归因说不清"


def test_f2_harness_side_failures_still_reach_blocked():
    """F2(**误杀侧**):harness 自己的毛病仍要走 BLOCKED。

    F1 只证明"该判死的判得死";若把 F1 修成"一律 FAIL",这五种就全被记成
    被测方的失败 —— 我们的浏览器崩了、取件器没写,凭什么算它的?
    """
    for reason in ("NO_DELIVERY_EXTRACTOR", "NO_DELIVERY_EXTRACTED",
                   "RECEIPT_VERIFIER_ERROR", "UPSTREAM_EXECUTION_ERROR",
                   "DELIVERY_SHAPE_INVALID"):
        verdict, ftype = _decide({"ok": False, "reason": reason})
        assert verdict == "BLOCKED", f"{reason} → {verdict},harness 的毛病记到它头上了"
        assert ftype is None
    # 显式归因优先(S1 走这条)
    assert _decide({"ok": False, "reason": "whatever",
                    "attribution": "harness"})[0] == "BLOCKED"


def test_f3_every_failure_type_is_declared_in_the_contract():
    """F3:归因类型必须落在契约声明的 taxonomy 里 —— 否则是用未言明的要求判人。"""
    declared = set(yaml.safe_load(
        (TASK / "contract.yaml").read_text(encoding="utf-8"))["failure_taxonomy_expected"])
    seen = set()
    for checks in (("U2.symbol",), ("U3.coverage",), ("U4.adoption",),
                   ("U3.coverage", "U4.adoption")):
        _, ftype = _decide(_red(*checks))
        seen.add(ftype)
        assert ftype in declared, f"{checks} → {ftype},不在 {sorted(declared)} 里"
    assert len(seen) >= 3, f"不同的红只映射出 {seen} —— 判别力不足,归因说不清"


# ------------------------------------------------------------------ 现场层
def _m() -> dict:
    if not MATRIX.is_file():
        pytest.skip("失败侧证据未落盘 —— 跑七个 `--fake control:<名>` 后执行 "
                    "scripts/failure_side_matrix.py")
    return json.loads(MATRIX.read_text(encoding="utf-8"))


def test_f4_the_recorded_failure_side_matrix_is_clean():
    """F4:七个负控真跑完整条链路后,判定为空问题。"""
    m = _m()
    assert m["ok"], f"失败侧矩阵有问题:{m['problems']}"


def test_f5_no_negative_control_landed_on_blocked():
    """F5:一个负控都不许落在 BLOCKED —— 那一格是给 harness 故障留的。"""
    bad = [r["control"] for r in _m()["rows"]
           if r["expect_verdict"] == "FAIL" and r["actual_verdict"] == "BLOCKED"]
    assert not bad, f"这些负控被记成了'不是被测方的错、可重跑':{bad}"


def test_f6_the_matrix_judge_itself_catches_a_planted_defect():
    """F6:判定函数先证明自己查得出缺陷,才有资格发绿(常设纪律)。

    喂三种合成缺陷:BLOCKED、类型缺失、类型不在契约里。一条查不出就不算数。
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "failure_side_matrix", REPO / "scripts" / "failure_side_matrix.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    def _found(**over):
        base = {n: {"run_id": n, "verdict": v,
                    "failure_types": [t] if t else []}
                for n, (v, _s, t) in mod.EXPECT.items()}
        base.update(over)
        return base

    assert mod.find_problems([], _found()) == [], "干净数据上就报问题 —— 判定太紧"

    planted = {
        "BLOCKED 混过去": {"nc2_ignores_result": {
            "run_id": "x", "verdict": "BLOCKED",
            "failure_types": ["UPSTREAM_CALLED_BUT_RESULT_UNUSED"]}},
        "类型缺失": {"nc4_wrong_symbol": {
            "run_id": "x", "verdict": "FAIL", "failure_types": []}},
        # **只有 taxonomy 那条能查出来的**形态:期望的类型在、另外多报一个
        # 契约没声明的。写成 `["MADE_UP_TYPE"]` 是抓不住这条的 —— "期望类型
        # 不在里面"会先报出来,taxonomy 检查被掏掉也看不出差别(实测:
        # M59c 就这么逃了一次)。
        "契约没声明的类型(混在对的里面)": {"nc4_wrong_symbol": {
            "run_id": "x", "verdict": "FAIL",
            "failure_types": ["WRONG_UPSTREAM_SYMBOL", "MADE_UP_TYPE"]}},
    }
    for label, over in planted.items():
        assert mod.find_problems([], _found(**over)), f"查不出:{label}"

    # 恒报一个值也要查得出 —— 否则"全绿"与"归因失灵"无从区分
    same = {n: {"run_id": n, "verdict": "FAIL",
                "failure_types": ["UPSTREAM_CALLED_BUT_RESULT_UNUSED"]}
            for n in mod.EXPECT if mod.EXPECT[n][2]}
    same["positive"] = {"run_id": "p", "verdict": "PASS_ADAPTED",
                        "failure_types": []}
    assert mod.find_problems([], same), "全部负控报同一个类型,判定没吭声"


def test_f7_control_mode_injects_the_control_it_was_asked_for():
    """F7:`--fake control:X` 必须注入 **X**,不许静默退回正控。

    这是最便宜也最致命的一种失效:退回正控后,七个负控全变成正控,失败侧
    矩阵**八行全绿**,而"全绿"正好长得像"全部通过"。落盘证据看不出来
    (它只记 verdict),所以必须在这里考注入本身。
    """
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from repoproof.runner.host_guided import HostGuidedRunner, _fake_script

    runner = HostGuidedRunner.__new__(HostGuidedRunner)
    runner.task_dir = TASK

    def _body(mode):
        return "\n".join(a["command"] for s in _fake_script(mode, runner)
                         for a in s["actions"])

    nc2 = (TASK / "controls" / "nc2_ignores_result" / "page_facts.py").read_text(
        encoding="utf-8")
    pos = (TASK / "controls" / "positive" / "page_facts.py").read_text(encoding="utf-8")
    marker_nc2 = "# 结果丢掉"
    assert marker_nc2 in nc2 and marker_nc2 not in pos, "标记选错了,这条考不出东西"

    got = _body("control:nc2_ignores_result")
    assert marker_nc2 in got, "要的是 nc2,注进去的不是它 —— 负控静默变正控"
    assert _body("positive") and marker_nc2 not in _body("positive")

    # 不存在的控制组要**显式失败**,不许退回 noop(那会让冒烟"通过"而什么都没验)
    with pytest.raises(ValueError, match="没有这个控制组"):
        _body("control:does_not_exist")
    for bad in ("control:", "control:../positive", "control:.hidden"):
        with pytest.raises(ValueError):
            _body(bad)


def test_f8_the_oracle_alone_would_pass_five_of_the_seven():
    """F8:**把这道题的判别力落在哪里,如实写出来。**

    七个负控里有五个(自抓 / 丢结果 / 一次充数 / 调错符号 / 洗白)在 oracle
    与干净重放上**全绿** —— 因为这道题的 oracle 只验行为(作业跑完、每项有
    非空事实、令牌不漏、开关关了没路由),**它完全不验事实对不对**。

    也就是说:**没有回执层,这五种形态都是 PASS_ADAPTED。** 这既是 A0/A1
    存在的理由,也是一条必须写进任何引用的边界 —— 这道题的判别力几乎全部
    集中在回执层,oracle 只挡得住"根本没做"。

    这条会随证据一起过期:哪天 oracle 变强了(比如自己也能验事实),这个
    数字就该变,而变了就得有人重新说清楚判别力搬到哪去了。
    """
    # 读**证据里抄下来的** oracle 结论,不去翻 `runs/` —— 那个目录不进仓,
    # 而钉死会跑在临时 worktree 里(变异闸门就是这么跑的,实测炸过一次)。
    m = _m()
    weak = [r["control"] for r in m["rows"]
            if r["expect_verdict"] == "FAIL" and r.get("oracle_green")]
    assert len(weak) == 5, (
        f"oracle 独自放行的负控从 5 个变成了 {len(weak)} 个({weak})——"
        "判别力的分布变了,得重新说清楚它搬到哪去了")
    assert "nc1_no_sidecar" in weak, (
        "连'完全自抓'都不在 oracle 放行之列了?那 oracle 变强了,这条要重写")
    # 同时钉住"回执层确实在这五个上红了" —— 只证明 oracle 放行还不够,
    # 那只说明 oracle 弱,不说明有别的东西接住了。
    by = {r["control"]: r for r in m["rows"]}
    for c in weak:
        assert by[c]["receipt_red"], f"{c}:oracle 放行、回执也没红 —— 没人接得住"
