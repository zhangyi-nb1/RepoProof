"""集中式中文文案与术语映射 — 页面禁止各自硬编码术语。

分层:
- TERM:内部/英文概念 → 普通用户中文(§四统一术语表)
- VERDICT_SIMPLE / VERDICT_NEXT:最终判定的通俗结论与下一步
- ADMISSION:向导适用性检查四态(纯 UI 输入校验,非 Core 判定)
- STAGES_SIMPLE:运行阶段的通俗九段
- ERROR_TEXT:错误三段式(发生了什么/为何影响/下一步)
- FAILED_NODE_HINTS:未通过测试节点 → 通俗解释

内部枚举一律保持原值,仅改变显示;技术模式在中文旁附原文。
"""

from __future__ import annotations

from repoproof.ui.presenters.zh import (  # noqa: F401 — 复用既有映射
    AGENT_EXIT_ZH,
    OWNER_ZH,
    RUN_TYPE_ZH,
    VERDICT_ZH,
    agent_exit_zh,
    dash,
    failure_owner_zh,
    replay_mode_zh,
    run_type_zh,
    verdict_zh,
)

# ---- §四 统一术语(Host Project -> 你的项目 …) ----
TERM = {
    "host_project": "你的项目",
    "upstream_repository": "目标仓库",
    "task_contract": "成功标准",
    "requirement_spec": "功能要求",
    "contract_adequacy_gate": "开始前检查",
    "admission": "适用性检查",
    "agent": "AI 开发助手",
    "harness": "运行保障机制",
    "oracle": "最终验收测试",
    "held_out_tests": "未向 AI 展示的独立测试",
    "adapter": "适配代码",
    "artifact": "结果文件",
    "trace": "执行记录",
    "completion_gate": "最终判定",
    "clean_replay": "换一个干净环境再验证",
    "policy": "操作规则检查",
    "host_regression": "原项目是否受影响",
    "capability_verification": "目标功能是否可用",
    "adoption_bundle": "可复核结果包",
    "patch_budget": "修改范围上限",
    "token_budget": "AI 使用额度",
    "provider_admission": "模型连接检查",
}

# ---- §八 Verdict:通俗结论 + 下一步 ----
VERDICT_SIMPLE = {
    "PASS_DIRECT": "无需修改,可直接使用",
    "PASS_ADAPTED": "适配后可使用",
    "READY_FOR_REPLAY": "功能已通过,正在复测",
    "PARTIAL": "部分可用",
    "BLOCKED": "缺少条件,暂时无法继续",
    "FAIL": "当前条件下不建议采用",
    "INVALID_TASK_SPEC": "成功标准还不够清楚",
}

VERDICT_ICON = {
    "PASS_DIRECT": "✅", "PASS_ADAPTED": "✅", "READY_FOR_REPLAY": "🟡",
    "PARTIAL": "🟡", "BLOCKED": "🟡", "FAIL": "❌", "INVALID_TASK_SPEC": "🟡",
}

VERDICT_NEXT = {
    "PASS_ADAPTED": "下载可复核结果包,把适配代码合入你的项目;合入前建议先读一遍 AI 的修改。",
    "PASS_DIRECT": "无需适配代码,按目标仓库文档直接安装使用即可。",
    "FAIL": "查看下方「哪些问题没解决」;可以补全成功标准或更换目标仓库后再试。",
    "BLOCKED": "先解决缺少的外部条件(如模型连接、运行环境),然后重新开始。",
    "PARTIAL": "查看已通过与未通过的部分,决定是否接受部分能力。",
    "INVALID_TASK_SPEC": "回到「开始新任务」,把想实现的功能与成功标准补充完整。",
    "READY_FOR_REPLAY": "等待干净环境复测完成,再查看最终结论。",
}


def verdict_simple(v: str | None) -> str:
    return VERDICT_SIMPLE.get(v or "", v or "—")


def verdict_icon(v: str | None) -> str:
    return VERDICT_ICON.get(v or "", "🟡")


def verdict_next(v: str | None) -> str:
    return VERDICT_NEXT.get(v or "", "查看技术详情了解更多。")


