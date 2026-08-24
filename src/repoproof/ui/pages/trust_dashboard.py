"""Product metrics and trust dashboard."""

from __future__ import annotations

import streamlit as st

from repoproof.ui.product_theme import apply_product_theme, hero, section_intro
from repoproof.ui.services.product_mode import dashboard_snapshot

st.set_page_config(page_title="可信仪表盘 · RepoProof Studio", page_icon="📊", layout="wide")
apply_product_theme()

snapshot = dashboard_snapshot()
metrics = snapshot["metrics"]
ops = snapshot["operational"]
reason_codes = snapshot["operational_reason_codes"]

hero(
    "成功率不是唯一答案",
    "RepoProof 同时报告任务接受率、历史 READY、干净重放、当前运营可用和误放行。拒绝不适合的任务，也是产品价值。",
    kicker="Trust & operations dashboard",
)

section_intro("本机运营状态", "这些数字来自工具注册表和 append-only 发布状态账。")
for projection_error in snapshot["projection_errors"]:
    st.error(
        f"{projection_error['reason_code']}：Core 事实源无法验证，"
        "运营投影已 fail closed。"
    )
c1, c2, c3, c4 = st.columns(4)
c1.metric("ACTIVE", ops.get("ACTIVE", 0), help="通过 fresh-input 审核，可继续使用和暴露 MCP")
c2.metric("待审核", ops.get("REVIEW_REQUIRED", 0), help="历史验证不等于当前运营批准")
c3.metric("已撤回", ops.get("REVOKED", 0), help="保留历史证据，但停止继续暴露")
c4.metric("历史验证", snapshot["historically_verified"], help="当时冻结合同下的不可改写事实")

st.write("")
section_intro(
    "最近一次真实仓批次",
    "接受率与 Tool Ready Rate 必须成对阅读；这些是内部 alpha 的已记录案例结果，"
    "不能外推为任意仓库成功率。",
)
b1, b2, b3, b4 = st.columns(4)
b1.metric("提交仓库", metrics.get("submitted", "—"))
b2.metric(
    "接受执行", metrics.get("accepted", "—"),
    delta=f"{metrics.get('acceptance_rate', 0):.1%}" if metrics else None,
)
b3.metric(
    "历史 READY", metrics.get("tool_ready", "—"),
    delta=f"{metrics.get('tool_ready_rate', 0):.1%}" if metrics else None,
)
b4.metric("干净重放", metrics.get("replay_success", "—"), delta=f"审计误放行 {snapshot['false_success']}")

left, right = st.columns([1, 1])
with left:
    st.markdown("#### 运营状态分布")
    st.bar_chart(
        {
            "状态": ["可使用", "待审核", "已撤回", "未验证"],
            "数量": [
                ops.get("ACTIVE", 0), ops.get("REVIEW_REQUIRED", 0),
                ops.get("REVOKED", 0), ops.get("UNVERIFIED", 0),
            ],
        },
        x="状态",
        y="数量",
        horizontal=True,
    )
with right:
    st.markdown("#### 当前状态原因码")
    if reason_codes:
        st.dataframe(
            [
                {"reason_code": code, "工具数": count}
                for code, count in reason_codes.items()
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("当前没有可投影的运营原因码。")

st.markdown("#### 漏斗事实")
st.bar_chart(
    {
        "阶段": ["Submitted", "Accepted", "Historical READY", "Replay"],
        "数量": [
            metrics.get("submitted", 0), metrics.get("accepted", 0),
            metrics.get("tool_ready", 0), metrics.get("replay_success", 0),
        ],
    },
    x="阶段",
    y="数量",
    horizontal=True,
)

st.markdown("#### 为什么保留两种 READY")
st.info(
    "历史验证回答“某次冻结合同下是否通过”；运营状态回答“今天是否仍允许继续使用”。"
    "撤回不会篡改历史 PASS，历史 PASS 也不能绕过当前撤回。"
)

false = metrics.get("false_success") or {}
if false.get("flagged"):
    st.error(
        f"已审计 {false.get('audited', 0)} 个历史 READY，发现 {false.get('flagged', 0)} 个误放行。"
        f"涉及：{', '.join(false.get('flagged_tasks') or [])}。"
    )

# 逐任务结果的人读主呈现：这些信息此前只存在于机器事实 JSON 深处,
# 普通用户想查"某个仓最后怎么样了"只能钻 JSON(M6 预览验证实录)。
per_task = metrics.get("per_task") or []
if per_task:
    st.markdown("#### 逐任务结果")

    def _mark(v: object) -> str:
        return "✅" if v else "✖"

    st.dataframe(
        [
            {
                "任务": row.get("task_id") or "—",
                "仓库": (row.get("repo") or "—").removeprefix("https://github.com/"),
                "能力": row.get("capability") or "—",
                "接受执行": _mark(row.get("accepted")),
                "历史 READY": _mark(row.get("historical_tool_ready", row.get("tool_ready"))),
                "干净重放": _mark(row.get("replay")),
                "当前运营": row.get("operational_status") or "—",
                "真发结论": row.get("real_verdict") or "—",
            }
            for row in per_task
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.caption("接受执行=通过准入闸；历史 READY=当时冻结合同下的流水线结论（不可改写）；当前运营=今天是否仍允许使用。")

with st.expander("查看机器事实（原始 JSON，供审计复核；上方表格已含同一信息的人读版）"):
    st.json(
        {
            "recorded_m4_metrics": metrics,
            "operational_reason_codes": reason_codes,
            "projection_errors": snapshot["projection_errors"],
        }
        if metrics or reason_codes or snapshot["projection_errors"]
        else {"note": "当前没有可读取的批次指标或运营投影"}
    )
