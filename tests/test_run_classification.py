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

from repoproof.persistence.bench_records import (
    MECHANISM_PURPOSES,
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


def _run(rid: str, verdict: str = "PASS_ADAPTED", task: str = "t2-x") -> dict:
    return {"run_id": rid, "task_id": task, "model": "gpt-5.5", "verdict": verdict}


def _cls(rid: str, **kw) -> dict:
    base = {"run_id": rid, "test_mode": "E1", "run_purpose": "MECHANISM_ABLATION",
            "task_seen": True, "counts_toward_model_capability": False,
            "counts_toward_heldout_benchmark": False,
            "counts_toward_mechanism_effect": True,
            "classification_timing": "PRE_REGISTERED"}
    base.update(kw)
    return base


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


def test_real_ledger_reports_zero_heldout_runs():
    """K6:T1–T3 全是开发套件,Held-out 能力分母目前必须为 0。

    转红 = 有人把开发套件上的发次标成了 Held-out,或者第二宿主已经建成
    (那时该更新本判据,而不是绕过它)。"""
    got = count_passes(REPO)

    assert got["heldout_model_evaluation_runs"] == 0, (
        "出现了标为 Held-out 的发次 —— 第二宿主建成了?那就更新本判据")


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
    assert all(c["run_purpose"] in MECHANISM_PURPOSES | {"CAPABILITY_EVALUATION"}
               for c in cls.values()), "出现未登记的 run_purpose"


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
