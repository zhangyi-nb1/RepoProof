"""Benchmark V2 记录器(Phase 0 ⑥)——UNKNOWN 纪律与 append-only 钉死。"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.persistence.bench_records import (
    REQUIRED_FIELDS,
    UNKNOWN,
    BenchRecordError,
    append_run,
    ensure_layout,
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
