"""发次用途分类与能力分母拆分的钉死(2026-08-14 用户指令)。

**问题**:批 14 的 12 发机制消融跑在 T2v5 上,verdict 有 PASS 有 FAIL,
直接把 T2 的 `passes` 从 5 抬到 14。那个数字读起来像"模型在 T2 上的能力
通过数",而它们回答的是"S2' 在**已见任务**上的局部机制效应"。混在一起
就是误导。

**冻结判据**(先写判据与反例;措辞此后不改):

- K1 **原始 verdict 不可改**:分类是**旁挂**的第二事实,`runs.jsonl` 与
  每发自己的 PASS/FAIL、capability、regression、policy、replay 全部原样
  保留。反例:因为"不适合做能力分析"就删改 verdict —— 那是篡改证据,
  而这些发次确实跑完了、确实是那个结果。
- K2 **能力分母必须拆开**:闸门不得只有一个 `passes` 数字。至少分出
  开发基线 / 机制消融 / Held-out 能力 / 已裁定无效 / 探索性加发 / 冒烟
  六类。反例:批 14 把 T2 passes 抬到 14,读者会以为模型能力提升了 180%。
- K3 **机制消融不计阶段闸门**:`run_purpose = MECHANISM_ABLATION` 的发次
  不进 `passes`。它们回答机制问题,不回答"这个任务可判可过"。
- K4 **处理未送达即不计处理效应**:`treatment_assigned=true` 但
  `treatment_activated=false` 的发次,`counts_toward_treatment_effect`
  必须为 false,并记 `exclusion_reason=TREATMENT_NOT_DELIVERED`。
  反例:批 14 的 gpt-5.6 三发投影 0 次生效,却被我当成"处理臂无差别"的
  证据 —— 那不是无害的证据,是**没做实验**。
- K5 **事后分类必须自曝**:若分类发生在看到结果之后,必须标
  `classification_timing = POST_HOC_TAXONOMY_CORRECTION`。反例:批 13
  名义 HB、实际 AR,这个更正是我看到 order-69 是假 PASS 之后做的 ——
  不标就等于把事后分类伪装成事前预注册。
- K6 **Held-out 分母诚实**:T1–T3 全是开发套件(已用于 oracle 开发),
  故 `heldout_model_evaluation_runs` 目前必须为 **0**。反例:把开发套件
  上的 PASS 当成能力证据 —— 那正是过拟合的定义。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.persistence.bench_records import (
    NON_GATEABLE_PURPOSES,
    classify_runs,
    count_passes,
    load_classifications,
)

REPO = Path(__file__).resolve().parents[1]


def _write(tmp: Path, runs: list[dict], cls: list[dict] | None = None) -> Path:
    b = tmp / "benchmarks" / "v2"
    b.mkdir(parents=True)
    (b / "runs.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in runs), encoding="utf-8")
    (b / "adjudications.jsonl").write_text("", encoding="utf-8")
    if cls:
        (b / "run_classifications.jsonl").write_text(
            "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cls), encoding="utf-8")
    return tmp


def _run(rid: str, verdict: str = "PASS_ADAPTED", task: str = "t2-x", **kw) -> dict:
    return {"run_id": rid, "task_id": task, "model": "gpt-5.5",
            "verdict": verdict, **kw}


def _cls(rid: str, **kw) -> dict:
    base = {"run_id": rid, "test_mode": "E1", "run_purpose": "MECHANISM_ABLATION",
            "task_seen": True, "counts_toward_model_capability": False,
            "counts_toward_heldout_benchmark": False,
            "counts_toward_mechanism_effect": True,
            "classification_timing": "PRE_REGISTERED"}
    base.update(kw)
    return base


_PQ = {"test_mode": "PQ", "run_purpose": "RUNTIME_PROFILE_QUALIFICATION",
       "task_seen": False, "counts_toward_mechanism_effect": False,
       "counts_toward_profile_qualification": True}


def test_original_verdicts_are_never_rewritten(tmp_path):
    """K1:分类是旁挂第二事实,原始 verdict 原样保留。"""
    root = _write(tmp_path, [_run("a"), _run("b", "FAIL")],
                  [_cls("a"), _cls("b")])

    rows = classify_runs(root)

    assert [r["verdict"] for r in rows] == ["PASS_ADAPTED", "FAIL"], "原始 verdict 被改写了"
    assert all(r["run_purpose"] == "MECHANISM_ABLATION" for r in rows)


def test_mechanism_ablation_does_not_count_toward_the_stage_gate(tmp_path):
    """K3:机制消融发次不进 passes —— 它回答机制问题,不回答任务可判可过。"""
    root = _write(tmp_path,
                  [_run("cap"), _run("abl1"), _run("abl2")],
                  [_cls("abl1"), _cls("abl2")])          # cap 未分类 = 常规发次

    got = count_passes(root)

    assert got["passes"] == 1, f"机制消融被计进闸门了,passes={got['passes']}"
    assert got["mechanism_ablation_runs"] == 2
    assert got["development_baseline_runs"] == 1


def test_k7_profile_qualification_does_not_count_toward_the_stage_gate(tmp_path):
    """K7(2026-08-15 首批 PQ 发次当场撞出来的):**PQ 不充闸门。**

    `_denominators` 里白纸黑字写着"PQ:runtime profile 资格审 —— 不充闸门、
    不计模型能力",而扣除逻辑只认 `MECHANISM_PURPOSES`,于是四发 PQ 把 T3 的
    passes 从 3 抬到 7。**散文说不算,代码算了。** 更难看的是这个方向:
    profile 资格审自己抬高了阶段闸门,而资格审存在的理由恰恰是"这个 profile
    还没资格被当数"。

    同时钉住**不许改记成机制消融** —— `mechanism_ablation_runs` 有自己的含义
    (E1/AR),把 PQ 塞进那格是拿一个错标掩盖另一个。
    """
    root = _write(tmp_path,
                  [_run("cap"), _run("pq1"), _run("pq2")],
                  [_cls("pq1", **_PQ), _cls("pq2", **_PQ)])

    got = count_passes(root)

    assert got["passes"] == 1, (
        f"PQ 发次被计进阶段闸门了,passes={got['passes']} —— "
        "profile 资格审自己把闸门抬高了")
    assert got["profile_qualification_runs"] == 2
    assert got["mechanism_ablation_runs"] == 0, "PQ 被错记成机制消融"
    assert got["development_baseline_runs"] == 1
    # 如实计数不挑选:总数仍是 3,扣除只作用在 passes 上
    assert got["total"] == 3 and got["all_valid_run_outcomes"] == 3


_WV = {"test_mode": "AR", "run_purpose": "OBSERVATION_POLICY_QUALIFICATION",
       "task_seen": True, "counts_toward_mechanism_effect": False}


def test_k7c_observation_policy_qualification_does_not_count_toward_the_stage_gate(tmp_path):
    """K7c(R4,2026-08-21):观测策略资格审(window-v1.1 投影在线资格,
    WV11-GPT-QUAL-1)不充闸门。K7 的病提前防:登记进 QUALIFICATION_PURPOSES
    必须是**代码**,预注册散文说"不计"不算数 —— 散文说不算,代码算了
    (2026-08-15 四发 PQ 抬高 T3 的原病)。同时钉住不许错记成机制消融或
    profile 资格审 —— 那两格各有自己的含义。"""
    root = _write(tmp_path,
                  [_run("cap"), _run("wv1"), _run("wv2")],
                  [_cls("wv1", **_WV), _cls("wv2", **_WV)])

    got = count_passes(root)

    assert got["passes"] == 1, (
        f"观测策略资格发被计进阶段闸门了,passes={got['passes']} —— "
        "资格审自己把闸门抬高了")
    assert got["observation_policy_qualification_runs"] == 2
    assert got["mechanism_ablation_runs"] == 0, "WV 被错记成机制消融"
    assert got["profile_qualification_runs"] == 0, "WV 被错记成 profile 资格审"
    # 如实计数不挑选:总数仍是 3,扣除只作用在 passes 上
    assert got["total"] == 3 and got["all_valid_run_outcomes"] == 3


def test_k7b_the_real_ledger_keeps_pq_out_of_t3(tmp_path):
    """K7 在**真台账**上的现场:2026-08-15 那四发 PQ 一个都不许进 T3 passes。

    上一条用合成数据证明扣除逻辑对;这条证明它**真的作用到了那四发**上 ——
    分类漏登记的话,逻辑再对也没用(实测就是漏了,所以先红后绿)。
    """
    got = count_passes(REPO, task_prefix="t3-")
    pq = {"t3-sidecar-page-facts-v1-20260815-135626",
          "t3-sidecar-page-facts-v1-20260815-140454",
          "t3-sidecar-page-facts-v1-20260815-141403",
          "t3-sidecar-page-facts-v1-20260815-142222"}
    assert not (pq & set(got["pass_run_ids"])), (
        f"PQ 发次进了 T3 的闸门通过名单:{sorted(pq & set(got['pass_run_ids']))}")
    assert got["profile_qualification_runs"] >= 4


def test_breakdown_has_all_required_buckets(tmp_path):
    """K2:闸门不得只有一个 passes 数字。"""
    root = _write(tmp_path, [_run("a")], [_cls("a")])

    got = count_passes(root)

    for k in ("all_valid_run_outcomes", "development_baseline_runs",
              "mechanism_ablation_runs", "heldout_model_evaluation_runs",
              "invalidated", "exploratory", "smoke"):
        assert k in got, f"能力分母缺一类:{k}"


def test_undelivered_treatment_is_excluded_from_treatment_effect(tmp_path):
    """K4:处理臂零生效的格子不计处理效应 —— 那不是无害,是没做实验。"""
    root = _write(tmp_path, [_run("on"), _run("off")],
                  [_cls("on", treatment_assigned=True, treatment_activated=True,
                        counts_toward_treatment_effect=True),
                   _cls("off", treatment_assigned=True, treatment_activated=False,
                        counts_toward_treatment_effect=False,
                        exclusion_reason="TREATMENT_NOT_DELIVERED")])

    got = count_passes(root)
    rows = {r["run_id"]: r for r in classify_runs(root)}

    assert got["treatment_delivered_runs"] == 1
    assert got["treatment_not_delivered_runs"] == 1
    assert rows["off"]["exclusion_reason"] == "TREATMENT_NOT_DELIVERED"


def test_post_hoc_classification_must_declare_itself(tmp_path):
    """K5:事后分类必须自曝,否则等于把它伪装成事前预注册。"""
    root = _write(tmp_path, [_run("a")],
                  [_cls("a", test_mode="AR", run_purpose="CRITERIA_INTEGRITY",
                        classification_timing="POST_HOC_TAXONOMY_CORRECTION")])

    got = count_passes(root)

    assert got["post_hoc_classified_runs"] == 1, "事后分类没有被单独计数"


def test_unclassified_runs_default_to_capability_denominator(tmp_path):
    """未分类的历史发次按常规处理 —— 分类是只增的,不改既有语义。"""
    root = _write(tmp_path, [_run("old1"), _run("old2", "FAIL")])

    got = count_passes(root)

    assert got["passes"] == 1 and got["development_baseline_runs"] == 2


def test_real_ledger_reports_exactly_the_preregistered_heldout_runs():
    """K6(2026-08-17 更新,按本钉旧文自己的指示):Held-out 分母 = 8。

    钉史:恒 0 →(HB-PCDELTA-1,6 发)6 →(HB-DSENTRY-1,2 发)8。每次
    转红都按规矩当批显式重审两道硬门再更新:DSENTRY 两发 oracle=
    UPSTREAM_OWN_TEST_SUITE(任务包自 ba77070 零改动,批后 git 核对)、
    host=PRISTINE(批前批后 verify-only 逐字节对得上,354 条);旁挂 2 行
    为冻结预注册(b50d6c0)的机械转录。分子不变:DSENTRY 两发均 FAIL
    (j3=NO_SUBMISSION,delta 0/5,盲攻上界 4/5 随档)。

    钉成**恰好等于**而非 ≥:下一批 HB 落账时本钉必须转红,逼着当批像
    这次一样显式过一遍两道硬门,而不是让分母静默上爬。"""
    got = count_passes(REPO)

    assert got["heldout_model_evaluation_runs"] == 8, (
        "Held-out 分母 ≠ 8 —— 新 HB 批落账了?按本钉的规矩显式重审再更新;"
        "或有人把不该计的发次标成了 Held-out")
    assert got["heldout_passes"] == 2, (
        "Held-out 分子 ≠ 2(HB-PCDELTA-1:8042 双模型 PASS_ADAPTED;"
        "HB-DSENTRY-1 零 PASS)")


def test_classification_sidecar_loads_from_the_real_repo():
    """接线检查:真仓的分类旁挂可读,且 run_id 都能对上台账。"""
    cls = load_classifications(REPO)
    if not cls:
        return                                     # 尚未分类时不做断言

    known = {json.loads(line)["run_id"]
             for line in (REPO / "benchmarks" / "v2" / "runs.jsonl")
             .read_text(encoding="utf-8").splitlines() if line.strip()}
    orphans = [rid for rid in cls if rid not in known]

    assert not orphans, f"分类记录指向不存在的发次:{orphans}"
    allowed = NON_GATEABLE_PURPOSES | {"CAPABILITY_EVALUATION"}
    bad = sorted({c["run_purpose"] for c in cls.values()} - allowed)
    assert not bad, f"出现未登记的 run_purpose:{bad}(登记在 bench_records.py)"


def test_no_unknown_keys_in_the_classification_sidecar():
    """K7:分类旁挂只许出现登记过的键。

    为什么查键不查值:`evidence_strength` 的缺省是 "STANDARD",于是把字段名
    打成 `evidence_strenght` 会让降级**静默失效** —— 失效方向朝松。值打错
    反而安全(任何非 STANDARD 的值都算降级)。所以危险的是键。"""
    from repoproof.persistence.bench_records import unknown_classification_keys

    bad = unknown_classification_keys(REPO)
    assert not bad, f"分类旁挂出现未登记的键(可能是拼错,会静默失效):{bad}"


def test_evidence_downgrade_does_not_touch_verdict_or_gate():
    """K8:证据降级与改判是**两件事**,必须正交。

    用户 2026-08-14 指令:那三发旧 T3v5 PASS "不要追溯改判,但也不要继续当
    强证据"。反例两侧都要挡:
      - 降级顺手把 verdict / effective_verdict 改了 → 编造当时不存在的事实;
      - 降级不进入任何机器可读输出 → 一份已知有疑的证据继续以全强度流通。
    """
    from repoproof.persistence.bench_records import classify_runs, count_passes

    rows = {r["run_id"]: r for r in classify_runs(REPO)}
    downgraded = [r for r in rows.values() if r["evidence_strength"] != "STANDARD"]
    if not downgraded:
        return

    for r in downgraded:
        assert r["verdict"] == r["verdict"], "占位:verdict 字段必须仍在"
        assert r["evidence_caveat"], f"{r['run_id']} 降级了却没写理由"
        # 降级**不**得改动有效判决 —— 那是裁定的职权,走 adjudications.jsonl
        assert r["effective_verdict"] in {"PASS_ADAPTED", "PASS", "FAIL",
                                          "INVALIDATED_FALSE_PASS", r["verdict"]}

    counts = count_passes(REPO)
    assert counts["provisional_evidence_runs"] == len(downgraded)
    ids = {x["run_id"] for x in counts["provisional_evidence"]}
    assert ids == {r["run_id"] for r in downgraded}, "降级发次没有全部出现在闸门输出里"


# ============================================ C 轨(第二宿主)开工前的记账加固
# 三条都不是"将来的风险",是**现在就在错的账**,只因为第二宿主还没建、
# held-out 还是 0,所以没人看得出来。第一批 held-out 数字一落地,污染会和
# 真数一起进来,而"它一直是 0"看起来正好像它没问题。

def test_k8_heldout_gets_the_same_four_deductions_as_passes(tmp_path):
    """K8:held-out 分母**必须**和 passes 走同样四道扣除。

    修之前是 `for r in rows` —— 一道都没有。冒烟、探索性加发、已裁定无效、
    机制消融,只要有人把 `counts_toward_heldout_benchmark` 置 true 就全进去,
    而这个数字是四类分母里**唯一会被直接读成"模型能力"**的那个。
    """
    HELDOUT = {"counts_toward_heldout_benchmark": True,
               "oracle_authorship": "UPSTREAM_OWN_TEST_SUITE",   # 严口径要这个
               "run_purpose": "CAPABILITY_EVALUATION", "test_mode": "HB"}
    rows = [_run("real"),
            _run("smk", **{"model": "fake-scripted"}),
            _run("exp", **{"batch": "EXPLORATORY_UNPREREGISTERED"}),
            _run("mech")]
    cls = [_cls(r["run_id"], **HELDOUT) for r in rows]
    cls[-1] = _cls("mech", **{**HELDOUT, "run_purpose": "MECHANISM_ABLATION"})
    got = count_passes(_write(tmp_path, rows, cls))

    assert got["heldout_model_evaluation_runs"] == 1, (
        f"held-out 分母是 {got['heldout_model_evaluation_runs']},该是 1 —— "
        "冒烟/探索/机制混进了唯一会被读成能力的那个数")
    assert got["heldout_passes"] == 1, "只有分母没有分子,引用时必然有人自己配一个"


def test_k9_a_second_host_run_does_not_land_in_the_first_hosts_stage(tmp_path):
    """K9:第二宿主的发次**不许**因为 task_id 前缀就进第一宿主的阶段闸门。

    阶段归属一直靠 `task_id.startswith("t3-")`。这不是理论风险 ——
    `t3-sidecar-page-facts-v1`(另一份 oracle、另一套判据)现在就被算在
    stages.T3 的 total 里,只靠 run_purpose 挡在 passes 之外,而那道挡板是
    2026-08-15 才补的(M58b)。第二宿主一来,同样的洞会以"能力数字"的形式
    再犯一次,后果重得多。
    """
    root = _write(tmp_path,
                  [_run("own", task="t3-offerclaw-x"),
                   _run("new", task="t3-newhost-x", **{"host_id": "someone/newhost"})])
    t3 = count_passes(root, task_prefix="t3-")

    assert t3["passes"] == 1, f"第二宿主的发次进了 T3 闸门:{t3['pass_run_ids']}"
    assert "new" not in (t3["pass_run_ids"] or [])
    assert t3["total"] == 1, "它连 total 都不该进 —— 那不是这个阶段的任务"
    # 历史行没有 host_id,必须仍按第一宿主处理(只增不改)
    assert count_passes(_write(tmp_path / "b", [_run("old", task="t3-x")]),
                        task_prefix="t3-")["passes"] == 1


def test_k10_writing_a_run_without_a_host_id_is_refused(tmp_path):
    """K10:落账时说不清宿主就**拒收**。

    光把 host_id 加进 REQUIRED_FIELDS 是没用的:`normalise_record` 对缺失
    字段一律填 UNKNOWN 而不报错,而 UNKNOWN 会被当第一宿主放行 —— 于是
    新宿主漏填 = 静默进旧闸门。这正是 M58b 的形状,必须在写入口拦。
    """
    from repoproof.persistence.bench_records import BenchRecordError, append_run

    with pytest.raises(BenchRecordError, match="host_id"):
        append_run(tmp_path, {"run_id": "x", "task_id": "t3-y", "verdict": "PASS"})
    append_run(tmp_path, {"run_id": "x", "task_id": "t3-y", "verdict": "PASS",
                          "host_id": "a/b"})     # 说得出来就收


def test_k11_the_heldout_prose_is_derived_from_data_not_written_down():
    """K11:"第二宿主未建,恒为 0" 这句话必须由**数据**推出来。

    写死的话,第二宿主建成后它照样原样写进 v2_gate.json,而没有任何检查
    会发现它成了假话 —— LESSONS #45 二("散文说不算,代码算了")的同型。
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "gate_report", REPO / "scripts" / "gate_report.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    d = mod.compute(REPO)
    # 2026-08-16 HB-PCDELTA-1 F0 电池入账,delta 宿主进台账 —— 旧钉值
    # ["zhangyi-nb1/offerclaw"] 的世界状态合法翻页,K11 那句"第二宿主未建"
    # 按设计当场自毁(这正是本测试合成段考的行为,真台账先兑现了)。
    # 2026-08-23 再翻一页:LOCAL-TOOL 产品线首任务入账(RFC-010 [G3],
    # host_id=local-tool/pdf-table;PRODUCT_ONBOARDING 不充闸不计能力)。
    assert d["hosts_covered"] == ["local-tool/pdf-table", "pallets/click",
                                  "tobymao/sqlglot",
                                  "zhangyi-nb1/offerclaw"], d["hosts_covered"]
    note = d["_denominators"]["heldout_model_evaluation_runs"]
    assert "第二宿主未建" not in note, "宿主已入账,这句必须消失"
    assert "pallets/click" in note

    # 合成一个"已经建了第二宿主"的台账,那句话必须自己消失
    import json
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    (tmp / "benchmarks" / "v2").mkdir(parents=True)
    (tmp / "benchmarks" / "v2" / "runs.jsonl").write_text(
        json.dumps({"run_id": "a", "task_id": "t3-x", "model": "gpt-5.5",
                    "verdict": "PASS", "host_id": "someone/newhost"}) + "\n",
        encoding="utf-8")
    note2 = mod.compute(tmp)["_denominators"]["heldout_model_evaluation_runs"]
    assert "第二宿主未建" not in note2, (
        f"第二宿主已在台账里,这句话还在说未建:{note2}")
    assert "someone/newhost" in note2


