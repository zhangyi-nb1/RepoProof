"""M4 产品指标 —— 唯一数字出口(RFC-010 [G4];散文只解释不下判断)。

四指标(口径由预注册冻结,本脚本忠实执行):
  acceptance_rate  = accepted / submitted   —— 与 tool_ready_rate **成对报**
  tool_ready_rate  = tool_ready / accepted     (防把准入闸调严刷指标)
  replay_success   = 自动重装口径(build.sh + --help)通过数 / tool_ready
  false_success    = 人工审计单(m4_audits.jsonl)中 flagged / audited

判定来源(全部盘上事实,零执行零 LLM):
  submitted   预注册任务清单 json(冻结件,--tasks)
  accepted    contracts/ 下存在 source_repo.url 匹配该清单项的冻结契约
              (sidecar 在;confirm 过即冻结)
  tool_ready  runs.jsonl 该 task_id 的**真模型发**(model 不带 fake 前缀)
              末发 verdict ∈ PASS_* 且注册表有导出项
  replay      benchmarks/v2/m4_replay.jsonl(scripts/m4_replay_check.py 产)
  audits      benchmarks/v2/m4_audits.jsonl(人工审计,append-only)

用法:
  .venv/bin/python scripts/tool_metrics.py \
      --tasks benchmarks/v2/preregistrations/M4-batch-1-tasks.json [--write]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
OUT_JSON = REPO / "docs" / "m4_metrics.json"


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()
            if x.strip()]


def compute(project_root: Path, tasks_file: Path,
            dest_root: Path | None = None) -> dict:
    tasks = json.loads(Path(tasks_file).read_text(encoding="utf-8"))["tasks"]
    runs = _jsonl(project_root / "benchmarks" / "v2" / "runs.jsonl")
    replays = {r["task_id"]: r for r in
               _jsonl(project_root / "benchmarks" / "v2" / "m4_replay.jsonl")}
    audits = _jsonl(project_root / "benchmarks" / "v2" / "m4_audits.jsonl")

    registry: dict = {}
    if dest_root is not None:
        reg_p = Path(dest_root) / ".repoproof-registry.json"
        if reg_p.is_file():
            registry = json.loads(reg_p.read_text(encoding="utf-8"))["tools"]
    reg_by_task = {e.get("task_id"): {"name": n, **e}
                   for n, e in registry.items()}

    # url → 冻结契约(accepted 的判定物)
    contracts: dict[str, dict] = {}
    for cp in sorted((project_root / "contracts").glob("tool-*.yaml")):
        if not Path(str(cp) + ".sha256").is_file():
            continue                       # 未冻结不算 accepted
        doc = yaml.safe_load(cp.read_text(encoding="utf-8"))
        url = ((doc.get("source_repo") or {}).get("url") or "").rstrip("/")
        contracts.setdefault(url, doc)

    per_task: list[dict] = []
    n_accepted = n_ready = n_replay_pass = 0
    for t in tasks:
        url = t["repo"].rstrip("/")
        row: dict = {"repo": url, "capability": t["capability"],
                     "accepted": False, "task_id": None, "real_verdict": None,
                     "tool_ready": False, "exported": None, "replay": None}
        c = contracts.get(url)
        if c is not None:
            row["accepted"] = True
            row["task_id"] = c["task_id"]
            n_accepted += 1
            real = [r for r in runs
                    if r.get("task_id") == c["task_id"]
                    and not str(r.get("model", "")).startswith("fake")]
            if real:
                row["real_verdict"] = real[-1].get("verdict")
            reg = reg_by_task.get(c["task_id"])
            if reg:
                row["exported"] = reg.get("path")
            if (row["real_verdict"] or "").startswith("PASS") and reg:
                row["tool_ready"] = True
                n_ready += 1
                rp = replays.get(c["task_id"])
                if rp is not None:
                    row["replay"] = rp.get("ok")
                    n_replay_pass += bool(rp.get("ok"))
        per_task.append(row)

    audited = [a for a in audits
               if a.get("task_id") in {r["task_id"] for r in per_task}]
    flagged = [a for a in audited if not a.get("ok")]
    n = len(tasks)
    out = {
        "submitted": n,
        "accepted": n_accepted,
        "acceptance_rate": round(n_accepted / n, 3) if n else None,
        "tool_ready": n_ready,
        "tool_ready_rate": (round(n_ready / n_accepted, 3)
                            if n_accepted else None),
        "_pairing_note": "acceptance_rate 与 tool_ready_rate 必须成对引用"
                         "(单引后者 = 准入闸可刷指标,[G4] 禁止)",
        "replay_checked": len([r for r in per_task if r["replay"] is not None]),
        "replay_success": n_replay_pass,
        "false_success": {"audited": len(audited), "flagged": len(flagged),
                          "flagged_tasks": sorted({a["task_id"] for a in flagged})},
        "per_task": per_task,
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument("--dest-root", type=Path,
                    default=Path("~/tools").expanduser())
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    out = compute(REPO, a.tasks, a.dest_root)
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if a.write:
        OUT_JSON.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
