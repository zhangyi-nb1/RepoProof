#!/usr/bin/env python3
"""题面欠定筛查(H6 的池级扫描器;P1-c,2026-08-21)。

判定不在这里 —— 本脚本只遍历候选、读题面、调 `oracle_hygiene` 里的那**一份**
纯函数(`statement_determinacy_signals` / `judge_statement_determinacy`),把
结果写成证据。判据副本会在原件改动后静默漂移(M58a/H3 同律),所以这里连
一行正则都不复制。

为什么要有池级扫描:H6 从今往后长在准入电池里(新候选必查),但**已经在池
里的 14 条是准入之前入池的** —— 不扫一遍就等于宣称"存量干净"而没查过。

用法:
    .venv/bin/python scripts/statement_determinacy_screen.py \\
        [--pool ~/RepoProofArchive/d5-hunt/candidates] [--write]

只读封存池(池是含答案的只读对象);证据落
docs/evidence/d5_hunt/statement_determinacy/pool_screen.json。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "evidence" / "d5_hunt" / "statement_determinacy" / "pool_screen.json"
DEFAULT_POOL = Path("~/RepoProofArchive/d5-hunt/candidates").expanduser()


def _load_battery():
    spec = importlib.util.spec_from_file_location(
        "oracle_hygiene", REPO / "scripts" / "oracle_hygiene.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oracle_hygiene"] = mod
    spec.loader.exec_module(mod)
    return mod


def screen_pool(pool: Path) -> dict:
    oh = _load_battery()
    candidates = []
    for d in sorted(p for p in pool.iterdir() if p.is_dir()):
        stmt = d / "statement.md"
        if not stmt.is_file():
            # 缺题面不是"干净",是查不了 —— 显式记为 MISSING,不静默跳过。
            candidates.append({"candidate": d.name, "verdict": "MISSING",
                               "signals": None, "problems": ["statement.md 缺席"]})
            continue
        raw = stmt.read_bytes()
        signals = oh.statement_determinacy_signals(raw.decode("utf-8", "replace"))
        ok, problems = oh.judge_statement_determinacy(signals)
        candidates.append({
            "candidate": d.name,
            "statement_sha256": hashlib.sha256(raw).hexdigest(),
            "verdict": "OK" if ok else "UNDERDETERMINED",
            "signals": signals,
            "problems": problems,
        })
    flagged = [c["candidate"] for c in candidates if c["verdict"] != "OK"]
    return {
        "_what": "封存池题面欠定筛查(H6 池级扫描;判定函数= oracle_hygiene 本体)",
        "pool": str(pool),
        "candidate_count": len(candidates),
        "flagged": flagged,
        "candidates": candidates,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", type=Path, default=DEFAULT_POOL)
    ap.add_argument("--write", action="store_true", help="写证据文件")
    a = ap.parse_args()
    result = screen_pool(a.pool.expanduser())
    if a.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                  sort_keys=True) + "\n", encoding="utf-8")
        print(f"→ {OUT}")
    for c in result["candidates"]:
        s = c["signals"]
        tail = ("" if s is None else
                f"  选项={s['option_sections']} 疑问行={s['question_lines']} "
                f"对冲={len(s['hedges'])}")
        print(f"  {c['candidate']:<24} {c['verdict']}{tail}")
    print(f"命中 {len(result['flagged'])}/{result['candidate_count']}:"
          f"{result['flagged'] or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
