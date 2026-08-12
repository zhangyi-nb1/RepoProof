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

from repoproof.adoption.repair.failure_packet import (
    ROLLBACK,
    FailurePacket,
    build_failure_packets,
)
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
    # RFC-008 §11.3 排序输入(默认值 = 与旧行为等价)
    collected_ok: bool = True        # 测试是否成功收集(崩溃轮不算成功)
    policy_violations: int = 0       # 本轮策略拒绝数(**本轮增量**,不是累计)
    regression_failed: int = 0       # 宿主回归失败数
    within_budget: bool = True       # 本轮未超 Patch/Token/Command 预算
    # 约束反馈(LESSONS #33)。violation_packets:本轮违规的结构化说明,
    # 随失败包一起进下一轮提示。fatal_violations:最终闸门必杀的违规名
    # (patch 超限/依赖不可解析)——非空时全绿也不许停轮,留轮修剪。
    violation_packets: list[FailurePacket] = []
    fatal_violations: list[str] = []


class Checkpoint(BaseModel):
    round_index: int
    adapter_snapshot: str
    passed: int
    failed_nodes: list[str]
    diff_lines: int
    score: list[float] = []          # score_fn 结果;比较用字典序
    # H4(LESSONS #33):回滚后下一轮的失败包必须配**该快照自己**的断言
    # 细节与违规包——060126 实录是 best 的 failed_nodes 配劣化轮的空
    # details,agent 收到 9 个"该检查项断言失败"的空壳。
    failure_details: dict[str, str] = {}
    violation_packets: list[FailurePacket] = []


def full_score(r: RoundResult) -> list[float]:
    """RFC-008 §11.3 完整排序(高者优):
    收集成功 → 无策略违规 → 回归未破坏 → (hard=)公开通过数 →
    公开通过数 → 预算内 → 更小 diff。禁止只按通过数排。"""
    return [
        1.0 if r.collected_ok else 0.0,
        1.0 if r.policy_violations == 0 else 0.0,
        1.0 if r.regression_failed == 0 else 0.0,
        float(r.passed),
        float(r.passed),
        1.0 if r.within_budget else 0.0,
        -float(r.diff_lines),
    ]


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
        score_fn: Callable[[RoundResult], list[float]] | None = None,
    ) -> None:
        self._run_round = run_round
        self._budget = budget or RepairBudget()
        # 默认 = 旧行为(只看通过数);产品模式传 full_score(§11.3)
        self._score = score_fn or (lambda r: [float(r.passed)])

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
                score=list(self._score(result)),
                failure_details=dict(result.failure_details),
                violation_packets=list(result.violation_packets),
            )
            checkpoints.append(cp)

            # Scope Change Gate:暂停等用户,绝不自行继续
            if result.scope_change_request:
                pending_scope = result.scope_change_request
                if best is None or cp.score > best.score:  # F8: 平手保留更早的最佳
                    best = cp
                stop = STOP_SCOPE_CHANGE
                break

            # Best state / rollback:劣化则回滚到最佳(§11.3 字典序,非纯通过数)
            if best is None or cp.score > best.score:
                best = cp
                no_improve_streak = 0
            else:
                if cp.score < best.score:
                    rolled_back.append(cp.round_index)
                no_improve_streak += 1

            # F2: 空 failed_nodes 不等于全绿——必须收集成功、非零且不劣于历史最佳。
            # H3(LESSONS #33):还挂着最终闸门必杀的违规时禁止"全绿即停"
            # ——061522/181550/054108 实录都是第 1 轮全绿盖棺、剩余轮次
            # 全弃、终局被政策/重放击杀;留轮修剪,fatal 清零才许停。
            if (not result.failed_nodes and result.collected_ok
                    and cp.passed > 0 and cp.score >= best.score
                    and not result.fatal_violations):
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

            # F3: 回滚发生时,下一轮的失败包基于被恢复的最佳状态,而非被丢弃的劣化轮。
            # H4:细节取 src_cp **自己**存的(修复 060126 的错位:best 的
            # failed_nodes 配劣化轮的空 details);违规包随行;回滚必须说明。
            src_cp = best if cp.round_index in rolled_back else cp
            packets = build_failure_packets(src_cp.failed_nodes, src_cp.failure_details)
            packets = packets + list(src_cp.violation_packets)
            if cp.round_index in rolled_back:
                cause_bits = [f"passed {cp.passed} vs best {best.passed}"]
                if result.regression_failed:
                    cause_bits.append(f"regression_failed {result.regression_failed}")
                if result.policy_violations:
                    cause_bits.append(f"policy_violations {result.policy_violations}")
                cause_bits.extend(p.summary for p in cp.violation_packets)
                packets.append(FailurePacket(
                    type=ROLLBACK,
                    summary=(f"your round-{cp.round_index} changes were ROLLED BACK; "
                             f"the working tree is round {best.round_index}'s "
                             "snapshot again"),
                    expected=(f"improve on round {best.round_index} without new "
                              "violations or regressions"),
                    actual="; ".join(cause_bits),
                    suggestion="不要原样重做被回滚的改动——先消掉导致回滚的违规/"
                               "回归,再在恢复的最佳状态上继续改进",
                ))

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
