"""Product Mode landing page."""

from __future__ import annotations

import streamlit as st

from repoproof.ui.product_theme import (
    apply_product_theme,
    flow_step,
    hero,
    metric_card,
    section_intro,
)
from repoproof.ui.services.product_mode import dashboard_snapshot, status_label

st.set_page_config(page_title="RepoProof Studio", page_icon="🏠", layout="wide")
apply_product_theme()

snapshot = dashboard_snapshot()
metrics = snapshot["metrics"]

hero(
    "把 GitHub 能力，变成你真正敢用的本地工具",
    "描述一个能力，确认成功标准，然后交给 RepoProof 构建、独立验证、干净重放并加入你的工具库。"
    "AI 说完成不算，证据和当前发布状态才算。",
    kicker="GitHub Capability → Verified Local Tool",
)
st.caption(
    "当前为受支持范围内的内部 alpha：公开 Python、单一明确能力、本地 CPU。"
    "下方批次数字是已记录案例结果，不代表任意 GitHub 仓库的成功率。"
)

left, right, _ = st.columns([1.05, 1, 2.2])
if left.button("＋ 新建本地工具", type="primary", use_container_width=True):
    st.switch_page("pages/tool_onboarding.py")
if right.button("打开工具库", use_container_width=True):
    st.switch_page("pages/tool_library.py")

st.write("")
cards = st.columns(4)
with cards[0]:
    metric_card("已登记工具", str(snapshot["installed"]), "这台机器上的本地工具包")
with cards[1]:
    metric_card("历史验证通过", str(snapshot["historically_verified"]), "保留当时冻结合同下的结论")
with cards[2]:
    metric_card("当前可使用", str(snapshot["operational"].get("ACTIVE", 0)), "通过新鲜输入审核的 ACTIVE 工具")
with cards[3]:
    metric_card("误放行发现", str(snapshot["false_success"]), "审计发现并保留的 false-success")

if snapshot["registry_error"]:
    st.error("本地工具索引无法读取。系统没有猜测工具状态，请先修复索引后再操作。")
if snapshot["release_error"]:
    st.error("运营状态账存在损坏行；当前不提供任何可操作工具，不会静默放行。")
elif snapshot["historically_verified"] and not snapshot["release_ledger_present"]:
    st.warning(
        "历史工具已经验证，但新的运营状态账尚未迁移。当前统一显示为“待审核”；"
        "这不会改写历史结论，也不会把未审核工具暴露给 Agent。"
    )

st.write("")
section_intro("一条清晰的五步旅程", "普通用户只在关键决策点确认，复杂执行和证据收集由系统处理。")
flow = st.columns(5)
steps = [
    ("发现", "粘贴公开 GitHub 仓库，描述你真正想要的单一能力。"),
    ("确认", "审阅输入输出、样例、依赖版本和不能接受的行为。"),
    ("构建", "Agent 在隔离环境里包装能力，不能修改验收规则。"),
    ("证明", "独立测试、上游回执和干净重放重新挣得结论。"),
    ("使用", "通过新输入抽查后即可上架：命令行直接用，或一键接入 AI 助手（MCP）。"),
]
for idx, (title, body) in enumerate(steps, 1):
    with flow[idx - 1]:
        flow_step(idx, title, body)

st.write("")
section_intro("最近的工具", "这里同时显示历史验证和当前运营状态，两者永不互相覆盖。")
tools = snapshot["tools"]
if not tools:
    st.info("工具库还是空的。创建第一个工具后，它会出现在这里。")
else:
    recent = tools[-6:][::-1]
    st.dataframe(
        [
            {
                "工具": row["name"],
                "能力": row["summary"] or "—",
                "历史验证": row["historical_verdict"] or "—",
                "当前状态": status_label(row["operational_status"]),
                "包健康": row["health"],
            }
            for row in recent
        ],
        hide_index=True,
        use_container_width=True,
    )

st.caption(
    f"工具根目录：{snapshot['root']} · 批量记录："
    f"{metrics.get('submitted', 0)} submitted / {metrics.get('accepted', 0)} accepted / "
    f"{metrics.get('tool_ready', 0)} historical READY"
)
