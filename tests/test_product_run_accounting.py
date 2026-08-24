from __future__ import annotations

import json
from pathlib import Path

from repoproof.persistence.bench_records import (
    classify_runs,
    count_passes,
    lab_accounting_projection,
)
from repoproof.runner.host_guided import _native_product_classification
from repoproof.ui.services import live_run


def _write_run(root: Path, record: dict) -> None:
    bench = root / "benchmarks" / "v2"
    bench.mkdir(parents=True)
    (bench / "runs.jsonl").write_text(
        json.dumps(record, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_local_tool_real_run_is_natively_product_classified() -> None:
    got = _native_product_classification(
        task_family="LOCAL-TOOL", fake_mode=None
    )
    assert got["test_mode"] == "PRODUCT"
    assert got["run_purpose"] == "PRODUCT_ONBOARDING"
    assert got["classification_timing"] == "NATIVE_AT_RUN_WRITE"
    assert not any(
        got[key]
        for key in (
            "counts_toward_model_capability",
            "counts_toward_heldout_benchmark",
            "counts_toward_mechanism_effect",
            "counts_toward_treatment_effect",
        )
    )


def test_local_tool_rehearsal_is_harness_selfcheck() -> None:
    got = _native_product_classification(
        task_family="LOCAL-TOOL", fake_mode="positive"
    )
    assert got["test_mode"] == "PRODUCT"
    assert got["run_purpose"] == "HARNESS_SELFCHECK"
    assert _native_product_classification(
        task_family="T3-SIDECAR", fake_mode=None
    ) == {}


def test_native_product_fields_never_enter_lab_counts(tmp_path: Path) -> None:
    classification = _native_product_classification(
        task_family="LOCAL-TOOL", fake_mode=None
    )
    _write_run(
        tmp_path,
        {
            "run_id": "tool-demo-v3-20260824-000000",
            "task_id": "tool-demo-v3",
            "host_id": "local-tool/demo",
            "model": "gpt-5.5",
            "verdict": "PASS_ADAPTED",
            **classification,
        },
    )

    row = classify_runs(tmp_path)[0]
    assert row["run_purpose"] == "PRODUCT_ONBOARDING"
    assert row["counts_toward_model_capability"] is False
    assert row["counts_toward_heldout_benchmark"] is False
    # Historical count_passes keeps its frozen reporting semantics; new M6
    # consumers use the explicit Lab-only projection.
    assert count_passes(tmp_path)["passes"] == 0
    counts = lab_accounting_projection(tmp_path)
    assert counts["recorded_total"] == 1
    assert counts["product_runs"] == 1
    assert counts["lab_total"] == 0
    assert counts["model_capability_runs"] == 0
    assert counts["model_capability_passes"] == 0
    assert counts["all_valid_run_outcomes"] == 0
    assert counts["mechanism_ablation_runs"] == 0
    assert counts["heldout_model_evaluation_runs"] == 0
    assert counts["assisted_repair_runs"] == 0
    assert counts["profile_qualification_runs"] == 0


def test_classification_sidecar_cannot_promote_native_product_run(
    tmp_path: Path,
) -> None:
    classification = _native_product_classification(
        task_family="LOCAL-TOOL", fake_mode=None
    )
    run_id = "tool-demo-v3-20260824-000001"
    _write_run(
        tmp_path,
        {
            "run_id": run_id,
            "task_id": "tool-demo-v3",
            "host_id": "local-tool/demo",
            "model": "gpt-5.5",
            "verdict": "PASS_ADAPTED",
            **classification,
        },
    )
    sidecar = tmp_path / "benchmarks" / "v2" / "run_classifications.jsonl"
    sidecar.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "test_mode": "BENCHMARK",
                "run_purpose": "CAPABILITY_EVALUATION",
                "counts_toward_model_capability": True,
                "counts_toward_heldout_benchmark": True,
                "counts_toward_mechanism_effect": True,
                "counts_toward_treatment_effect": True,
                "treatment_assigned": True,
                "treatment_activated": True,
                "oracle_authorship": "UPSTREAM_OWN_TEST_SUITE",
                "host_modification_mode": "PRISTINE_UPSTREAM",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    row = classify_runs(tmp_path)[0]
    assert row["test_mode"] == "PRODUCT"
    assert row["run_purpose"] == "PRODUCT_ONBOARDING"
    assert row["counts_toward_model_capability"] is False
    assert row["counts_toward_heldout_benchmark"] is False
    assert row["counts_toward_mechanism_effect"] is False
    assert row["counts_toward_treatment_effect"] is False
    assert row["treatment_assigned"] is False
    assert row["treatment_activated"] is None
    assert count_passes(tmp_path)["passes"] == 0
    counts = lab_accounting_projection(tmp_path)
    assert counts["recorded_total"] == 1
    assert counts["product_runs"] == 1
    assert counts["lab_total"] == 0
    assert counts["model_capability_passes"] == 0
    assert counts["all_valid_run_outcomes"] == 0


def test_product_rows_and_sidecar_demotion_do_not_change_lab_run_order(
    tmp_path: Path,
) -> None:
    bench = tmp_path / "benchmarks" / "v2"
    bench.mkdir(parents=True)
    lab_id = "t1-offerclaw-fastapi-mcp-v1-20260824-000000"
    product_id = "tool-demo-v1-20260824-000001"
    rows = [
        {
            "run_id": lab_id,
            "task_id": "t1-offerclaw-fastapi-mcp-v1",
            "host_id": "zhangyi-nb1/offerclaw",
            "model": "gpt-5.5",
            "verdict": "PASS_ADAPTED",
        },
        {
            "run_id": product_id,
            "task_id": "tool-demo-v1",
            "host_id": "local-tool/demo",
            "model": "gpt-5.5",
            "verdict": "PASS_ADAPTED",
            **_native_product_classification(
                task_family="LOCAL-TOOL", fake_mode=None
            ),
        },
    ]
    (bench / "runs.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (bench / "run_classifications.jsonl").write_text(
        json.dumps(
            {
                "run_id": lab_id,
                "test_mode": "PRODUCT",
                "run_purpose": "PRODUCT_ONBOARDING",
                "counts_toward_model_capability": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = live_run.host_task_state(tmp_path, "T1")
    assert state["next_global_order"] == 2
    assert [row["run_id"] for row in state["done"]] == [lab_id]
