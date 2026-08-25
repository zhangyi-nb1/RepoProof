"""Build docs/product_summary.json — 产品线(Local Tool)的机器可读事实源。

为什么要有第二份事实源(外部审查 2026-08-26):
`docs/benchmark_summary.json` 是 MVP 时代(2026-08-07)冻结的 12 发快照,
它自身自洽,但**覆盖不到产品线**——两批真实仓、313 行台账、运营发布状态
一条都不在里面。于是 `check_public_claims.py` 虽然全绿,校验的却是一套
早已不再对外讲的话:**claims 纪律机器空转**。本脚本补上产品口径,
`check_public_claims.py` 同步把它纳入校验。

Extraction-only,与 build_benchmark_summary.py 同律:
- 每个字段都来自已提交的台账/指标文件,不手打数字;
- 证据证不出来的写 null,不猜、不从记忆回填;
- 发次口径一律走 `bench_records.classify_runs()` 的既有投影,不自创规则
  (PRODUCT 身份出自原始 append-only 行,分类旁挂不能把它塞进 Lab 分母)。

Run: .venv/bin/python scripts/build_product_summary.py
"""

from __future__ import annotations

import collections
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from repoproof.persistence.bench_records import classify_runs  # noqa: E402

OUT = REPO / "docs" / "product_summary.json"
RUNS = REPO / "benchmarks" / "v2" / "runs.jsonl"
CLASSIFICATIONS = REPO / "benchmarks" / "v2" / "run_classifications.jsonl"
M4_METRICS = REPO / "docs" / "m4_metrics.json"

# 真模型 vs 彩排:彩排发用 fake provider,model 串带 fake 前缀。
# 这是台账上的既有约定(tool_metrics.py 的 tool_ready 判据同款)。
FAKE = "fake"


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_real_model(row: dict) -> bool:
    return FAKE not in str(row.get("model", "")).lower()


