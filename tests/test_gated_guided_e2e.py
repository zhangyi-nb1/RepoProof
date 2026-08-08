"""Gate D — fake-model 多轮 E2E(PREREG-gateD 承诺的机制彩排)。

不调用任何真实模型、不启动 Docker:用 FakeModel 脚本 + 内存假环境
驱动 GuidedRepairRunner 的 run_round 编排逻辑,验证三件事:
1. 多轮确实按 FailurePacket 迭代(第 1 轮 0/N → 第 2 轮全绿);
2. 快照/恢复真实发生(劣化轮被回滚到最佳);
3. 循环永不宣布成功——公开全绿只得到 pending_verification。

默认运行(纯内存,毫秒级);容器级 E2E 仍留给用户的真实运行。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.adoption.repair.failure_packet import build_failure_packets
from repoproof.adoption.repair.repair_budget import RepairBudget
from repoproof.adoption.repair.repair_loop import RepairLoop, RoundResult, full_score
from repoproof.agents.fake_model import FakeModel
from repoproof.runner.guided_repair import (
    render_packets,
    restore_adaptation,
    snapshot_adaptation,
)

PUBLIC_NODES = [
    "public_tests/test_public_contract.py::test_example_1",
    "public_tests/test_public_contract.py::test_example_2",
]


def _fake_public_junit(adapter_src: str) -> dict:
    """假的公开测试:适配代码含 'MAP' 才算实现了样例映射。"""
    passing = "MAP" in adapter_src
    return {
        "junit_present": True,
        "junit_parse_error": None,
        "nodes": [
            {"node_id": n, "outcome": "passed" if passing else "failed",
             "message": "" if passing else "期望包含 '周会纪要',实际: []"}
            for n in PUBLIC_NODES
        ],
    }


def test_guided_e2e_two_rounds_converge_but_never_declare_success(tmp_path: Path) -> None:
    adaptation = tmp_path / "adaptation"
    adaptation.mkdir()
    repair_dir = tmp_path / "repair"
    repair_dir.mkdir()
    # FakeModel 脚本:第 1 轮写空实现,第 2 轮写含 MAP 的实现
    model = FakeModel(script=[
        {"content": "round1", "actions": [{"command": "echo r1"}]},
        {"content": "round2", "actions": [{"command": "echo r2"}]},
    ])
    writes = ["def run(v): return None\n", "MAP = {...}\ndef run(v): return MAP[v]\n"]
    seen_packets: list[list] = []

    def run_round(idx: int, packets, best_snapshot):
        seen_packets.append([p.type for p in packets])
        if best_snapshot:  # 从最佳状态继续(真实恢复)
            restore_adaptation(adaptation, Path(best_snapshot))
        model.query([], )  # 走一次 fake 模型调用(计数真实)
        (adaptation / "adapter.py").write_text(writes[idx - 1], encoding="utf-8")
        snap = repair_dir / f"round-{idx}"
        snapshot_adaptation(adaptation, snap)
        junit = _fake_public_junit(writes[idx - 1])
        nodes = junit["nodes"]
        failed = [n["node_id"] for n in nodes if n["outcome"] != "passed"]
        return RoundResult(
            adapter_snapshot=str(snap),
            passed=sum(1 for n in nodes if n["outcome"] == "passed"),
            failed_nodes=failed,
            failure_details={n["node_id"]: n["message"] for n in nodes if n["message"]},
            diff_lines=len(writes[idx - 1].splitlines()),
            collected_ok=True,
        )

    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=3),
                     score_fn=full_score).run()

    assert out.rounds_run == 2 and out.best_round == 2 and out.best_passed == 2
    # 循环永不宣布成功:全绿只到 pending_verification
    assert out.stop_reason == "all_public_green_pending_verification"
    assert "verdict" not in out.to_dict()
    # 第 2 轮确实收到了第 1 轮的失败包(公开来源)
    assert seen_packets[0] == [] and seen_packets[1], seen_packets
    assert model.calls == 2
    # 最佳快照内容 = 第 2 轮实现
    assert "MAP" in (Path(out.final_adapter) / "adapter.py").read_text(encoding="utf-8")


def test_guided_e2e_regression_round_is_rolled_back(tmp_path: Path) -> None:
    """第 2 轮劣化 → 回滚;第 3 轮从最佳状态继续(适配区内容被真实恢复)。"""
    adaptation = tmp_path / "adaptation"
    adaptation.mkdir()
    repair_dir = tmp_path / "repair"
    repair_dir.mkdir()
    # 第 1 轮部分通过(2/3,未全绿 → 循环继续);第 2 轮劣化(0/3);
    # 第 3 轮应从第 1 轮的最佳状态起步
    bodies = {1: "MAP_PARTIAL\n", 2: "broken\n", 3: "MAP_PARTIAL2\n"}
    passes = {1: 2, 2: 0, 3: 2}
    observed_start: dict[int, str] = {}

    def run_round(idx: int, packets, best_snapshot):
        if best_snapshot:
            restore_adaptation(adaptation, Path(best_snapshot))
        observed_start[idx] = (
            (adaptation / "adapter.py").read_text(encoding="utf-8")
            if (adaptation / "adapter.py").exists() else "")
        (adaptation / "adapter.py").write_text(bodies[idx], encoding="utf-8")
        snap = repair_dir / f"round-{idx}"
        snapshot_adaptation(adaptation, snap)
        return RoundResult(
            adapter_snapshot=str(snap), passed=passes[idx],
            failed_nodes=["public::test_c"],  # 始终有一个未过 → 不会提前全绿停
            failure_details={"public::test_c": "KeyError: missing field"},
            collected_ok=True, diff_lines=1,
        )

    out = RepairLoop(run_round, budget=RepairBudget(max_rounds=3),
                     score_fn=full_score).run()
    assert 2 in out.rolled_back_rounds  # 劣化轮被回滚
    assert out.best_round == 1
    assert "MAP_PARTIAL" in observed_start[3]  # 第 3 轮从最佳状态起步(真实恢复)


def test_packets_rendered_to_agent_are_public_only() -> None:
    junit = _fake_public_junit("def run(v): return None")
    failed = [n["node_id"] for n in junit["nodes"] if n["outcome"] != "passed"]
    details = {n["node_id"]: n["message"] for n in junit["nodes"] if n["message"]}
    text = render_packets(build_failure_packets(failed, details))
    for banned in ("held", "oracle", "Traceback", "reference_records", "verdict"):
        assert banned not in text, banned
