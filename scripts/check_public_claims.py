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
               REPO / "docs" / "PROJECT_EVOLUTION.md", REPO / "docs" / "INTERVIEW_GUIDE.md"]

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
    return failures


if __name__ == "__main__":
    problems = check()
    if problems:
        print(json.dumps({"ok": False, "failures": problems}, ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps({"ok": True, "failures": []}))
    sys.exit(0)
