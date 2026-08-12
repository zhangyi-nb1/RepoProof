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
PUBLIC_DOCS = [REPO / "README.md", REPO / "docs" / "BENCHMARK.md", REPO / "docs" / "RESUME_CLAIMS.md",
               REPO / "docs" / "DEMO.md", REPO / "docs" / "DEMO_SCRIPT.md", REPO / "docs" / "ARCHITECTURE.md",
               REPO / "docs" / "PROJECT_EVOLUTION.md", REPO / "docs" / "INTERVIEW_GUIDE.md",
               # 当前态文档(2026-08-12 增):自己声明了闸门数,就要被同一把尺子量
               REPO / "docs" / "PROCESS-INDEPENDENCE-PLAN.md"]

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
    return failures


if __name__ == "__main__":
    problems = check()
    if problems:
        print(json.dumps({"ok": False, "failures": problems}, ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps({"ok": True, "failures": []}))
    sys.exit(0)
