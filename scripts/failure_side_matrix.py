#!/usr/bin/env python3
"""失败侧矩阵 —— 判据**红了之后**那一段,控制矩阵一步都没走过。

三个矩阵的分工,现在是四个:

    receipt_controls        回执机制不可伪造
    browser_conformance     这条拓扑在真上游上成立
    t3_sidecar_conformance  这道题可解且可判 —— 跑到"**红在哪**"为止
    **本脚本**              红了**之后**:归因分流 → capability 合并 →
                            completion gate → verdict → 台账 failure_types

为什么必须单独有它(2026-08-15,PQ 首批之后):四发全过,于是判据在失败侧
的行为**零现场实例** —— S1/S2 那套归因分流只有合成证据。而那一段恰恰是最
容易悄悄失效的:分流判反了,系统照跑、控制矩阵照绿,只是每一次"没真用上游"
都被记成 BLOCKED(不算模型失败、可重跑),等于这道题白出。

**判什么**:每个负控走完 `host-run --fake control:<名>` 的完整链路后,

1. verdict 必须是 **FAIL**,**不许是 BLOCKED** —— BLOCKED 那一格的含义是
   "不是被测方的错、可重跑";
2. 台账 `failure_types` 必须落在契约声明的 taxonomy 里(说不清 = 归因失败);
3. 正控必须仍是 PASS_ADAPTED —— 否则判据成墙,前面三条一文不值。

**不重跑发次**:发次由人跑(每个 6–9 分钟),本脚本只从台账与 run 目录取证。
控制组与发次的对应关系**用内容核对**,不靠调用顺序的口头记录 —— 每发的
`adaptation.patch` 里必须逐字含有该控制组的 `page_facts.py`。
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TASK = REPO / "benchmarks" / "v2" / "tasks" / "t3_sidecar_v1"
LEDGER = REPO / "benchmarks" / "v2" / "runs.jsonl"
OUT = REPO / "docs" / "evidence" / "t3_sidecar_failure_side" / "matrix.json"

# 期望:控制组 → (verdict, 归因侧, taxonomy 类型)。
# 类型取自 `HostGuidedRunner._adoption_failure_type` 的映射,与契约的
# `failure_taxonomy_expected` 对齐 —— 对不上就是"用未言明的要求判人"。
EXPECT = {
    "positive":                 ("PASS_ADAPTED", None,    None),
    "nc1_no_sidecar":           ("FAIL", "agent", "UPSTREAM_CAPABILITY_REIMPLEMENTED"),
    "nc2_ignores_result":       ("FAIL", "agent", "UPSTREAM_CALLED_BUT_RESULT_UNUSED"),
    "nc3_one_call_for_all":     ("FAIL", "agent", "UPSTREAM_CAPABILITY_REIMPLEMENTED"),
    "nc4_wrong_symbol":         ("FAIL", "agent", "WRONG_UPSTREAM_SYMBOL"),
    "nc5_launder_forged_input": ("FAIL", "agent", "UPSTREAM_CALLED_BUT_RESULT_UNUSED"),
    "nc6_partial_delivery":     ("FAIL", "agent", "UPSTREAM_CALLED_BUT_RESULT_UNUSED"),
    "nc7_blank_output":         ("FAIL", "agent", "UPSTREAM_CALLED_BUT_RESULT_UNUSED"),
}


def _rows() -> list[dict]:
    return [json.loads(x) for x in LEDGER.read_text(encoding="utf-8").splitlines()
            if x.strip()]


def _match_by_content(rows: list[dict]) -> dict[str, dict]:
    """把发次对回控制组 —— **按内容**,不按我记得的调用顺序。

    口头记的顺序错一位,整张表的结论就全错了,而它看起来完全正常。
    """
    found: dict[str, dict] = {}
    for name in EXPECT:
        src = (TASK / "controls" / name / "page_facts.py").read_text(encoding="utf-8")
        needle = "\n".join(src.splitlines()[:40])      # 头 40 行足以区分且够稳
        for r in reversed(rows):                       # 取最新一发
            if not str(r.get("task_id", "")).startswith("t3-sidecar"):
                continue
            patch = REPO / "runs" / str(r["run_id"]) / "adaptation.patch"
            if not patch.is_file():
                continue
            body = patch.read_text(encoding="utf-8", errors="replace")
            stripped = "\n".join(ln[1:] if ln.startswith("+") else ln
                                 for ln in body.splitlines())
            if needle in stripped:
                found[name] = r
                break
    return found


def find_problems(rows: list[dict], found: dict[str, dict]) -> list[str]:
    """判定单独成函数,好让钉死直接考它(M50a 的教训)。"""
    out: list[str] = []
    taxonomy = set(json.loads(json.dumps(
        _contract()["failure_taxonomy_expected"])))
    for name, (want_verdict, _want_side, want_type) in EXPECT.items():
        r = found.get(name)
        if r is None:
            out.append(f"{name}:台账里找不到对应发次 —— 跑 "
                       f"`host-run --fake control:{name}`")
            continue
        got = r.get("verdict")
        if got != want_verdict:
            out.append(f"{name}:verdict 期望 {want_verdict},实际 {got}"
                       + ("(BLOCKED = '不是被测方的错、可重跑' —— 归因反了)"
                          if got == "BLOCKED" else ""))
        if want_type is None:
            continue
        types = r.get("failure_types") or []
        types = [types] if isinstance(types, str) else list(types)
        if want_type not in types:
            out.append(f"{name}:failure_types 期望含 {want_type},实际 {types}")
        stray = [t for t in types if t not in taxonomy and t != "UNKNOWN"]
        if stray:
            out.append(f"{name}:报了契约没声明的类型 {stray} —— "
                       "用未言明的要求判人")
    # 判别力:所有负控都报同一个类型 = 与"恒报一个值"无从区分
    got_types = {n: (found[n].get("failure_types") or []) for n in found
                 if EXPECT[n][2] is not None}
    distinct = {t for v in got_types.values() for t in
                ([v] if isinstance(v, str) else v)}
    if len(distinct) < 2:
        out.append(f"全部负控报同一个 failure_type({distinct})—— "
                   "与'恒报一个值'无从区分")
    return out


def _contract() -> dict:
    import yaml

    return yaml.safe_load((TASK / "contract.yaml").read_text(encoding="utf-8"))


def main() -> int:
    rows = _rows()
    found = _match_by_content(rows)
    problems = find_problems(rows, found)

    table = []
    for name, (wv, ws, wt) in EXPECT.items():
        r = found.get(name)
        table.append({"control": name, "expect_verdict": wv,
                      "expect_side": ws, "expect_type": wt,
                      "run_id": r.get("run_id") if r else None,
                      "actual_verdict": r.get("verdict") if r else None,
                      "actual_types": (r.get("failure_types") if r else None),
                      "model": r.get("model") if r else None})

    w = max(len(t["control"]) for t in table)
    print(f"{'控制组'.ljust(w)}  期望         实际         failure_types")
    for t in table:
        ok = t["actual_verdict"] == t["expect_verdict"]
        print(f"{'✓' if ok else '✗'} {t['control'].ljust(w)}  "
              f"{t['expect_verdict']:12} {str(t['actual_verdict']):12} "
              f"{t['actual_types']}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"_what": "T3-SIDECAR v1 的**失败侧**矩阵:判据红了之后那一段",
         "_why": "PQ 首批 4/4 全过,失败侧零现场实例;S1/S2 的归因分流"
                 "此前只有合成证据",
         "_not_a_benchmark": "全部是 fake-scripted 冒烟,按 SMOKE_MODEL_PREFIX "
                             "从闸门里扣除,不计任何模型成绩",
         "task_id": "t3-sidecar-page-facts-v1",
         "rows": table, "problems": problems, "ok": not problems},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if problems:
        print("\n不合格:")
        for p in problems:
            print("  -", p)
        print(f"\n证据:{OUT}")
        return 1
    print(f"\n1 正控 + {len(table) - 1} 负控全部走完整条链路,归因各就各位。"
          f"\n证据:{OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
