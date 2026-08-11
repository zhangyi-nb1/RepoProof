"""Benchmark V2 记录器(Phase 0 ⑥,TESTPLAN-V2 §9)。

单一事实源:`benchmarks/v2/runs.jsonl`,每 run 一行 append-only。
纪律:字段缺失/None 一律写 "UNKNOWN",**绝不写 0 冒充**(源方案 §15
与项目踩坑史:纸面 0 会被当成真实测量值,污染后续统计);未知字段
不丢弃(如实入行,便于 schema 演进);同 run_id 重复追加拒绝。

**人工再分类旁挂**(2026-08-11 增补,LESSONS #24/#26):系统 verdict
与人工取证判定可能相左(首例:order-38 系统 PASS_ADAPTED,人工判
FALSE PASS)。runs.jsonl **永不改写**——再分类写入旁挂
`adjudications.jsonl`,按 run_id 连接。**闸门与任何 PASS 统计必须走
`adjudicated_runs()` / `count_passes()`,不得直接数 runs.jsonl 的
verdict**,否则会把已判无效的假 PASS 计入。

目录布局(TESTPLAN §7/§9):

    benchmarks/v2/
    ├── runs.jsonl            事实源(本模块唯一写入点,append-only 不改写)
    ├── adjudications.jsonl   人工再分类旁挂(按 run_id 连接,亦 append-only)
    ├── preregistrations/     预注册(冻结时落盘,批作废需重预注册)
    └── reports/              停点报告(源 §48 清单)
"""

from __future__ import annotations

import json
from pathlib import Path

# TESTPLAN §9 的最少字段集(缺失写 UNKNOWN)
REQUIRED_FIELDS = (
    "run_id", "task_id", "task_version", "harness_commit", "host_commit",
    "source_commit", "model", "provider", "provider_config_hash",
    "run_index", "run_order", "guided", "max_rounds", "rounds_used",
    "model_calls", "commands", "input_tokens", "output_tokens", "wall_time",
    "cost", "public_passed_by_round", "regression_by_round", "rollback_count",
    "scope_change_count", "stagnation", "final_capability", "final_regression",
    "policy", "replay", "verdict", "failure_types", "execution_backend",
    "env_baseline_hash", "main_dir_integrity", "trace_sha256", "bundle_path",
)

UNKNOWN = "UNKNOWN"

# 计入闸门的判决。**显式集合,禁止用 "PASS" in verdict 子串判断**——
# "FALSE_PASS" 含 "PASS",子串法会把已判无效的假 PASS 数成通过。
PASS_VERDICTS = frozenset({"PASS", "PASS_ADAPTED"})

# 再分类记录的最少字段;evidence_refs 必填 = 裁定不得无出处
ADJUDICATION_REQUIRED_FIELDS = (
    "run_id", "system_verdict", "effective_verdict",
    "adjudicated_at", "adjudicated_by", "basis", "evidence_refs",
)


class BenchRecordError(RuntimeError):
    pass


def bench_root(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / "benchmarks" / "v2"


def ensure_layout(project_root: str | Path) -> Path:
    root = bench_root(project_root)
    for d in ("preregistrations", "reports"):
        (root / d).mkdir(parents=True, exist_ok=True)
    for f in ("runs.jsonl", "adjudications.jsonl"):
        if not (root / f).exists():
            (root / f).touch()
    return root


def normalise_record(record: dict) -> dict:
    """补齐必需字段(缺失/None → UNKNOWN);保留未知字段;拒绝 run_id 缺失。"""
    if not record.get("run_id"):
        raise BenchRecordError("run 记录必须携带非空 run_id")
    out = dict(record)
    for f in REQUIRED_FIELDS:
        v = out.get(f)
        if v is None or v == "":
            out[f] = UNKNOWN
    return out


def append_run(project_root: str | Path, record: dict) -> Path:
    """追加一行 run 记录;同 run_id 重复追加拒绝(append-only 事实源)。"""
    root = ensure_layout(project_root)
    rec = normalise_record(record)
    path = root / "runs.jsonl"
    for existing in load_runs(project_root):
        if existing.get("run_id") == rec["run_id"]:
            raise BenchRecordError(
                f"run_id 已存在,事实源 append-only 拒绝重写:{rec['run_id']}")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def load_runs(project_root: str | Path) -> list[dict]:
    path = bench_root(project_root) / "runs.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


# ---------------------------------------------------------------- 人工再分类

def load_adjudications(project_root: str | Path) -> list[dict]:
    path = bench_root(project_root) / "adjudications.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def append_adjudication(project_root: str | Path, record: dict) -> Path:
    """追加一条人工再分类。

    校验:①必需字段齐全(含 evidence_refs,裁定不得无出处);②run_id 必须
    存在于 runs.jsonl(不得裁定不存在的运行);③system_verdict 必须与台账
    实际值一致(防止照着记忆写错行);④同 run_id 不得重复裁定。
    **不触碰 runs.jsonl。**
    """
    root = ensure_layout(project_root)
    rec = dict(record)
    missing = [f for f in ADJUDICATION_REQUIRED_FIELDS if not rec.get(f)]
    if missing:
        raise BenchRecordError(f"再分类记录缺字段:{missing}")

    runs = {r.get("run_id"): r for r in load_runs(project_root)}
    run = runs.get(rec["run_id"])
    if run is None:
        raise BenchRecordError(f"run_id 不在 runs.jsonl 中,拒绝裁定:{rec['run_id']}")
    if run.get("verdict") != rec["system_verdict"]:
        raise BenchRecordError(
            "system_verdict 与台账不一致,拒绝写入(疑似写错行):"
            f"台账={run.get('verdict')} 记录={rec['system_verdict']}")
    for existing in load_adjudications(project_root):
        if existing.get("run_id") == rec["run_id"]:
            raise BenchRecordError(f"该 run 已有裁定,append-only 拒绝重写:{rec['run_id']}")

    path = root / "adjudications.jsonl"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def adjudicated_runs(project_root: str | Path) -> list[dict]:
    """runs.jsonl ⋈ adjudications.jsonl。

    每行附加 `effective_verdict`(无裁定则等于系统 verdict)与 `adjudication`
    (裁定原文或 None)。**闸门/统计的唯一入口**,原始 verdict 字段原样保留。
    """
    by_run = {a["run_id"]: a for a in load_adjudications(project_root)}
    out: list[dict] = []
    for run in load_runs(project_root):
        adj = by_run.get(run.get("run_id"))
        merged = dict(run)
        merged["effective_verdict"] = adj["effective_verdict"] if adj else run.get("verdict")
        merged["adjudication"] = adj
        out.append(merged)
    return out


def count_passes(project_root: str | Path, task_prefix: str | None = None) -> dict:
    """按 effective_verdict 统计 PASS(闸门判据)。

    task_prefix 形如 "t3-" 时只统计该阶段。返回 total/passes/invalidated,
    其中 invalidated = 系统判 PASS 但人工裁定不计入的条数。
    """
    rows = adjudicated_runs(project_root)
    if task_prefix:
        rows = [r for r in rows if str(r.get("task_id", "")).startswith(task_prefix)]
    passes = [r for r in rows if r["effective_verdict"] in PASS_VERDICTS]
    invalidated = [
        r for r in rows
        if r.get("verdict") in PASS_VERDICTS and r["effective_verdict"] not in PASS_VERDICTS
    ]
    return {
        "total": len(rows),
        "passes": len(passes),
        "invalidated": len(invalidated),
        "pass_run_ids": [r.get("run_id") for r in passes],
        "invalidated_run_ids": [r.get("run_id") for r in invalidated],
    }
