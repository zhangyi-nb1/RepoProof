"""Benchmark V2 记录器(Phase 0 ⑥)——UNKNOWN 纪律与 append-only 钉死。"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.persistence.bench_records import (
    PASS_VERDICTS,
    REQUIRED_FIELDS,
    UNKNOWN,
    BenchRecordError,
    adjudicated_runs,
    append_adjudication,
    append_run,
    bench_root,
    count_passes,
    ensure_layout,
    load_adjudications,
    load_runs,
)


def test_layout_and_unknown_discipline(tmp_path: Path) -> None:
    root = ensure_layout(tmp_path)
    assert (root / "preregistrations").is_dir() and (root / "reports").is_dir()

    append_run(tmp_path, {"run_id": "r1", "model": "gpt-5.5", "cost": None})
    rec = load_runs(tmp_path)[0]
    assert rec["model"] == "gpt-5.5"
    assert rec["cost"] == UNKNOWN                     # None → UNKNOWN,绝不写 0
    missing = [f for f in REQUIRED_FIELDS if f not in rec]
    assert not missing                                 # 必需字段全部在场
    assert rec["verdict"] == UNKNOWN and rec["verdict"] != 0


def test_append_only_rejects_duplicate_and_requires_run_id(tmp_path: Path) -> None:
    append_run(tmp_path, {"run_id": "r1"})
    with pytest.raises(BenchRecordError, match="append-only"):
        append_run(tmp_path, {"run_id": "r1", "verdict": "PASS_ADAPTED"})
    with pytest.raises(BenchRecordError, match="run_id"):
        append_run(tmp_path, {"model": "x"})
    assert len(load_runs(tmp_path)) == 1              # 拒绝不留半行


def test_unknown_extra_fields_preserved(tmp_path: Path) -> None:
    append_run(tmp_path, {"run_id": "r2", "novel_metric": 42})
    rec = [r for r in load_runs(tmp_path) if r["run_id"] == "r2"][0]
    assert rec["novel_metric"] == 42                  # schema 演进不丢数据


# ------------------------------------------------ 人工再分类旁挂(LESSONS #26)

def _adj(run_id: str, **over) -> dict:
    rec = {
        "run_id": run_id, "system_verdict": "PASS_ADAPTED",
        "effective_verdict": "INVALIDATED_FALSE_PASS",
        "adjudicated_at": "2026-08-11", "adjudicated_by": "manual-forensics",
        "basis": "判别子被伪造穿透", "evidence_refs": {"report": "r.md"},
    }
    rec.update(over)
    return rec


def test_adjudication_never_touches_runs_jsonl(tmp_path: Path) -> None:
    """旁挂写入后事实源逐字节不变——'别动原文件'的钉死。"""
    append_run(tmp_path, {"run_id": "r1", "verdict": "PASS_ADAPTED"})
    runs_path = bench_root(tmp_path) / "runs.jsonl"
    before = runs_path.read_bytes()

    append_adjudication(tmp_path, _adj("r1"))

    assert runs_path.read_bytes() == before           # 原文件零改动
    assert load_runs(tmp_path)[0]["verdict"] == "PASS_ADAPTED"   # 原判决原样保留


def test_effective_verdict_join_and_pass_count(tmp_path: Path) -> None:
    append_run(tmp_path, {"run_id": "good", "task_id": "t3-x", "verdict": "PASS_ADAPTED"})
    append_run(tmp_path, {"run_id": "fake", "task_id": "t3-x", "verdict": "PASS_ADAPTED"})
    append_run(tmp_path, {"run_id": "bad", "task_id": "t3-x", "verdict": "FAIL"})
    append_adjudication(tmp_path, _adj("fake"))

    rows = {r["run_id"]: r for r in adjudicated_runs(tmp_path)}
    assert rows["good"]["effective_verdict"] == "PASS_ADAPTED"   # 无裁定 → 沿用系统判
    assert rows["good"]["adjudication"] is None
    assert rows["fake"]["effective_verdict"] == "INVALIDATED_FALSE_PASS"
    assert rows["fake"]["verdict"] == "PASS_ADAPTED"             # 原字段不被覆盖

    c = count_passes(tmp_path, "t3-")
    assert c["total"] == 3 and c["passes"] == 1 and c["invalidated"] == 1
    assert c["pass_run_ids"] == ["good"] and c["invalidated_run_ids"] == ["fake"]


def test_false_pass_not_counted_by_substring(tmp_path: Path) -> None:
    """'FALSE_PASS' 含子串 PASS —— 显式集合判定,禁止 `"PASS" in verdict`。"""
    assert "PASS" in "INVALIDATED_FALSE_PASS"          # 子串法会误计,故必须集合法
    assert "INVALIDATED_FALSE_PASS" not in PASS_VERDICTS
    assert PASS_VERDICTS == frozenset({"PASS", "PASS_ADAPTED"})


def test_adjudication_guards(tmp_path: Path) -> None:
    append_run(tmp_path, {"run_id": "r1", "verdict": "PASS_ADAPTED"})

    with pytest.raises(BenchRecordError, match="不在 runs.jsonl"):
        append_adjudication(tmp_path, _adj("nope"))            # 不得裁定不存在的运行
    with pytest.raises(BenchRecordError, match="与台账不一致"):
        append_adjudication(tmp_path, _adj("r1", system_verdict="FAIL"))  # 防写错行
    with pytest.raises(BenchRecordError, match="缺字段"):
        append_adjudication(tmp_path, _adj("r1", evidence_refs=None))     # 裁定须有出处

    append_adjudication(tmp_path, _adj("r1"))
    with pytest.raises(BenchRecordError, match="append-only"):
        append_adjudication(tmp_path, _adj("r1"))              # 同 run 不得重复裁定
    assert len(load_adjudications(tmp_path)) == 1              # 拒绝不留半行
