"""中文展示映射 — UI 只翻译措辞,绝不改变 Core 的判定语义。"""

from __future__ import annotations

VERDICT_ZH = {
    "PASS_DIRECT": "直接采用通过",
    "PASS_ADAPTED": "适配后通过",
    "READY_FOR_REPLAY": "待干净重放",
    "PARTIAL": "部分目标完成",
    "BLOCKED": "外部条件阻塞",
    "FAIL": "未满足采用合同",
    "INVALID_TASK_SPEC": "任务规格不充分",
}

AGENT_EXIT_ZH = {
    "Submitted": "Agent 主动提交",
    "LimitsExceeded": "Agent 预算耗尽",
    "ProviderUnavailable": "模型服务不可用",
    "PolicyTerminated": "违反策略后终止",
    "UserCancelled": "用户请求停止",
    "RuntimeError": "运行异常",
}

STAGE_ZH = {
    "DRAFT": "草稿",
    "READY_TO_FREEZE": "可冻结",
    "ADMISSION": "准入检查",
    "AGENT_RUNNING": "Agent 执行中",
    "FREEZING": "产物冻结中",
    "VERIFYING": "独立验证中",
    "REPLAYING": "干净重放中",
    "COMPLETED": "已完成",
}

RUN_TYPE_ZH = {
    "direct_baseline": "直连基线(无 Agent)",
    "real_agent": "真实 Agent",
    "ablation": "行为消融实验",
    "corrected_spec_positive": "修正规格正例",
}

REPLAY_MODE_ZH = {
    "clean_adoption": "干净采用重放",
    "baseline_failure_reproduction": "失败复现重放",
}

# 失败类型 → 主要责任方(与 docs/FAILURE_TAXONOMY.md 的归因一致)
FAILURE_OWNER = {
    "CONTRACT_REQUIREMENT_OMISSION": "AGENT_ADAPTER",
    "SEMANTIC_SUBSTITUTION": "AGENT_ADAPTER",
    "BUDGET_EXHAUSTED": "AGENT_ADAPTER",
    "HARNESS_SIGNAL_IGNORED": "AGENT_ADAPTER",
    "BUILD_METADATA_INCOMPATIBILITY": "UPSTREAM",
    "TASK_SPECIFIC_HARDCODE": "HARNESS",
    "PROVIDER_UNAVAILABLE": "PROVIDER",
    "HARNESS_PROMPT_CONTAMINATION": "HARNESS",
    "CONTRACT_UNDERSPECIFICATION": "TASK_AUTHOR",
}

OWNER_ZH = {
    "TASK_AUTHOR": "任务作者",
    "HOST_INPUT_GUARD": "宿主输入守卫",
    "AGENT_ADAPTER": "Agent 适配器",
    "HARNESS": "Harness",
    "UPSTREAM": "上游仓库",
    "PROVIDER": "模型服务商",
}


def verdict_zh(v: str | None) -> str:
    return VERDICT_ZH.get(v or "", v or "—")


def agent_exit_zh(v: str | None) -> str:
    return AGENT_EXIT_ZH.get(v or "", v or "—")


def run_type_zh(v: str | None) -> str:
    return RUN_TYPE_ZH.get(v or "", v or "—")


def replay_mode_zh(v: str | None) -> str:
    return REPLAY_MODE_ZH.get(v or "", v or "—")


def failure_owner_zh(failure_type: str | None) -> str:
    if not failure_type:
        return "—"
    # 复合类型(如 "A + B")逐个归因
    owners = []
    for part in failure_type.split("+"):
        owner = FAILURE_OWNER.get(part.strip())
        if owner and OWNER_ZH[owner] not in owners:
            owners.append(OWNER_ZH[owner])
    return " + ".join(owners) if owners else "—"


def dash(v) -> str:
    """缺失数据显示为 — ,绝不推断。"""
    return "—" if v is None or v == "" else str(v)
