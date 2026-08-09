"""Benchmark V2 记录器(Phase 0 ⑥,TESTPLAN-V2 §9)。

单一事实源:`benchmarks/v2/runs.jsonl`,每 run 一行 append-only。
纪律:字段缺失/None 一律写 "UNKNOWN",**绝不写 0 冒充**(源方案 §15
与项目踩坑史:纸面 0 会被当成真实测量值,污染后续统计);未知字段
不丢弃(如实入行,便于 schema 演进);同 run_id 重复追加拒绝。

目录布局(TESTPLAN §7/§9):

    benchmarks/v2/
    ├── runs.jsonl            事实源(本模块唯一写入点)
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


class BenchRecordError(RuntimeError):
    pass


def bench_root(project_root: str | Path) -> Path:
    return Path(project_root).expanduser().resolve() / "benchmarks" / "v2"


def ensure_layout(project_root: str | Path) -> Path:
    root = bench_root(project_root)
    for d in ("preregistrations", "reports"):
        (root / d).mkdir(parents=True, exist_ok=True)
    if not (root / "runs.jsonl").exists():
        (root / "runs.jsonl").touch()
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
