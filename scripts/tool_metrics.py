"""M4 产品指标 —— 唯一数字出口(RFC-010 [G4];散文只解释不下判断)。

四指标(口径由预注册冻结,本脚本忠实执行):
  acceptance_rate  = accepted / submitted   —— 与 tool_ready_rate **成对报**
  tool_ready_rate  = tool_ready / accepted     (防把准入闸调严刷指标)
  replay_success   = 自动重装口径(build.sh + --help)通过数 / tool_ready
  false_success    = 人工审计单(m4_audits.jsonl)中 flagged / audited

M5 双口径(RFC-011 §六):
  historical_tool_ready = 原 tool_ready，历史流水线结论永不追改
  operational_ready / review_required / revoked
                         = 运营决策账最后决定的当前投影

判定来源(全部盘上事实,零执行零 LLM):
  submitted   预注册任务清单 json(冻结件,--tasks)
  accepted    contracts/ 下存在 source_repo.url 匹配该清单项的冻结契约
              (sidecar 在;confirm 过即冻结)
  tool_ready  registry 导出项绑定的 run_id 在 runs.jsonl 中属于**真模型发**
              (model 不带 fake 前缀)且 verdict ∈ PASS_*；后续模型对比发次
              不得反向改写已导出的历史 READY
  replay      benchmarks/v2/m4_replay.jsonl(scripts/m4_replay_check.py 产)
  audits      benchmarks/v2/m4_audits.jsonl(人工审计,append-only)
  release     <dest_root>/.repoproof-release-decisions.jsonl(append-only)

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

from repoproof.runner.tool_release import (
    load_release_decisions_file,
    parse_operator_audit_outcome,
)

REPO = Path(__file__).resolve().parents[1]
OUT_JSON = REPO / "docs" / "m4_metrics.json"
RELEASE_DECISIONS = ".repoproof-release-decisions.jsonl"
RELEASE_STATUSES = frozenset({"ACTIVE", "REVIEW_REQUIRED", "REVOKED"})


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()
            if x.strip()]


def _release_decisions(path: Path | None) -> dict[str, dict]:
    """Fold the strictly validated append-only ledger by tool name."""
    if path is None:
        return {}
    decisions: dict[str, dict] = {}
    for row in load_release_decisions_file(path):
        decisions[row["tool"]] = row
    return decisions


def _audit_ok(row: dict, *, where: str) -> bool:
    """Use the release migration's compatible, contradiction-safe parser."""

    return parse_operator_audit_outcome(row, where=where)


