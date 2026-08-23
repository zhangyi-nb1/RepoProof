"""M4 指标脚本的自证([G4] · 数字只出自一个脚本,脚本先证明自己算得对)。

合成世界喂正反例:未冻结(无 sidecar)不算 accepted;fake 发不算真发;
真发 FAIL 不算 ready;导出+PASS 才 ready;replay/audit 各自归位;
成对语义标注必须在输出里(防单引 tool_ready_rate)。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


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
         "verdict": "FAIL"},                                    # fake 不算
        {"task_id": "tool-a-v1", "model": "gpt-5.5", "verdict": "PASS_ADAPTED"},
        {"task_id": "tool-b-v1", "model": "gpt-5.5", "verdict": "FAIL"},
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
    assert out["tool_ready_rate"] == 0.5
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
