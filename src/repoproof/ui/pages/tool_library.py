"""Installed Local Tool library and operational controls."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from repoproof.ui.product_theme import apply_product_theme, hero, section_intro, status_badge
from repoproof.ui.services import live_run
from repoproof.ui.services.product_mode import (
    list_tools,
    mcp_command,
    status_label,
    tool_command,
)

st.set_page_config(page_title="工具库 · RepoProof Studio", page_icon="🧩", layout="wide")
apply_product_theme()

hero(
    "你的本地 AI Tool Library",
    "每个工具都保留来源、固定版本、历史验证和当前运营状态。历史 PASS 不会因为撤回而消失，撤回也不会被历史 PASS 覆盖。",
    kicker="Local tool registry",
)

library = list_tools()
tools = library["tools"]
if library["registry_error"]:
    st.error("注册表无法读取，系统拒绝猜测。请先修复注册表。")
if library["release_error"]:
    st.error("运营状态账损坏；所有工具按待审核处理。")

section_intro("工具清单", "先按当前状态筛选，再打开一个工具查看调用方式和证据。")
statuses = ["ACTIVE", "REVIEW_REQUIRED", "REVOKED", "UNVERIFIED"]
selected_status = st.multiselect(
    "当前状态",
    statuses,
    default=statuses,
    format_func=status_label,
)
query = st.text_input("搜索工具或能力", placeholder="例如 PDF、Markdown、中文分词")
filtered = [
    row for row in tools
    if row["operational_status"] in selected_status
    and (not query.strip() or query.lower() in (row["name"] + " " + row["summary"]).lower())
]

if not filtered:
    st.info("没有符合筛选条件的工具。")
    st.stop()

st.dataframe(
    [
        {
            "工具": row["name"],
            "能力": row["summary"] or "—",
            "当前状态": status_label(row["operational_status"]),
            "历史验证": row["historical_verdict"] or "—",
            "包健康": row["health"],
            "上游": row["source_distribution"] or "—",
        }
        for row in filtered
    ],
    hide_index=True,
    use_container_width=True,
)

name = st.selectbox("查看工具详情", [row["name"] for row in filtered])
tool = next(row for row in filtered if row["name"] == name)
st.markdown(f"### {tool['name']} &nbsp; {status_badge(tool['operational_status'])}", unsafe_allow_html=True)
st.write(tool["summary"] or "尚无摘要。")

facts, usage = st.columns([1.15, 1])
with facts:
    st.markdown("#### 可信状态")
    st.write(f"**历史验证：** {tool['historical_verdict'] or '—'}")
    st.write(f"**当前运营：** {status_label(tool['operational_status'])}")
    st.write(f"**包健康：** {tool['health']}")
    st.write(f"**上游：** {tool['source_url'] or '—'}")
    st.write(f"**固定版本：** `{(tool['resolved_commit'] or '—')[:16]}`")
    if tool.get("operational_reason"):
        st.caption(f"最近决定：{tool['operational_reason']}")
with usage:
    st.markdown("#### 使用方式")
    st.code(tool_command(tool["name"]), language="bash")
    st.code(mcp_command(tool["name"]), language="bash")
    if tool["operational_status"] == "ACTIVE":
        if st.button("生成 MCP 适配器", type="primary"):
            result = live_run.start_tool_mcp(tool["name"], Path(library["root"]))
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))
    else:
        st.warning("只有通过 fresh-input 审核的 ACTIVE 工具可以生成或启用 MCP。")

with st.expander("审核、撤回与证据"):
    st.caption("这些操作只追加运营决定，不删除包，也不改写历史验证。M5 核心命令合并后自动启用。")
    available = live_run.product_tool_commands()
    if "audit" in available:
        a, b = st.columns(2)
        audit_input = a.text_input("新鲜输入文件路径", key="audit_input")
        audit_expected = b.text_input("期望输出文件路径", key="audit_expected")
        if st.button("运行 fresh-input 审核", disabled=not (audit_input and audit_expected)):
            result = live_run.start_tool_audit(
                tool["name"], Path(audit_input).expanduser(),
                Path(audit_expected).expanduser(), Path(library["root"]),
            )
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))
    else:
        st.info("当前分支尚未提供 `tool audit`；界面已预留，合并 M5 后启用。")

    if "withdraw" in available:
        reason = st.text_input("撤回原因", key="withdraw_reason")
        if st.button("撤回工具", disabled=not reason):
            result = live_run.start_tool_withdraw(
                tool["name"], reason, Path(library["root"]),
            )
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

    st.write(f"**工具目录：** `{tool['path']}`")
    st.write(f"**运行证据：** `{tool['run_id'] or '—'}`")
    st.write(f"**合同指纹：** `{tool['contract_sha256'] or '—'}`")
