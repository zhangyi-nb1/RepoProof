"""M4 指标脚本的自证([G4] · 数字只出自一个脚本,脚本先证明自己算得对)。

合成世界喂正反例:未冻结(无 sidecar)不算 accepted;fake 发不算真发;
真发 FAIL 不算 ready;导出+PASS 才 ready;replay/audit 各自归位;
成对语义标注必须在输出里(防单引 tool_ready_rate);M5 历史与运营
双口径并列，运营撤回绝不追改历史 READY。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _release_decision(
    task_id: str,
    decision: str,
    *,
    tool: str | None = None,
    evidence_sha256: str = "0" * 64,
) -> dict:
    return {
        "schema_version": 1,
        "tool": tool or task_id.removeprefix("tool-").removesuffix("-v1"),
        "task_id": task_id,
        "run_id": f"run-{task_id}",
        "decision": decision,
        "reason_code": "SYNTHETIC_TEST",
        "reason": "synthetic metrics projection",
        "evidence_sha256": evidence_sha256,
        "decided_at": "2026-08-23T00:00:00Z",
        "actor": "operator",
    }


def _mod():
    spec = importlib.util.spec_from_file_location(
        "tool_metrics", REPO / "scripts" / "tool_metrics.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _world(tmp: Path) -> tuple[Path, Path, Path]:
    (tmp / "contracts").mkdir()
    b = tmp / "benchmarks" / "v2"
    b.mkdir(parents=True)

    def contract(tid: str, url: str, *, frozen: bool = True) -> None:
        p = tmp / "contracts" / f"{tid}.yaml"
        p.write_text(f"task_id: {tid}\nsource_repo:\n  url: {url}\n",
                     encoding="utf-8")
        if frozen:
            Path(str(p) + ".sha256").write_text("x  y\n", encoding="utf-8")

    contract("tool-a-v1", "https://github.com/x/a")            # ready 全链
    contract("tool-b-v1", "https://github.com/x/b")            # 真发 FAIL
    contract("tool-c-v1", "https://github.com/x/c", frozen=False)  # 未冻结
    # x/d:连契约都没有(admission 拒/未 confirm)

    runs = [
        {"task_id": "tool-a-v1", "model": "fake-scripted:positive",
         "run_id": "fake-a", "verdict": "FAIL"},              # fake 不算
        {"task_id": "tool-a-v1", "model": "gpt-5.5",
         "run_id": "run-a", "verdict": "PASS_ADAPTED"},
        {"task_id": "tool-b-v1", "model": "gpt-5.5",
         "run_id": "run-b", "verdict": "FAIL"},
    ]
    (b / "runs.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in runs), encoding="utf-8")
    (b / "m4_replay.jsonl").write_text(
        json.dumps({"task_id": "tool-a-v1", "ok": True}) + "\n", encoding="utf-8")
    (b / "m4_audits.jsonl").write_text(
        json.dumps({"task_id": "tool-a-v1", "ok": False, "notes": "输出截断"})
        + "\n", encoding="utf-8")

    dest = tmp / "tools"
    dest.mkdir()
    (dest / ".repoproof-registry.json").write_text(json.dumps({
        "schema_version": 1,
        "tools": {"a": {"path": str(dest / "a"), "task_id": "tool-a-v1",
                        "run_id": "run-a",
                        "verdict": "VERIFIED_TOOL_READY"}}}), encoding="utf-8")

    tasks = tmp / "tasks.json"
    tasks.write_text(json.dumps({"tasks": [
        {"repo": "https://github.com/x/a", "capability": "ga"},
        {"repo": "https://github.com/x/b", "capability": "gb"},
        {"repo": "https://github.com/x/c", "capability": "gc"},
        {"repo": "https://github.com/x/d", "capability": "gd"},
    ]}), encoding="utf-8")
    return tmp, tasks, dest


def test_four_metrics_and_paired_semantics(tmp_path):
    root, tasks, dest = _world(tmp_path)
    out = _mod().compute(root, tasks, dest)

    assert out["submitted"] == 4
    assert out["accepted"] == 2, "未冻结/无契约不得算 accepted"
    assert out["acceptance_rate"] == 0.5
    assert out["tool_ready"] == 1, "真发 FAIL 不算;fake PASS 也不算"
    assert out["historical_tool_ready"] == 1
    assert out["tool_ready_rate"] == 0.5
    assert out["operational_ready"] == 0
    assert out["review_required"] == 1, "无运营决定必须 fail-closed"
    assert out["revoked"] == 0
    assert "成对" in out["_pairing_note"], "[G4] 成对语义必须写死在输出里"
    assert out["replay_checked"] == 1 and out["replay_success"] == 1
    assert out["false_success"] == {"audited": 1, "flagged": 1,
                                    "flagged_tasks": ["tool-a-v1"]}

    rows = {r["repo"]: r for r in out["per_task"]}
    assert rows["https://github.com/x/a"]["tool_ready"] is True
    assert rows["https://github.com/x/b"]["real_verdict"] == "FAIL"
    assert rows["https://github.com/x/c"]["accepted"] is False
    assert rows["https://github.com/x/d"]["accepted"] is False


def test_empty_world_yields_nulls_not_crashes(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "benchmarks" / "v2").mkdir(parents=True)
    tasks = tmp_path / "t.json"
    tasks.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    out = _mod().compute(tmp_path, tasks, None)
    assert out["submitted"] == 0 and out["acceptance_rate"] is None
    assert out["tool_ready_rate"] is None


def test_later_model_comparison_does_not_rewrite_exported_ready_run(tmp_path):
    root, tasks, dest = _world(tmp_path)
    runs_path = root / "benchmarks" / "v2" / "runs.jsonl"
    with runs_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "task_id": "tool-a-v1",
            "run_id": "compare-a",
            "model": "deepseek-v4-pro",
            "verdict": "FAIL",
            "batch": "MODEL_COMPARE",
        }) + "\n")

    out = _mod().compute(root, tasks, dest)
    row = next(r for r in out["per_task"] if r["task_id"] == "tool-a-v1")
    assert row["real_verdict"] == "PASS_ADAPTED"
    assert row["historical_tool_ready"] is True


def test_batch_two_history_and_operational_release_are_both_reported(tmp_path):
    (tmp_path / "contracts").mkdir()
    bench = tmp_path / "benchmarks" / "v2"
    bench.mkdir(parents=True)
    dest = tmp_path / "tools"
    dest.mkdir()

    tasks: list[dict] = []
    runs: list[dict] = []
    audits: list[dict] = []
    decisions: list[dict] = []
    registry: dict[str, dict] = {}
    for i in range(10):
        task_id = f"tool-batch-two-{i}-v1"
        repo = f"https://github.com/x/batch-two-{i}"
        tasks.append({"repo": repo, "capability": f"cap-{i}"})
        contract = tmp_path / "contracts" / f"{task_id}.yaml"
        contract.write_text(
            f"task_id: {task_id}\nsource_repo:\n  url: {repo}\n",
            encoding="utf-8")
        Path(str(contract) + ".sha256").write_text("frozen\n", encoding="utf-8")
        runs.append({"task_id": task_id, "model": "gpt-5.5",
                     "verdict": "PASS_ADAPTED"})
        registry[f"batch-two-{i}"] = {
            "path": str(dest / f"batch-two-{i}"), "task_id": task_id}
        # 前九行模拟旧 verdict-only 格式；最后一行验证显式 ok 优先。
        audits.append({"task_id": task_id, "verdict": "PASS"})
        decisions.append(_release_decision(
            task_id, "ACTIVE", tool=f"batch-two-{i}", evidence_sha256=f"{i:064x}"))

    withdrawn = "tool-batch-two-9-v1"
    audits[-1] = {"task_id": withdrawn, "ok": False, "verdict": "FAIL"}
    decisions.append(_release_decision(
        withdrawn, "REVOKED", tool="batch-two-9", evidence_sha256="f" * 64))
    (bench / "runs.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in runs), encoding="utf-8")
    (bench / "m4_audits.jsonl").write_text(
        "".join(json.dumps(a) + "\n" for a in audits), encoding="utf-8")
    (dest / ".repoproof-registry.json").write_text(json.dumps({
        "schema_version": 1, "tools": registry}), encoding="utf-8")
    (dest / ".repoproof-release-decisions.jsonl").write_text(
        "".join(json.dumps(d) + "\n" for d in decisions), encoding="utf-8")
    task_file = tmp_path / "batch-two.json"
    task_file.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")

    out = _mod().compute(tmp_path, task_file, dest)

    assert out["tool_ready"] == 10, "既有历史字段与数字不得追改"
    assert out["historical_tool_ready"] == 10
    assert out["operational_ready"] == 9
    assert out["review_required"] == 0
    assert out["revoked"] == 1
    assert out["false_success"] == {
        "audited": 10, "flagged": 1, "flagged_tasks": [withdrawn]}
    rows = {row["task_id"]: row for row in out["per_task"]}
    assert rows[withdrawn]["historical_tool_ready"] is True
    assert rows[withdrawn]["operational_status"] == "REVOKED"


def test_release_ledger_is_append_only_folded_and_malformed_rows_fail(tmp_path):
    m = _mod()
    ledger = tmp_path / "release.jsonl"
    ledger.write_text(
        json.dumps(_release_decision(
            "tool-a-v1", "REVOKED", evidence_sha256="a" * 64)) + "\n"
        + json.dumps(_release_decision(
            "tool-a-v1", "ACTIVE", evidence_sha256="b" * 64)) + "\n",
        encoding="utf-8")
    assert {
        tool: row["decision"]
        for tool, row in m._release_decisions(ledger).items()
    } == {"a": "ACTIVE"}

    ledger.write_text(
        json.dumps(_release_decision("tool-a-v1", "UNKNOWN")) + "\n",
        encoding="utf-8")
    try:
        m._release_decisions(ledger)
    except RuntimeError as exc:
        assert "只允许" in str(exc)
    else:
        raise AssertionError("损坏运营决策行不得被静默忽略")

    ledger.write_text(
        json.dumps({"task_id": "tool-a-v1", "decision": "ACTIVE"}) + "\n",
        encoding="utf-8")
    try:
        m._release_decisions(ledger)
    except RuntimeError as exc:
        assert "缺字段" in str(exc)
    else:
        raise AssertionError("指标出口必须复用完整 release schema 校验")


def test_metrics_fold_current_release_by_tool_and_task_version(tmp_path):
    root, tasks, dest = _world(tmp_path)
    (dest / ".repoproof-registry.json").write_text(json.dumps({
        "schema_version": 1,
        "tools": {
            "a": {
                "path": str(dest / "a"),
                "task_id": "tool-a-v2",
                "run_id": "run-a-v2",
                "verdict": "VERIFIED_TOOL_READY",
                "previous_versions": [{
                    "task_id": "tool-a-v1",
                    "run_id": "run-a",
                    "contract_sha256": "a" * 64,
                    "archive_path": ".repoproof-versions/a/tool-a-v1--synthetic",
                    "historical_verdict": "VERIFIED_TOOL_READY",
                }],
            },
        },
    }), encoding="utf-8")
    ledger = dest / ".repoproof-release-decisions.jsonl"
    ledger.write_text(
        json.dumps(_release_decision(
            "tool-a-v1", "ACTIVE", tool="a", evidence_sha256="a" * 64)) + "\n"
        + json.dumps(_release_decision(
            "tool-a-v2", "REVIEW_REQUIRED", tool="a", evidence_sha256="b" * 64)) + "\n",
        encoding="utf-8",
    )

    out = _mod().compute(root, tasks, dest)
    row = next(item for item in out["per_task"] if item["task_id"] == "tool-a-v1")
    assert out["historical_tool_ready"] == 1
    assert out["operational_ready"] == 0
    assert out["review_required"] == 1
    assert row["exported"].endswith("tool-a-v1--synthetic")
    assert row["operational_status"] == "REVIEW_REQUIRED"


def test_metrics_rejects_contradictory_audit_outcome(tmp_path):
    root, tasks, dest = _world(tmp_path)
    audit_path = root / "benchmarks" / "v2" / "m4_audits.jsonl"
    audit_path.write_text(json.dumps({
        "task_id": "tool-a-v1", "ok": False, "verdict": "PASS",
    }) + "\n", encoding="utf-8")

    try:
        _mod().compute(root, tasks, dest)
    except RuntimeError as exc:
        assert "矛盾" in str(exc)
    else:
        raise AssertionError("审计 ok/verdict 矛盾必须 fail-closed")
