"""M4 模型对比批驱动(M4-MODEL-COMPARE-DS-1 · 预注册 20260823)。

对批次一 12 个冻结任务包换 provider 重发一发:不 export、不 register、
不覆盖已交付工具 —— 只产 verdict 对比数据。provider 全部由 env 决定
(deepseek-native 四键由调用 shell 注入;本脚本不碰任何密钥)。

幂等续跑:台账里本批(--batch 标签)已有该任务的行 → 跳过;
金丝雀模式:--only <task_id> 单发(取证后再放行全批)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# 预注册 §三 冻结清单(顺序同批次一)
TASKS = [
    "tool-python-slugify-tool-v1",
    "tool-ftfy-tool-v1",
    "tool-unidecode-tool-v1",
    "tool-pyyaml-tool-v1",
    "tool-json5-tool-v1",
    "tool-markdown-tool-v1",
    "tool-pygments-tool-v1",
    "tool-tabulate-tool-v1",
    "tool-humanize-tool-v1",
    "tool-chardet-tool-v1",
    "tool-python-dateutil-tool-v1",
    "tool-feedparser-tool-v1",
]
BATCH = "M4-MODEL-COMPARE-DS-1"
CAP_IN = 6_000_000          # 批帽:名义 in 触顶即停(预注册 §二)


def _batch_rows(batch: str) -> dict[str, dict]:
    """台账里本批已有的 {task_id: row}(幂等续跑依据)。"""
    seen: dict[str, dict] = {}
    ledger = REPO / "benchmarks" / "v2" / "runs.jsonl"
    if not ledger.is_file():
        return seen
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("batch") == batch:
            seen[row.get("task_id", "")] = row
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只发一个任务(金丝雀取证)")
    ap.add_argument("--reissue", help="显式补发一个已有行的任务(用户批准的"
                                      "harness 修复复验;绕过幂等跳过与批帽——"
                                      "帽外授权必须来自用户,勘误区记录)")
    ap.add_argument("--batch", default=BATCH)
    args = ap.parse_args()

    from repoproof.runner.host_guided import run_host_guided_cli

    done = _batch_rows(args.batch)
    spent_in = sum(r.get("input_tokens") or 0 for r in done.values())
    todo = [t for t in TASKS if t not in done]
    if args.reissue:
        todo = [args.reissue]
    elif args.only:
        todo = [t for t in todo if t == args.only]

    results = []
    for i, task_id in enumerate(todo):
        if spent_in >= CAP_IN and not args.reissue:
            print(f"批帽触顶:{spent_in:,} >= {CAP_IN:,},停批", file=sys.stderr)
            break
        if args.reissue and spent_in >= CAP_IN:
            print(f"帽外补发(用户显式授权):已花 {spent_in:,} >= {CAP_IN:,}",
                  file=sys.stderr)
        contract = REPO / "tool_tasks" / task_id / "contract.yaml"
        if not contract.is_file():
            results.append({"task_id": task_id, "verdict": "MISSING_TASK_PKG"})
            continue
        print(f"[{len(done) + i + 1}/{len(TASKS)}] {task_id} …", flush=True)
        out = run_host_guided_cli(
            contract, REPO, fake=None,
            run_order=f"compare-{len(done) + i + 1}", batch=args.batch)
        if out.get("blocked"):
            results.append({"task_id": task_id, "verdict": "BLOCKED",
                            "detail": out.get("preflight")})
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
            break                        # 系统层拦截:停批排障,不硬闯
        rp = out.get("report") or {}
        row = {"task_id": task_id, "run_id": rp.get("run_id"),
               "verdict": rp.get("verdict"),
               "gate_reasons": (rp.get("gate_reasons") or [])[:2]}
        # 批帽核算以台账为准(runner 返回前已落账;report 不保证带 tokens)
        spent_in = sum(r.get("input_tokens") or 0
                       for r in _batch_rows(args.batch).values())
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    print(json.dumps({"batch": args.batch, "new_runs": results,
                      "spent_in_after": spent_in}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
