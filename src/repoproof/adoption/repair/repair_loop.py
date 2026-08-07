"""Guided Repair Loop(RFC-006)— 有界多轮修复编排。

产品模式(Benchmark 模式仍是单次运行,互不影响)。同一个
mini-swe-agent DefaultAgent 顺序调用(run_round 注入),不引入第二个
Agent。循环产出 RepairOutcome——**没有 verdict 字段**:即使全部公开
测试通过,也只是 completed_all_pass;最终结论必须走既有
Freeze → Capability → Regression → Policy → Clean Replay →
Completion Gate,循环永不宣布成功。
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel

from repoproof.adoption.repair.failure_packet import FailurePacket, build_failure_packets
from repoproof.adoption.repair.repair_budget import RepairBudget

STOP_ALL_PUBLIC_PASS = "all_public_green_pending_verification"  # ≠ 成功;还需隐藏验证
STOP_MAX_ROUNDS = "max_rounds"
STOP_BUDGET = "budget_exhausted"
STOP_STAGNATION = "stagnation"
STOP_SCOPE_CHANGE = "scope_change_pending_user"


class RoundResult(BaseModel):
    """一轮 Agent 修改后的可观测结果(由 run_round 提供)。"""

    adapter_snapshot: str
    passed: int
    failed_nodes: list[str] = []
    failure_details: dict[str, str] = {}
    diff_lines: int = 0
    tokens_used: int = 0
    commands_used: int = 0
    scope_change_request: str | None = None


class Checkpoint(BaseModel):
    round_index: int
    adapter_snapshot: str
    passed: int
    failed_nodes: list[str]
    diff_lines: int


class RepairOutcome(BaseModel):
    rounds_run: int
    best_round: int
    best_passed: int
    final_adapter: str
    stop_reason: str
    rolled_back_rounds: list[int] = []
    checkpoints: list[Checkpoint] = []
    pending_scope_change: str | None = None
    note: str = "循环不产生最终结论;必须继续走冻结+独立验证+干净重放+最终判定"

    def to_dict(self) -> dict:
        return self.model_dump()


class RepairLoop:
    def __init__(
        self,
        run_round: Callable[[int, list[FailurePacket], str | None], RoundResult],
        *,
        budget: RepairBudget | None = None,
    ) -> None:
        self._run_round = run_round
        self._budget = budget or RepairBudget()

    def run(self) -> RepairOutcome:
        budget = self._budget
        checkpoints: list[Checkpoint] = []
        rolled_back: list[int] = []
        best: Checkpoint | None = None
        packets: list[FailurePacket] = []
        tokens = commands = 0
        stop = STOP_MAX_ROUNDS
        no_improve_streak = 0
        pending_scope: str | None = None

        if budget.max_rounds < 1:
            raise ValueError("max_rounds 必须 >= 1")
        for i in range(budget.max_rounds):
            # F3: 把当前最佳快照传给执行方——回滚后从最佳状态继续
            result = self._run_round(i + 1, packets, best.adapter_snapshot if best else None)
            tokens += result.tokens_used
            commands += result.commands_used
            cp = Checkpoint(
                round_index=i + 1,
                adapter_snapshot=result.adapter_snapshot,
                passed=result.passed,
                failed_nodes=list(result.failed_nodes),
                diff_lines=result.diff_lines,
            )
            checkpoints.append(cp)

            # Scope Change Gate:暂停等用户,绝不自行继续
            if result.scope_change_request:
                pending_scope = result.scope_change_request
                if best is None or cp.passed > best.passed:  # F8: 平手保留更早的最佳
                    best = cp
                stop = STOP_SCOPE_CHANGE
                break

            # Best state / rollback:劣化则回滚到最佳
            if best is None or cp.passed > best.passed:
                best = cp
                no_improve_streak = 0
            else:
                if cp.passed < best.passed:
                    rolled_back.append(cp.round_index)
                no_improve_streak += 1

            # F2: 空 failed_nodes 不等于全绿——必须真的比历史最佳更好且非零
            if not result.failed_nodes and cp.passed > 0 and cp.passed >= best.passed:
                stop = STOP_ALL_PUBLIC_PASS
                break

            # Stagnation:连续两轮无改善
            if no_improve_streak >= 2:
                stop = STOP_STAGNATION
                break

            reason = budget.exceeded(
                rounds=i + 1, tokens=tokens, commands=commands, diff_lines=cp.diff_lines
            )
            if reason:
                stop = STOP_BUDGET if i + 1 < budget.max_rounds else STOP_MAX_ROUNDS
                if "max_rounds" in reason:
                    stop = STOP_MAX_ROUNDS
                break

            # F3: 回滚发生时,下一轮的失败包基于被恢复的最佳状态,而非被丢弃的劣化轮
            src_cp = best if cp.round_index in rolled_back else cp
            packets = build_failure_packets(src_cp.failed_nodes, result.failure_details)

        if best is None:  # F9: 显式错误,不依赖 assert
            raise RuntimeError("repair loop ended without any round result")
        return RepairOutcome(
            rounds_run=len(checkpoints),
            best_round=best.round_index,
            best_passed=best.passed,
            final_adapter=best.adapter_snapshot,
            stop_reason=stop,
            rolled_back_rounds=rolled_back,
            checkpoints=checkpoints,
            pending_scope_change=pending_scope,
        )