def compute(project_root: Path, tasks_file: Path,
            dest_root: Path | None = None,
            release_decisions_file: Path | None = None) -> dict:
    tasks = json.loads(Path(tasks_file).read_text(encoding="utf-8"))["tasks"]
    runs = _jsonl(project_root / "benchmarks" / "v2" / "runs.jsonl")
    replays = {r["task_id"]: r for r in
               _jsonl(project_root / "benchmarks" / "v2" / "m4_replay.jsonl")}
    audits = _jsonl(project_root / "benchmarks" / "v2" / "m4_audits.jsonl")
    if release_decisions_file is None and dest_root is not None:
        release_decisions_file = Path(dest_root) / RELEASE_DECISIONS
    release_by_tool = _release_decisions(release_decisions_file)

    registry: dict = {}
    if dest_root is not None:
        reg_p = Path(dest_root) / ".repoproof-registry.json"
        if reg_p.is_file():
            registry = json.loads(reg_p.read_text(encoding="utf-8"))["tools"]
    reg_by_task: dict[str, dict] = {}
    for name, entry in registry.items():
        task_id = entry.get("task_id")
        if isinstance(task_id, str) and task_id:
            reg_by_task[task_id] = {"name": name, **entry}
        # A same-command task upgrade replaces the current package index but
        # must not erase an older batch's historical READY numerator.  The
        # archived package remains the evidence source; registry is only its
        # task/run/path index.
        for previous in entry.get("previous_versions", []):
            if not isinstance(previous, dict):
                continue
            previous_task_id = previous.get("task_id")
            if not isinstance(previous_task_id, str) or not previous_task_id:
                continue
            archive_path = previous.get("archive_path")
            if archive_path and dest_root is not None:
                archive = Path(archive_path)
                if not archive.is_absolute():
                    archive = Path(dest_root) / archive
                archive_path = str(archive)
            reg_by_task.setdefault(
                previous_task_id,
                {
                    "name": name,
                    "task_id": previous_task_id,
                    "run_id": previous.get("run_id"),
                    "contract_sha256": previous.get("contract_sha256"),
                    "path": archive_path,
                    "historical_verdict": previous.get("historical_verdict"),
                },
            )

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
    release_counts = {status: 0 for status in RELEASE_STATUSES}
    for t in tasks:
        url = t["repo"].rstrip("/")
        row: dict = {"repo": url, "capability": t["capability"],
                     "accepted": False, "task_id": None, "real_verdict": None,
                     "tool_ready": False, "historical_tool_ready": False,
                     "operational_status": None,
                     "exported": None, "replay": None}
        c = contracts.get(url)
        if c is not None:
            row["accepted"] = True
            row["task_id"] = c["task_id"]
            n_accepted += 1
            reg = reg_by_task.get(c["task_id"])
            exported_run_id = reg.get("run_id") if reg else None
            if exported_run_id:
                # Historical READY belongs to the exact run exported into the
                # registry. A later model-comparison run for the same frozen
                # task must not rewrite that product fact.
                real = [r for r in runs
                        if r.get("run_id") == exported_run_id
                        and not str(r.get("model", "")).startswith("fake")]
            else:
                # Compatibility for old/synthetic registries that predate a
                # run_id. Current Product Mode registrations always carry it.
                real = [r for r in runs
                        if r.get("task_id") == c["task_id"]
                        and not str(r.get("model", "")).startswith("fake")]
            if real:
                row["real_verdict"] = real[-1].get("verdict")
            if reg:
                row["exported"] = reg.get("path")
            if (row["real_verdict"] or "").startswith("PASS") and reg:
                row["tool_ready"] = True
                row["historical_tool_ready"] = True
                n_ready += 1
                release = release_by_tool.get(reg["name"])
                status = (
                    release["decision"]
                    if release is not None
                    and release["task_id"] == c["task_id"]
                    else "REVIEW_REQUIRED"
                )
                row["operational_status"] = status
                release_counts[status] += 1
                rp = replays.get(c["task_id"])
                if rp is not None:
                    row["replay"] = rp.get("ok")
                    n_replay_pass += bool(rp.get("ok"))
        per_task.append(row)

    task_ids = {r["task_id"] for r in per_task}
    audited_with_outcome = [
        (audit, _audit_ok(
            audit,
            where=f"{project_root / 'benchmarks' / 'v2' / 'm4_audits.jsonl'}:{line_no}",
        ))
        for line_no, audit in enumerate(audits, start=1)
        if audit.get("task_id") in task_ids
    ]
    audited = [audit for audit, _outcome in audited_with_outcome]
    flagged = [audit for audit, outcome in audited_with_outcome if outcome is False]
    n = len(tasks)
    out = {
        "submitted": n,
        "accepted": n_accepted,
        "acceptance_rate": round(n_accepted / n, 3) if n else None,
        "tool_ready": n_ready,
        "historical_tool_ready": n_ready,
        "tool_ready_rate": (round(n_ready / n_accepted, 3)
                            if n_accepted else None),
        "operational_ready": release_counts["ACTIVE"],
        "review_required": release_counts["REVIEW_REQUIRED"],
        "revoked": release_counts["REVOKED"],
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
    ap.add_argument("--release-decisions", type=Path,
                    help="运营决策 JSONL；默认 <dest-root>/"
                         ".repoproof-release-decisions.jsonl")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    out = compute(REPO, a.tasks, a.dest_root, a.release_decisions)
    text = json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if a.write:
        OUT_JSON.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