def test_k12_our_own_oracle_can_never_be_counted_as_heldout(tmp_path):
    """K12(用户 2026-08-15 裁决,**严口径**):我们写的 oracle 一律不算 held-out。

    裁决之前盘上两套措辞并存且自相矛盾:TESTPLAN §11.4 要求"未参与 harness
    开发",§7 又要求第二宿主"照旧走全流程"而 §7 的 oracle 仍由我们写。不裁的话,
    第一发落账时这一格填什么就是临场判断 —— 数字先出来、口径后跟上。

    实现要点:**分类文件说 true 也不算**。它是旁挂的自述,手一滑就能置 true,
    而 held-out 是四类分母里唯一被直接读成"模型能力"的那个。自述不能自证。
    """
    from repoproof.persistence.bench_records import (
        ORACLE_AUTHORSHIP_EXTERNAL,
        ORACLE_AUTHORSHIP_OURS,
    )

    base = {"counts_toward_heldout_benchmark": True,
            "run_purpose": "CAPABILITY_EVALUATION", "test_mode": "HB"}

    def _n(**over):
        root = _write(tmp_path / f"c{len(over)}{over.get('oracle_authorship', '')}",
                      [_run("a", **{"host_id": "someone/newhost"})],
                      [_cls("a", **{**base, **over})])
        return count_passes(root)["heldout_model_evaluation_runs"]

    assert _n(oracle_authorship=ORACLE_AUTHORSHIP_EXTERNAL) == 1, "外部 oracle 该算"
    assert _n(oracle_authorship=ORACLE_AUTHORSHIP_OURS) == 0, (
        "我们写的 oracle 被算成 held-out —— 严口径失效")
    assert _n() == 0, "没声明 oracle 来源就算 held-out —— 默认必须是不算"
    assert _n(oracle_authorship="SOMETHING_ELSE") == 0, "无法识别的来源必须按不算处理"

    # 真台账口径(2026-08-17 更新,与 K6 同步):T1–T3(我们写的 oracle)
    # 仍一发不计;计入的只能是 HB-PCDELTA-1 的 6 发 + HB-DSENTRY-1 的
    # 2 发,且**逐发**真过两道硬门 —— 不只钉数字,钉性质:任何一发
    # heldout 行若不是外部 oracle + 未加语义宿主,这里必须红。
    from repoproof.persistence.bench_records import classify_runs

    real = [r for r in classify_runs(REPO) if r["counts_toward_heldout_benchmark"]]
    assert len(real) == 8, f"真台账 heldout 发次 {len(real)} ≠ 8(PCDELTA 6 + DSENTRY 2)"
    for r in real:
        assert r["oracle_authorship"] == ORACLE_AUTHORSHIP_EXTERNAL, r["run_id"]
        assert str(r["run_id"]).startswith("hb1-"), (
            f"非 HB 批发次混进 heldout:{r['run_id']}")


