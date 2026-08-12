"""批次判据核对器:预注册写下的判据,由脚本判,不由散文判。

背景(PROCESS-INDEPENDENCE-PLAN §5 + LESSONS #30):批报里的"P2 通过
5/5"这类句子此前是我手打 python 片段现算出来的——一次性、不可复跑、
错了没人知道(批 6 就有一次:我的启发式把 `anthropic` 判成"不含具体
真值",实际包体点名了该分发)。现在固化成脚本:输入批次名,输出逐条
判定,三种结局 通过 / 未通过 / **未被检验(vacuous)**。

vacuous 是一等公民:判据的触发条件本批没出现时,既不算通过也不算失败
——"不许拿没发生的事当成功"(批 6 P1 先例)。

用法:
    .venv/bin/python scripts/batch_criteria.py T3v5-RANKING-20260813
    .venv/bin/python scripts/batch_criteria.py <batch> --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LEDGER = REPO / "benchmarks" / "v2" / "runs.jsonl"

PASS, FAIL, VACUOUS = "通过", "未通过", "未被检验"


def load_batch(batch: str) -> list[dict]:
    rows = [json.loads(x) for x in LEDGER.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("batch") == batch]


def round_facts(run_dir: Path) -> list[dict]:
    """逐轮事实 = trace 的 round.end + probe ⋈ record.json。"""
    trace = run_dir / "trace.jsonl"
    if not trace.is_file():
        return []
    ev = [json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines() if x.strip()]
    ends = {e["payload"]["round"]: e["payload"]
            for e in ev if e.get("event") == "repair.round.end"}
    probes = {e["payload"]["round"]: e["payload"]["unresolvable_dists"]
              for e in ev if e.get("event") == "repair.dependency_probe"}
    out = []
    for rnd in sorted(ends):
        rec_path = run_dir / "repair" / f"round-{rnd}" / "record.json"
        if not rec_path.is_file():
            continue
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        traj = run_dir / f"trajectory_round{rnd}.json"
        out.append({
            "round": rnd, "end": ends[rnd], "record": rec,
            "unresolvable": probes.get(rnd, []),
            "prompt": traj.read_text(encoding="utf-8", errors="replace") if traj.is_file() else "",
        })
    return out


def _verdict(hits: list[bool], detail: list[str]) -> tuple[str, list[str]]:
    if not hits:
        return VACUOUS, detail
    return (PASS if all(hits) else FAIL), detail


def adjudicate(batch: str) -> dict:
    runs = load_batch(batch)
    facts = {r["run_order"]: (r, round_facts(REPO / "runs" / r["run_id"])) for r in runs}
    res: dict[str, dict] = {}

    # Q1 denied 轮不计入排序 / P3 denied 不跨轮继承(同一份证据,两个角度)
    q1, q1d, p3, p3d = [], [], [], []
    for o, (_run, rounds) in sorted(facts.items()):
        for f in rounds:
            d, pol = f["end"]["denied_this_round"], f["record"]["policy_violations"]
            p3.append(pol == d or pol == 0)
            p3d.append(f"order-{o} r{f['round']}: 本轮 denied={d} → policy_violations={pol}")
            if d >= 1:
                q1.append(pol == 0)
                q1d.append(f"order-{o} r{f['round']}: denied={d} → policy_violations={pol}"
                           f" {'✓' if pol == 0 else '✗ 仍计入排序'}")
    res["Q1 denied 不计入排序"] = dict(zip(("verdict", "detail"), _verdict(q1, q1d), strict=True))
    res["P3 denied 不跨轮继承"] = dict(zip(("verdict", "detail"), _verdict(p3, p3d), strict=True))

    # Q2 无"仅因 denied 被回滚"的冤案
    q2, q2d = [], []
    for o, (run, rounds) in sorted(facts.items()):
        if not (run.get("rollback_count") or 0):
            continue
        best = max((f["record"]["public_passed"] for f in rounds), default=0)
        for f in rounds:
            rec, end = f["record"], f["end"]
            if end["denied_this_round"] < 1:
                continue
            other = (rec["public_passed"] < best or rec["regression_failed"] > 0
                     or any(p.startswith("public_tests/") for p in rec["changed_files"]))
            q2.append(other or rec["policy_violations"] == 0)
            q2d.append(f"order-{o} r{f['round']}: denied 轮 public={rec['public_passed']}"
                       f"(全场最佳 {best}) 非 denied 的回滚理由={'有' if other else '无'}")
    res["Q2 无仅因 denied 的回滚冤案"] = dict(zip(("verdict", "detail"), _verdict(q2, q2d), strict=True))

    # Q3 denied 且严格最优的轮必须当选 best
    q3, q3d = [], []
    for o, (run, rounds) in sorted(facts.items()):
        if not rounds:
            continue
        top = max(rounds, key=lambda f: f["record"]["public_passed"])
        others = [f["record"]["public_passed"] for f in rounds if f is not top]
        strict = all(top["record"]["public_passed"] > x for x in others) if others else False
        if not (strict and top["end"]["denied_this_round"] >= 1
                and top["record"]["regression_failed"] == 0):
            continue
        rp = json.loads((REPO / "runs" / run["run_id"] / "report.json").read_text(encoding="utf-8"))
        best_round = (rp.get("repair") or rp.get("summary", {}).get("repair", {})).get("best_round")
        q3.append(best_round == top["round"])
        q3d.append(f"order-{o}: denied 且严格最优的是 r{top['round']}"
                   f"(public {top['record']['public_passed']}), best_round={best_round}")
    res["Q3 denied 的最优轮必须当选"] = dict(zip(("verdict", "detail"), _verdict(q3, q3d), strict=True))

    # Q4 反向护栏:改了 public_tests 的轮必须计入排序
    q4, q4d = [], []
    for o, (_run, rounds) in sorted(facts.items()):
        for f in rounds:
            tam = [p for p in f["record"]["changed_files"] if p.startswith("public_tests/")]
            if not tam:
                continue
            q4.append(f["record"]["policy_violations"] >= 1)
            q4d.append(f"order-{o} r{f['round']}: 改了 {len(tam)} 个公开测试 → "
                       f"policy_violations={f['record']['policy_violations']}")
    res["Q4 tampered 仍计入排序"] = dict(zip(("verdict", "detail"), _verdict(q4, q4d), strict=True))

    # P2 违规包携带 trace 真值(分发名 / denied 计数)
    p2, p2d = [], []
    for o, (_run, rounds) in sorted(facts.items()):
        for f in rounds:
            truth = list(f["unresolvable"]) if f["end"]["fatal_violations"] else []
            if f["end"]["denied_this_round"]:
                truth.append(str(f["end"]["denied_this_round"]))
            if not truth:
                continue
            blob = json.dumps(f["record"]["failure_packets"], ensure_ascii=False)
            p2.append(all(t in blob for t in truth))
            p2d.append(f"order-{o} r{f['round']}: 真值 {truth} → 包体含之 "
                       f"{'✓' if all(t in blob for t in truth) else '✗'}")
    res["P2 违规包携带真值"] = dict(zip(("verdict", "detail"), _verdict(p2, p2d), strict=True))

    # P4 回滚必有 ROLLBACK 包(末轮回滚无下一轮可送 → 不可验,不计失败)
    p4, p4d = [], []
    for o, (run, rounds) in sorted(facts.items()):
        rp = json.loads((REPO / "runs" / run["run_id"] / "report.json").read_text(encoding="utf-8"))
        rolled = (rp.get("repair") or rp.get("summary", {}).get("repair", {})).get(
            "rolled_back_rounds") or []
        for rb in rolled:
            nxt = next((f for f in rounds if f["round"] == rb + 1), None)
            if nxt is None:
                p4d.append(f"order-{o}: r{rb} 回滚发生在末轮,无下一轮可送 → 不可验")
                continue
            p4.append("ROLLED BACK" in nxt["prompt"])
            p4d.append(f"order-{o}: r{rb} 回滚 → r{rb + 1} 提示含 ROLLBACK 包 "
                       f"{'✓' if 'ROLLED BACK' in nxt['prompt'] else '✗'}")
    res["P4 回滚必被说明"] = dict(zip(("verdict", "detail"), _verdict(p4, p4d), strict=True))

    return {"batch": batch, "runs": len(runs),
            "run_orders": sorted(facts), "criteria": res,
            "overall": FAIL if any(c["verdict"] == FAIL for c in res.values()) else PASS}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = adjudicate(a.batch)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"批次 {out['batch']} · {out['runs']} 发 · order {out['run_orders']}\n")
        for name, c in out["criteria"].items():
            print(f"  [{c['verdict']}] {name}")
            for d in c["detail"]:
                print(f"        {d}")
        print(f"\n合议:{out['overall']}"
              "(任一条未通过即整体未通过;未被检验不计为通过)")
    sys.exit(1 if out["overall"] == FAIL else 0)