# ---- 四项通俗检查(结果页固定顺序) ----
FOUR_CHECKS = [
    ("capability", "目标功能是否可用", TERM["capability_verification"]),
    ("regression", "原项目是否正常", TERM["host_regression"]),
    ("policy", "操作是否符合规则", TERM["policy"]),
    ("replay", "新环境中是否还能运行", TERM["clean_replay"]),
]

# ---- AI 助手状态(通俗版;技术模式再附英文原值) ----
AGENT_EXIT_SIMPLE = {
    "Submitted": "AI 助手已提交",
    "LimitsExceeded": "AI 使用额度已用完",
    "ProviderUnavailable": "模型服务连不上",
    "PolicyTerminated": "因违反操作规则被终止",
    "UserCancelled": "你请求了停止",
    "RuntimeError": "运行出现异常",
}


def agent_exit_simple(v: str | None) -> str:
    return AGENT_EXIT_SIMPLE.get(v or "", v or "—")


# ---- §七 运行阶段(通俗九段) ----
STAGES_SIMPLE = [
    "理解项目",
    "分析目标仓库",
    "准备适配方案",
    "AI 正在修改",
    "正在运行测试",
    "正在修复问题",
    "正在进行最终验收",
    "正在干净环境复测",
    "完成",
]

# ---- §六 适用性检查四态(向导用;纯输入校验,非 Core 判定) ----
ADMISSION = {
    "READY": {"icon": "✅", "title": "可以开始尝试适配"},
    "NEED_INFO": {"icon": "🟡", "title": "还需要补充一些信息"},
    "UNSUPPORTED": {"icon": "❌", "title": "当前版本暂不支持"},
    "RISK_REVIEW": {"icon": "🟡", "title": "存在风险,需要你确认"},
}

# ---- §九 错误三段式:code -> (发生了什么, 为什么影响任务, 下一步) ----
ERROR_TEXT = {
    "INVALID_TASK_SPEC": (
        "成功标准还不够清楚",
        "验收规则有缺口时,AI 的产物无法被公平判定,结果不可信",
        "回到「开始新任务」补全想实现的功能和成功标准,再重新检查",
    ),
    "PROVIDER_UNAVAILABLE": (
        "模型服务连不上",
        "没有可用的 AI 模型连接,任务无法开始(不会消耗任何额度)",
        "检查网络与模型配置(系统设置),稍后重试;不会自动更换模型",
    ),
    "CAPABILITY_MISMATCH": (
        "目标功能测试未全部通过",
        "目标功能没有完全达到成功标准,合入你的项目可能出错",
        "查看未通过的检查项,决定补全标准、调整目标或放弃采用",
    ),
    "BUDGET_EXHAUSTED": (
        "AI 使用额度已用完",
        "在额度内没有完成全部目标,本次结果按未完成计",
        "查看已完成的部分;如需继续,请在新任务中调整目标范围",
    ),
    "POLICY_VIOLATION": (
        "出现了不符合操作规则的动作",
        "为保护你的项目,越界操作会被拒绝并记录",
        "查看执行记录中的被拒动作;通常无需处理,系统已拦截",
    ),
}


def error_text(code: str | None) -> tuple[str, str, str]:
    return ERROR_TEXT.get(
        code or "",
        ("出现了一个未分类的问题", "该问题影响了本次任务的正常完成", "展开技术详情查看原始信息,或重新开始任务"),
    )


# ---- 未通过测试节点 → 通俗解释(按子串匹配) ----
FAILED_NODE_HINTS = [
    ("upstream_errors_wrapped", "遇到异常输入时,没有按要求包装错误(程序可能直接崩溃)"),
    ("malformed_request", "对格式错误的输入没有按要求给出稳定报错"),
    ("rankings_match", "排序打分结果与目标仓库的真实算法不一致(AI 自己实现了近似逻辑)"),
    ("records_match", "输出内容与目标仓库的真实解析结果不一致"),
    ("unfenced_document", "对边界格式文档的处理与目标仓库行为不一致"),
    ("truth_table", "布尔标记的取值与公开真值表不一致"),
    ("order", "输出顺序与输入顺序不一致"),
    ("schema", "输出字段与约定的格式不一致"),
]


def failed_node_hint(node: str) -> str:
    for key, hint in FAILED_NODE_HINTS:
        if key in node:
            return hint
    return "该项验收测试未通过(展开技术详情查看原始名称)"