def build() -> dict:
    rows = classify_runs(REPO)
    product = [r for r in rows if r.get("test_mode") == "PRODUCT"]
    real = [r for r in product if _is_real_model(r)]
    rehearsal = [r for r in product if not _is_real_model(r)]

    # 真实上游仓库数:产品真发涉及的不同 task_id 前缀(tool-<name>-vN)。
    tasks = sorted({str(r.get("task_id") or "") for r in real if r.get("task_id")})

    # 主仓完整性:P0-2(2026-08-25)之前完整性在 completion gate **之后**才算、
    # 只落 report 不进判定,于是台账里存在"verdict=PASS 而 integrity=MISMATCH"
    # 的存量行。台账该字段是字符串("ok" / "MISMATCH"),不是字典 —— 按字典读
    # 会静默得到空集(本脚本首版的真实 bug,外部审查 2026-08-26 当场咬出)。
    #
    # 如实统计,不追改历史:这些发次按修复后的闸应判 BLOCKED,勘误行记在
    # run_classifications.jsonl,原始 verdict 一字不动(判据 K1)。
    def _mismatch(rows_: list[dict]) -> list[str]:
        return sorted(str(r.get("run_id")) for r in rows_
                      if r.get("main_dir_integrity") == "MISMATCH")

    product_mismatch = _mismatch(product)
    mismatch_pass_rows = [r for r in product
                          if r.get("main_dir_integrity") == "MISMATCH"
                          and str(r.get("verdict", "")).startswith("PASS")]
    product_mismatch_but_pass = _mismatch(
        [r for r in product if str(r.get("verdict", "")).startswith("PASS")])

    # 干净复样(INTEGRITY-RESAMPLE-1,2026-08-26):同一冻结 task_id 的真模型
    # 发次拿到 integrity=ok + PASS。**按 task_id 结构性推导,不硬编码映射**
    # —— 硬编码的映射表下次加发就过期,而过期的事实源比没有更坏。
    #
    # 复样能证明的:这道冻结题 + 钉版上游在完整性闸下确实能干净通过。
    # 复样**不能**证明:当初那一发是干净的。原发的 MISMATCH 与限定句义务
    # 原样保留(见各发 append-only 勘误行)。
    resample: dict[str, str] = {}
    for r in real:
        if (r.get("batch") == "INTEGRITY-RESAMPLE-1"
                and r.get("main_dir_integrity") == "ok"
                and str(r.get("verdict", "")).startswith("PASS")):
            resample.setdefault(str(r.get("task_id")), str(r.get("run_id")))
    covered = sorted({str(r.get("run_id")) for r in mismatch_pass_rows
                      if str(r.get("task_id")) in resample})
    uncovered = sorted({str(r.get("run_id")) for r in mismatch_pass_rows
                        if str(r.get("task_id")) not in resample})

    m4 = json.loads(M4_METRICS.read_text(encoding="utf-8")) if M4_METRICS.exists() else {}

    return {
        "note": (
            "Machine-readable fact source for RepoProof PRODUCT-mode claims. "
            "Extraction-only from committed ledgers; null = evidence does not "
            "prove it. Benchmark Lab numbers live in benchmark_summary.json and "
            "are never merged with these. Rebuild: "
            "scripts/build_product_summary.py; enforced by check_public_claims.py."
        ),
        "sources": {
            "runs_jsonl_sha256": _sha256(RUNS),
            "run_classifications_sha256": _sha256(CLASSIFICATIONS),
            "m4_metrics_sha256": _sha256(M4_METRICS),
        },
        "ledger": {
            "rows_total": sum(1 for line in RUNS.read_text(encoding="utf-8").splitlines() if line.strip()),
            "product_runs": len(product),
            "product_real_model_runs": len(real),
            "product_rehearsal_runs": len(rehearsal),
            "product_real_verdicts": dict(
                sorted(collections.Counter(r.get("verdict") for r in real).items())),
            "product_distinct_tasks": len(tasks),
            # 产品发次一律不进模型能力/held-out 分母 —— 这是 RFC-010 [G4] 的
            # 分账铁律,写进事实源以便 checker 直接钉死。
            "counts_toward_model_capability": any(
                r.get("counts_toward_model_capability") for r in product),
            "counts_toward_heldout_benchmark": any(
                r.get("counts_toward_heldout_benchmark") for r in product),
            "product_runs_integrity_mismatch": product_mismatch,
            # **对外声称的硬约束**:这些发次的 PASS 是在完整性已破的状态下
            # 记下的,按现行闸应为 BLOCKED。任何引用它们的成绩必须同时说明
            # 这一点;checker 钉死"数量不得在无勘误的情况下减少"。
            "product_runs_integrity_mismatch_but_pass": product_mismatch_but_pass,
            # 干净复样覆盖情况(INTEGRITY-RESAMPLE-1)
            "clean_resample_by_task": dict(sorted(resample.items())),
            "mismatch_pass_runs_with_clean_resample": covered,
            "mismatch_pass_runs_without_clean_resample": uncovered,
        },
        "batch_2": {
            "_note": (
                "RFC-010 [G4] 口径:acceptance_rate 与 tool_ready_rate 必须成对引用。"
                "historical 与 operational 是双口径并列,不是新旧替代。"
            ),
            "submitted": m4.get("submitted"),
            "accepted": m4.get("accepted"),
            "historical_tool_ready": m4.get("historical_tool_ready"),
            "operational_ready": m4.get("operational_ready"),
            "review_required": m4.get("review_required"),
            "revoked": m4.get("revoked"),
            "replay_success": m4.get("replay_success"),
            "replay_checked": m4.get("replay_checked"),
            "acceptance_rate": m4.get("acceptance_rate"),
            "tool_ready_rate": m4.get("tool_ready_rate"),
            "false_success": m4.get("false_success"),
        },
        "frozen_artifacts": {
            "contracts": len(list((REPO / "contracts").glob("*.yaml"))),
            "tool_tasks": len([p for p in (REPO / "tool_tasks").iterdir() if p.is_dir()])
            if (REPO / "tool_tasks").exists() else None,
            "oracles": len([p for p in (REPO / "oracle").iterdir() if p.is_dir()])
            if (REPO / "oracle").exists() else None,
            "controls": len([p for p in (REPO / "controls").iterdir() if p.is_dir()])
            if (REPO / "controls").exists() else None,
        },
    }


if __name__ == "__main__":
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))
