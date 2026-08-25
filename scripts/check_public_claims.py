"""Deterministic public-claims consistency check (Gate 8A.3).

Verifies that README / BENCHMARK / CLAIMS_MATRIX agree with the
machine-readable fact source docs/benchmark_summary.json, and that no
FORBIDDEN claim wording appears in public documents. Zero LLM. Exits
non-zero with a failure list on any violation.

Run: .venv/bin/python scripts/check_public_claims.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SUMMARY = REPO / "docs" / "benchmark_summary.json"
# 产品口径事实源(2026-08-26,外部审查):benchmark_summary.json 是 MVP 时代
# 冻结的 12 发快照,覆盖不到产品线,于是本 checker 曾长期"全绿地校验一套
# 早已不再对外讲的话"。product_summary.json 补上这一半。
PRODUCT_SUMMARY = REPO / "docs" / "product_summary.json"
PUBLIC_DOCS = [REPO / "README.md", REPO / "docs" / "BENCHMARK.md", REPO / "docs" / "RESUME_CLAIMS.md",
               REPO / "docs" / "DEMO.md", REPO / "docs" / "DEMO_SCRIPT.md", REPO / "docs" / "ARCHITECTURE.md",
               REPO / "docs" / "PROJECT_EVOLUTION.md", REPO / "docs" / "INTERVIEW_GUIDE.md",
               # 当前态文档(2026-08-12 增):自己声明了闸门数,就要被同一把尺子量
               REPO / "docs" / "PROCESS-INDEPENDENCE-PLAN.md",
               # 2026-08-26 补缺口:本脚本的 docstring 一直写着"检查 CLAIMS_MATRIX",
               # 但它从来不在这张表里 —— 规则书自己不受规则约束,躺了很久。
               REPO / "docs" / "CLAIMS_MATRIX.md",
               REPO / "docs" / "PROJECT_MAP.md"]

# Wording patterns that would state a FORBIDDEN claim AS OURS. Kept
# deliberately literal; docs may still DENY these claims (denials are
# matched and excluded via the negation prefixes below).
FORBIDDEN_PATTERNS = [
    r"works (?:with|on) any (?:GitHub )?repo",
    r"supports any (?:GitHub )?repo",
    r"guarantee[sd]? (?:successful )?adapt",
    r"(?:universally|generally) (?:improves|boosts) agent success",
    r"budget awareness (?:is )?proven",
    r"ledger (?:is )?proven",
    r"security sandbox",
    r"tamper-?proof",
    r"single[- ]variable (?:experiment|delta|improvement)",
    r"production[- ](?:ready|grade) platform",
    r"matches (?:Codex|Claude Code)",
]
NEGATION_PREFIX = re.compile(
    r"(?:not|never|no|nothing|isn't|is not|nor|cannot|can't|don't|does not|doesn't"
    r"|禁止|不是|不得|非|不能|没有)[^.]{0,80}$",
    re.IGNORECASE,
)


def _fail(failures: list[str], msg: str) -> None:
    failures.append(msg)


# ---------------- V2 宿主闸门声明(2026-08-12,PROCESS-INDEPENDENCE-PLAN §5-P0-2)
# 教训(LESSONS #30):V2 的通过数只活在手打散文里,本脚本的事实源没有它们,
# 于是"T1 3 个 PASS"这种错数字全绿通过、躺了 3 天。现在:凡当前态文档出现
# 闸门数字,必须与 scripts/gate_report.py 产出的 docs/v2_gate.json 一致。
# 历史日志(LESSONS_LOG/EXPLORATION_LOG)是带时间戳的记录,豁免——
# 强迫历史匹配现值等于要求改写历史。
V2_GATE_JSON = REPO / "docs" / "v2_gate.json"
# 形如 "T1 2 / T2 2 / T3 1(/ T4 0)" 的连排声明
_V2_SLASH = re.compile(
    r"\bT1\s+(\d+)\s*/\s*T2\s+(\d+)\s*/\s*T3\s+(\d+)(?:\s*/\s*T4\s+(\d+))?")
# 形如 "T1 3 个 PASS" / "T2 阶段 2 个真实模型 PASS" 的单阶段声明。
# 刻意收紧:数字必须紧跟阶段名(至多隔 阶段/闸门/的),再紧跟 PASS——
# "T3 v5 oracle 8/8 PASS"、"T1 11 runs / 2 gate PASS" 都不命中(有单测钉死)。
_V2_SINGLE = re.compile(
    r"\bT([1-4])\s*(?:阶段|闸门|的)?\s*[::]?\s*(\d+)\s*个?\s*(?:真实模型)?\s*(?:闸门)?\s*PASS")


def find_v2_gate_violations(text: str, passes: dict[str, int], docname: str) -> list[str]:
    """当前态文档中的闸门数字声明 vs v2_gate.json 的 passes。纯函数,可单测。"""
    out: list[str] = []
    for m in _V2_SLASH.finditer(text):
        for i, stage in enumerate(("T1", "T2", "T3", "T4")):
            got = m.group(i + 1)
            if got is not None and int(got) != passes[stage]:
                out.append(f"{docname}: 闸门声明 {stage}={got} 与 v2_gate.json 的 "
                           f"{passes[stage]} 不一致(offset {m.start()})")
    for m in _V2_SINGLE.finditer(text):
        stage, got = f"T{m.group(1)}", int(m.group(2))
        if got != passes[stage]:
            out.append(f"{docname}: 闸门声明 {stage}={got} 与 v2_gate.json 的 "
                       f"{passes[stage]} 不一致(offset {m.start()})")
    return out


# ---------------- 产品口径校验(2026-08-26,外部审查)
#
# 三条规则,都针对同一个真实事故:主仓完整性曾在 completion gate **之后**
# 才计算、只落 report 不参与判定(P0-2)。修复后回头清点存量,发现 19 发
# PRODUCT PASS 的 integrity=MISMATCH,其中 10 发绑定已导出工具、8 个当时
# ACTIVE。用户 2026-08-26 裁决:记事实 + 强制限定句,不撤回、不重跑。
# 于是"限定句"必须是机器强制的,否则下一次写文档的人照旧只写漂亮数字。

# 只有这句话算数(刻意选一句长且唯一的话,防止用近义词糊弄过去)
INTEGRITY_CAVEAT = "交付发次在现行完整性闸下应判 BLOCKED"
# 出现批次二运营/历史数字 = 触发限定句义务。**按文档里实际用过的措辞**列举,
# 不按我以为它会怎么写 —— 首版只列了 `historical_tool_ready`,而 README 写的是
# "Historical pipeline READY results",于是规则装了个空枪(自测时当场发现)。
_BATCH2_CLAIM = re.compile(
    r"运营可用"
    r"|operational[_ ]ready"
    r"|historical[_ ](?:tool[_ ]ready|pipeline\s+READY)"
    r"|ACTIVE for RepoProof-managed exposure",
    re.IGNORECASE)
# 每一发受影响运行都必须有勘误行,且勘误行必须点名现行闸的判定
ERRATA_ANCHOR = "MAIN_DIR_INTEGRITY_UNATTRIBUTED"


def _load_classifications() -> dict[str, dict]:
    """后写覆盖前写 —— 与 bench_records.load_classifications 同语义。"""
    path = REPO / "benchmarks" / "v2" / "run_classifications.jsonl"
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["run_id"]] = rec
    return out


def check_product_claims(failures: list[str]) -> None:
    if not PRODUCT_SUMMARY.exists():
        _fail(failures, "product_summary.json missing — run scripts/build_product_summary.py")
        return
    ps = json.loads(PRODUCT_SUMMARY.read_text(encoding="utf-8"))

    # 1) 事实源必须新鲜:源文件 sha 变了而 summary 没重建 = 数字已经在骗人
    import hashlib
    for key, rel in (("runs_jsonl_sha256", "benchmarks/v2/runs.jsonl"),
                     ("run_classifications_sha256", "benchmarks/v2/run_classifications.jsonl"),
                     ("m4_metrics_sha256", "docs/m4_metrics.json")):
        f = REPO / rel
        want = ps.get("sources", {}).get(key)
        got = hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None
        if want != got:
            _fail(failures, f"product_summary.json 过期:{rel} 的 sha 不符 —— "
                            "重跑 scripts/build_product_summary.py")

    # 2) 产品发次永远不进 Lab 分母(RFC-010 [G4] 分账铁律)
    led = ps.get("ledger", {})
    for k in ("counts_toward_model_capability", "counts_toward_heldout_benchmark"):
        if led.get(k):
            _fail(failures, f"产品发次进入了 Lab 分母({k}=true)—— 违反 RFC-010 [G4] 分账")

    # 3) 每一发 "integrity=MISMATCH 却 PASS" 都必须有点名现行闸判定的勘误行。
    #    这条防的是"把发次从列表里悄悄拿掉"和"忘了补勘误"两种漂移。
    cls = _load_classifications()
    for rid in led.get("product_runs_integrity_mismatch_but_pass", []):
        notes = str(cls.get(rid, {}).get("notes") or "")
        if ERRATA_ANCHOR not in notes:
            _fail(failures, f"{rid}: integrity=MISMATCH 却记 PASS,但分类台账缺"
                            f"点名 {ERRATA_ANCHOR} 的勘误行")

    # 4) 公开文档凡引用批次二运营/历史数字,必须同时带完整性限定句
    for doc in PUBLIC_DOCS:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        if _BATCH2_CLAIM.search(text) and INTEGRITY_CAVEAT not in text:
            _fail(failures, f"{doc.name}: 引用了批次二运营/历史数字,却没有完整性限定句"
                            f"(必须逐字包含:{INTEGRITY_CAVEAT!r})")


def check() -> list[str]:
    failures: list[str] = []
    if not SUMMARY.exists():
        return ["benchmark_summary.json missing — run scripts/build_benchmark_summary.py"]
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    totals = summary["totals"]
    runs = summary["runs"]

    # 1) internal totals recomputable from rows (UNKNOWN never counted as 0)
    recomputed_pass = sum(1 for r in runs if r["final_verdict"] == "PASS_ADAPTED")
    if totals["pass_adapted"] != recomputed_pass:
        _fail(failures, f"totals.pass_adapted {totals['pass_adapted']} != recomputed {recomputed_pass}")
    if totals["runs_recorded"] != len(runs):
        _fail(failures, "totals.runs_recorded != len(runs)")
    if recomputed_pass != 1:
        _fail(failures, f"expected exactly 1 PASS_ADAPTED in evidence, found {recomputed_pass}")

    # 2) the PASS_ADAPTED row is fully evidenced
    pa = next(r for r in runs if r["final_verdict"] == "PASS_ADAPTED")
    for field in ("capability_passed", "capability_total", "replay_mode", "trace_sha256", "evidence_path"):
        if pa.get(field) in (None, "", "UNKNOWN"):
            _fail(failures, f"PASS_ADAPTED row missing evidenced field {field}")
    if pa["replay_mode"] != "clean_adoption":
        _fail(failures, "PASS_ADAPTED row must carry clean_adoption replay")

    # 3) headline ratios appearing in docs must exist in the summary
    known_ratios = {f"{r['capability_passed']}/{r['capability_total']}" for r in runs
                    if r["capability_passed"] is not None}
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for ratio in set(re.findall(r"\b(\d{1,2}/\d{2})\b", readme)):
        if ratio not in known_ratios:
            _fail(failures, f"README ratio {ratio} not present in benchmark_summary.json")

    # 4) BENCHMARK.md must not contradict the summary's headline ratios
    bench = (REPO / "docs" / "BENCHMARK.md").read_text(encoding="utf-8")
    for must in ("31/33", "9/12", "18/18"):
        if must in known_ratios and must not in bench:
            _fail(failures, f"BENCHMARK.md lost headline ratio {must}")

    # 5) forbidden wording in public docs (denials excluded)
    for doc in PUBLIC_DOCS:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        for pat in FORBIDDEN_PATTERNS:
            for m in re.finditer(pat, text, re.IGNORECASE):
                prefix = " ".join(text[max(0, m.start() - 90) : m.start()].split())
                if NEGATION_PREFIX.search(prefix):
                    continue  # it's a denial/limits statement
                _fail(failures, f"{doc.name}: forbidden claim wording {pat!r} at offset {m.start()}")

    # 6) UNKNOWN written as 0 is forbidden: nulls must stay null
    for r in runs:
        for k, v in r.items():
            if v == "UNKNOWN":
                _fail(failures, f"{r['case_id']}.{k} uses string UNKNOWN — use null")

    # 7) V2 宿主闸门:json 必须新鲜(与台账重算一致),且当前态文档里的
    #    闸门数字必须与之相符。数字声明只能出自 gate_report.py 的产出。
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("gate_report", REPO / "scripts" / "gate_report.py")
    gate_report = _ilu.module_from_spec(spec)
    spec.loader.exec_module(gate_report)
    for msg in gate_report.check(REPO):
        _fail(failures, msg)
    if V2_GATE_JSON.exists():
        gate = json.loads(V2_GATE_JSON.read_text(encoding="utf-8"))
        passes = {s: gate["stages"][s]["passes"] for s in ("T1", "T2", "T3", "T4")}
        for doc in PUBLIC_DOCS:
            if doc.exists():
                for msg in find_v2_gate_violations(
                        doc.read_text(encoding="utf-8"), passes, doc.name):
                    _fail(failures, msg)

    # 8) 产品口径(2026-08-26):事实源新鲜度、分账铁律、完整性勘误与限定句
    check_product_claims(failures)
    return failures


if __name__ == "__main__":
    problems = check()
    if problems:
        print(json.dumps({"ok": False, "failures": problems}, ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps({"ok": True, "failures": []}))
    sys.exit(0)
