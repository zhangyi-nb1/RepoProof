"""HB-PCDELTA-1 批判据检查器(J1–J7 的机器判;2026-08-16)。

为什么不用 scripts/batch_criteria.py:它的七条判据语义专属 guided-repair
(denied/排序/回滚),对 HB 批只会产出七个"未被检验"→ overall 通过 ——
假绿。本检查器按预注册 §6 的 J 判据与附录一第 8 条实现,原则照旧:

- **判定是纯函数**(`classify_run`),与 IO 分离,tests/test_hb_batch_criteria.py
  直接喂事实字典钉死每个分支;
- **检查器先证明自己查得出缺陷**:`--selftest` 吃同批 F0 冒烟发次
  (fake-scripted),正控必须判 PASS_NO_CLASS、nc_null 必须判
  IMPL_INCOMPLETE、nc_regression_break 必须判 REGRESSION_BROKEN ——
  三者任一不符,检查器自宣无效退出 2(与 C0/C1 金丝雀同一条自证纪律);
- 数字只出脚本:批报引用的每格数字都应来自本脚本的 --json 输出。

J3 归因优先级(高 → 低;每发 FAIL 落且只落一类):
  PROVIDER_FAILURE > HARNESS_FAILURE(h0 红/评分不可得) >
  SUITE_TIMEOUT(h0 红且因超时 —— 附录一第 9 条单列:agent 代码能拖慢
  套件,归 HARNESS 会让蓄意超时洗进连败计数撞停批线 1;不入连败计数,
  一次重跑,复发按模型侧 FAIL 人工裁定) >
  INSTRUMENT_TAMPERED(h1 红,附录一第 8 条;含 LAY_TARGET_OCCUPIED) >
  NO_SUBMISSION >
  REGRESSION_BROKEN(delta 有转绿 ∧ 回归破坏) >
  IMPL_INCOMPLETE(公开面红 / 未触及实现树) >
  DESIGN_MISMATCH(交付完整可跑、回归零破坏、delta 未全绿)。
DESIGN_MISMATCH 的"交付完整"机器代理 = 提交非空 ∧ 触及实现树(src/ 或
包目录);引用它必须并排该题盲攻上界(J 表纪律,报告层执行)。

用法:
  .venv/bin/python scripts/hb_batch_criteria.py <batch> [--json] [--selftest]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RUNS_LEDGER = REPO / "benchmarks/v2/runs.jsonl"
RUNS_DIR = REPO / "runs"

J3_CLASSES = ("PROVIDER_FAILURE", "HARNESS_FAILURE", "SUITE_TIMEOUT",
              "INSTRUMENT_TAMPERED", "NO_SUBMISSION", "REGRESSION_BROKEN",
              "IMPL_INCOMPLETE", "DESIGN_MISMATCH")
IMPL_ROOTS = ("src/", "sqlglot/")           # 实现树:触及它才算"尝试过实现"


def _failing_names(capability: str) -> list[str]:
    """report['capability'] 的 failing 段 → 名单(容忍格式噪声)。"""
    if "failing:" not in (capability or ""):
        return []
    tail = capability.split("failing:", 1)[1]
    return [t.strip().rstrip("],") for t in tail.split(",") if t.strip()]


def _reg_counts(regression: str) -> tuple[int, int]:
    m = re.search(r"passed_checks=(\d+).*?baseline=(\d+)", regression or "")
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def delta_results(cap_failing: list[str], delta_nodes: list[str],
                  cap_total: int) -> tuple[int, int, list[str]]:
    """delta 转绿数(J5)。cap 名单是 pytest 名(无模块前缀),按 :: 尾段匹配。
    cap_total 与 delta+4 守卫不符 = 评分面残缺,调用方按 HARNESS_FAILURE 处理。"""
    red = []
    for node in delta_nodes:
        name = node.split("::", 1)[1]
        if any(name in f or f in name for f in cap_failing):
            red.append(node)
    return len(delta_nodes) - len(red), len(delta_nodes), red


def classify_run(facts: dict) -> dict:
    """一发的 J3 归因。facts 全部来自机器读数,见 _facts_of。"""
    delta_green, delta_total, delta_red = delta_results(
        facts["cap_failing"], facts["delta_nodes"], facts["cap_total"])
    out = {"j3": None, "delta_green": delta_green, "delta_total": delta_total,
           "delta_red": delta_red, "notes": []}
    if facts["verdict"] in ("PASS_ADAPTED",):
        if delta_green != delta_total or facts["cap_failing"]:
            out["j3"] = "HARNESS_FAILURE"       # PASS 却有红 = 判定层自相矛盾
            out["notes"].append("PASS 与 cap 红名单矛盾,判定层缺陷")
        return out
    if facts.get("provider_failure"):
        out["j3"] = "PROVIDER_FAILURE"
        return out
    if facts["cap_total"] != delta_total + 4 or facts.get("scoring_unavailable"):
        out["j3"] = "HARNESS_FAILURE"
        out["notes"].append(f"评分面残缺:cap_total={facts['cap_total']},"
                            f"期望 {delta_total}+4")
        return out
    if any("test_h0_" in f for f in facts["cap_failing"]):
        if facts.get("suite_timeout"):
            out["j3"] = "SUITE_TIMEOUT"         # 超时单列(附录一第 9 条):
            out["notes"].append("一次重跑;复发按模型侧 FAIL 人工裁定")
        else:
            out["j3"] = "HARNESS_FAILURE"       # 判卷器缺料(fail-closed)
        return out
    if any("test_h1_" in f or "test_h3_" in f for f in facts["cap_failing"]):
        out["j3"] = "INSTRUMENT_TAMPERED"       # 量具面被动 / 判后未还原
        return out
    if not facts["submitted"]:
        out["j3"] = "NO_SUBMISSION"
        return out
    regression_broken = (any("test_h2_" in f for f in facts["cap_failing"])
                         or (0 <= facts["reg_passed"] < facts["reg_baseline"]))
    if delta_green > 0 and regression_broken:
        out["j3"] = "REGRESSION_BROKEN"
        return out
    if regression_broken or not facts["impl_touched"]:
        out["j3"] = "IMPL_INCOMPLETE"
        return out
    out["j3"] = "DESIGN_MISMATCH"
    out["notes"].append("引用必须并排该题盲攻上界(J 表纪律)")
    return out


# ------------------------------------------------------------------ IO 侧


def _facts_of(run_id: str, delta_nodes: list[str]) -> dict:
    rd = RUNS_DIR / run_id
    report = json.loads((rd / "report.json").read_text(encoding="utf-8"))
    cap = report.get("capability") or ""
    m = re.search(r"total_checks=(\d+)", cap)
    reg_passed, reg_baseline = _reg_counts(report.get("regression") or "")
    manifest = rd / "adaptation_manifest.json"
    files: list[str] = []
    if manifest.is_file():
        files = [f if isinstance(f, str) else f.get("path", "")
                 for f in json.loads(manifest.read_text()).get("files", [])]
    # submitted = 交了任何东西(含惰性标记 —— NO_SUBMISSION 只留给真空提交,
    # 附录一第 6 条:惰性提交按 IMPL_INCOMPLETE 侧走;selftest 首跑抓的
    # 就是这两个代理混用的错);impl_touched 才剔除惰性标记。
    real_files = [f for f in files if "RP_NULL_SUBMISSION" not in f]
    # SUITE_TIMEOUT 的机器信号:oracle 驱动器 fail-closed 拒判时把
    # "SUITE_TIMEOUT:" 写进 h0 断言消息,原样落在 oracle_stdout.log ——
    # 只在 h0 红时被 classify_run 查询,平时不参与判定。
    olog = rd / "oracle_stdout.log"
    suite_timeout = olog.is_file() and "SUITE_TIMEOUT:" in olog.read_text(
        encoding="utf-8", errors="replace")
    return {
        "verdict": report.get("verdict"),
        "delta_nodes": delta_nodes,
        "cap_failing": _failing_names(cap),
        "cap_total": int(m.group(1)) if m else -1,
        "scoring_unavailable": not m,
        "reg_passed": reg_passed,
        "reg_baseline": reg_baseline,
        "provider_failure": bool(report.get("provider_failure")),
        "submitted": bool(files),
        "impl_touched": any(f.startswith(IMPL_ROOTS) for f in real_files),
        "suite_timeout": suite_timeout,
        "public_by_round": report.get("public_passed_by_round"),
    }


def _delta_nodes_of(task_id: str) -> list[str]:
    pkg = task_id.replace("-", "_")
    mf = REPO / "benchmarks/v2/tasks" / pkg / "oracle/delta_manifest.json"
    return json.loads(mf.read_text(encoding="utf-8"))["delta_nodes"]


def adjudicate(batch: str) -> dict:
    rows = [json.loads(ln) for ln in RUNS_LEDGER.read_text().splitlines() if ln]
    rows = [r for r in rows if r.get("batch") == batch]
    if not rows:
        raise SystemExit(f"台账里没有批 {batch} 的发次")
    out = {"batch": batch, "runs": [], "smoke_controls": [],
           "consecutive_harness_failures_max": 0}
    streak = mx = 0
    for r in rows:
        facts = _facts_of(r["run_id"], _delta_nodes_of(r["task_id"]))
        cls = classify_run(facts)
        entry = {"run_id": r["run_id"], "model": r["model"],
                 "verdict": facts["verdict"], **cls,
                 "public_by_round": facts["public_by_round"]}
        bucket = ("smoke_controls" if str(r["model"]).startswith("fake")
                  else "runs")
        out[bucket].append(entry)
        if bucket == "runs":
            # SUITE_TIMEOUT 已单列成类,天然不入连败计数(附录一第 9 条)。
            streak = streak + 1 if cls["j3"] == "HARNESS_FAILURE" else 0
            mx = max(mx, streak)
    out["consecutive_harness_failures_max"] = mx
    out["stop_line_hit"] = mx >= 2            # 停批线 1(其余停批线人工判)
    return out


# classify_run 的分支活检(附录一第 9 条):活体负控只覆盖得起
# IMPL_INCOMPLETE / REGRESSION_BROKEN / INSTRUMENT_TAMPERED 三类,其余分支
# 用合成事实钉死 —— selftest 每次运行都过一遍,任何一支判错即自宣无效。
_D1 = ["tests.x::test_a"]
_BASE = {"verdict": "FAIL", "delta_nodes": _D1, "cap_failing": ["test_a"],
         "cap_total": 5, "scoring_unavailable": False, "reg_passed": 100,
         "reg_baseline": 100, "provider_failure": False, "submitted": True,
         "impl_touched": True, "suite_timeout": False}
SYNTHETIC_BRANCHES: list[tuple[str | None, dict]] = [
    (None, {**_BASE, "verdict": "PASS_ADAPTED", "cap_failing": []}),
    ("PROVIDER_FAILURE", {**_BASE, "provider_failure": True}),
    ("HARNESS_FAILURE", {**_BASE, "cap_total": 3}),
    ("HARNESS_FAILURE", {**_BASE, "cap_failing": ["test_h0_oracle_operable"]}),
    ("SUITE_TIMEOUT", {**_BASE, "cap_failing": ["test_h0_oracle_operable"],
                       "suite_timeout": True}),
    ("INSTRUMENT_TAMPERED",
     {**_BASE, "cap_failing": ["test_h1_instrument_surface_untouched", "test_a"]}),
    ("NO_SUBMISSION", {**_BASE, "submitted": False}),
    ("REGRESSION_BROKEN", {**_BASE, "cap_failing": ["test_h2_no_regression_broken"],
                           "reg_passed": 99}),
    ("IMPL_INCOMPLETE", {**_BASE, "impl_touched": False}),
    ("DESIGN_MISMATCH", dict(_BASE)),
]


def selftest(result: dict) -> list[str]:
    """检查器的自证:F0 冒烟四形态各归各位 + 合成分支活检,错一条自宣无效。"""
    expect = {"fake-scripted:positive": (None, "PASS_ADAPTED"),
              "fake-scripted:control:nc_null_submission": ("IMPL_INCOMPLETE", "FAIL"),
              "fake-scripted:control:nc_regression_break": ("REGRESSION_BROKEN", "FAIL"),
              "fake-scripted:control:nc_instrument_tamper": ("INSTRUMENT_TAMPERED", "FAIL")}
    bad: list[str] = []
    seen = set()
    for e in result["smoke_controls"]:
        want = expect.get(e["model"])
        if not want:
            continue
        seen.add(e["model"])
        if (e["j3"], e["verdict"]) != want:
            bad.append(f"{e['run_id']}: 判成 ({e['j3']},{e['verdict']}),期望 {want}")
    for m in expect:
        if m not in seen:
            bad.append(f"自证素材缺席:批里没有 {m} 冒烟发次")
    for want_j3, facts in SYNTHETIC_BRANCHES:
        got = classify_run(facts)["j3"]
        if got != want_j3:
            bad.append(f"合成分支判错:期望 {want_j3},判成 {got}(facts={facts})")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    result = adjudicate(a.batch)
    if a.selftest:
        bad = selftest(result)
        if bad:
            print("SELFTEST INVALID:\n" + "\n".join(bad))
            return 2
        print("SELFTEST OK: 三形态冒烟各归各位")
    print(json.dumps(result, ensure_ascii=False, indent=1) if a.json else
          "\n".join(f"{e['run_id']}  {e['verdict']}  j3={e['j3']}  "
                    f"delta={e['delta_green']}/{e['delta_total']}"
                    for e in result["runs"] + result["smoke_controls"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