def test_k20_harness_enriched_hosts_can_never_be_heldout(tmp_path):
    """K20:harness **往宿主里加语义**的题,一律不算 held-out。

    这是严口径闸门的**第二道**,2026-08-15 第二宿主设计评审当场查出的盲区:
    只看 `oracle_authorship` 管的是**测试文本**谁写的,对"harness 改写了
    **非测试**源码"完全无感。于是有一条又宽又隐蔽的路 ——

        把宿主源码改得面目全非、塞进我们自己发明的接线语义,
        上游那 554 条此刻实际在检验"你有没有猜对**我们新加的**东西",
        而闸门照样认它是 held-out。

    不是假想:本次三份设计里有一份的最大 trap(71 条上游测试)判的就是
    harness 自造的 `register_doc_preparer` + 现摇 priority。做它等于亲手把
    第一发 held-out 数字喂进盲区。

    可判的分界线:**只许挖空,不许加语义。**
    """
    from repoproof.persistence.bench_records import (
        HOST_MOD_ENRICHED,
        HOST_MOD_HOLLOW_ONLY,
        HOST_MOD_PRISTINE,
        ORACLE_AUTHORSHIP_EXTERNAL,
    )

    base = {"counts_toward_heldout_benchmark": True,
            "oracle_authorship": ORACLE_AUTHORSHIP_EXTERNAL,
            "run_purpose": "CAPABILITY_EVALUATION", "test_mode": "HB"}

    def _n(mode):
        cls = dict(base)
        if mode is not None:
            cls["host_modification_mode"] = mode
        root = _write(tmp_path / f"m{mode}",
                      [_run("a", **{"host_id": "someone/newhost"})], [_cls("a", **cls)])
        return count_passes(root)["heldout_model_evaluation_runs"]

    assert _n(HOST_MOD_PRISTINE) == 1, "宿主没改,该算"
    assert _n(HOST_MOD_HOLLOW_ONLY) == 1, (
        "只挖空也不算的话就没题可出了 —— 上游测试考的仍是上游自己的语义")
    assert _n(None) == 1, "缺省该按 PRISTINE 处理(历史行没有这个字段)"
    assert _n(HOST_MOD_ENRICHED) == 0, (
        "harness 往宿主里加了语义还算 held-out —— 上游测试此刻在考我们发明的东西")
    assert _n("SOMETHING_ELSE") == 0, "无法识别的改动模式必须按不算处理"
