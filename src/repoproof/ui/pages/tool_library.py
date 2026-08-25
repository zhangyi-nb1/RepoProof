"""Installed Local Tool library and operational controls.

文案纪律(M6 两名目标用户实测 P1 后确立):状态/原因/操作的说法一律
「先人话,括号里给术语」,语义唯一来源 = services.product_mode 的
STATUS_EXPLAINERS / REASON_CODE_LABELS / AUDIT_EXPLAINER —— 页面不许
自造术语;「停用(撤回)」入口必须可发现且写明后果。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from repoproof.ui.product_theme import apply_product_theme, hero, section_intro, status_badge
from repoproof.ui.services import product_jobs
from repoproof.ui.services.product_mode import (
    AUDIT_EXPLAINER,
    STATUS_EXPLAINERS,
    list_tools,
    mcp_command,
    reason_label,
    status_label,
    tool_command,
)

st.set_page_config(page_title="工具库 · RepoProof Studio", page_icon="🧩", layout="wide")
apply_product_theme()

hero(
    "你的本地 AI Tool Library",
    "每个工具都保留来源、固定版本、历史验证和当前状态。历史成绩永远保留：停用不会抹掉它，它也不能替代今天的可用性。",
    kicker="Local tool registry",
)

library = list_tools()
tools = library["tools"]
if library["registry_error"]:
    st.error(
        "工具登记表无法通过完整性校验，系统按最保守方式处理：暂不提供任何"
        "可操作工具。（TOOL_REGISTRY_INVALID）"
    )
if library["release_error"]:
    st.error(
        "工具状态账本无法通过完整性校验，系统按最保守方式处理：暂不提供任何"
        "可操作工具。（RELEASE_LEDGER_INVALID）"
    )

section_intro("工具清单", "先按当前状态筛选，再打开一个工具查看用法、状态原因和管理操作。")
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
    st.info(
        "没有符合筛选条件的工具。工具库只收录**成功构建**的工具；"
        "构建失败或未完成的任务不会出现在这里——它们的完整记录"
        "（含失败原因）在「运行活动」页的构建历史里。"
    )
    st.stop()

st.dataframe(
    [
        {
            "工具": row["name"],
            "能力": row["summary"] or "—",
            "当前状态": status_label(row["operational_status"]),
            "状态原因": "; ".join(
                reason_label(c) for c in row.get("reason_codes", [])) or "—",
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
status = tool["operational_status"]
st.markdown(f"### {tool['name']} &nbsp; {status_badge(status)}", unsafe_allow_html=True)
st.write(tool["summary"] or "尚无摘要。")

facts, usage = st.columns([1.15, 1])
with facts:
    st.markdown("#### 可信状态")
    st.write(f"**历史验证：** {tool['historical_verdict'] or '—'}")
    st.caption("历史验证 = 当时通过独立验收的不可改写结论；它不代表今天是否可用。")
    st.write(f"**当前状态：** {status_label(status)}")
    st.caption(STATUS_EXPLAINERS.get(status, ""))
    displayed_reason_codes = tool.get("reason_codes", [])
    if displayed_reason_codes:
        st.write("**状态原因：**")
        for code in displayed_reason_codes:
            label = reason_label(code)
            st.write(f"- {label}（`{code}`）" if label != code
                     else f"- `{code}`（暂无人读说明）")
    st.write(f"**包健康：** {tool['health']}")
    st.write(f"**上游：** {tool['source_url'] or '—'}")
    st.write(f"**固定版本：** `{(tool['resolved_commit'] or '—')[:16]}`")
    if status == "ACTIVE":
        st.caption("想让它下架停用？到下方「管理这个工具」→「停用」。")
with usage:
    st.markdown("#### 使用方式")
    st.code(tool_command(tool["name"]), language="bash")
    st.code(mcp_command(tool["name"]), language="bash")
    # 适配器状态以磁盘为准(Core 事实源),不依赖会话内的按钮反馈——
    # st.success 是单次渲染的瞬态提示,切页/切工具回来就没了,曾让用户
    # 误以为任务被重置、只能去运行历史里确认(M6 预览验证 P1 实录)。
    mcp_server = Path(tool["path"]) / "mcp_server.py"
    if status == "ACTIVE":
        if mcp_server.is_file():
            st.success("AI 助手接入文件已生成（以磁盘为准，切换页面不会丢失）。")
            st.caption(f"`{mcp_server}`")
            button_label = "重新生成 AI 助手接入文件（MCP）"
        else:
            button_label = "生成 AI 助手接入文件（MCP）"
        if st.button(button_label, type="primary"):
            result = product_jobs.start_tool_mcp(tool["name"], Path(library["root"]))
            if result.get("ok"):
                st.rerun()    # 重渲染后由磁盘状态给出常驻"已生成"
            st.error(result.get("error") or result.get("note") or "生成失败")
    elif status == "REVIEW_REQUIRED":
        st.warning(
            "这个工具还不能接入 AI 助手：它还差最后一步——「新输入抽查」。"
            "到下方「管理这个工具」做一次抽查，通过后状态变为「可使用」，"
            "就可以在这里生成接入文件了。"
        )
    else:
        st.warning(
            "这个工具当前已停用，不能接入 AI 助手。停用原因见左侧「状态原因」。"
        )
    if status != "ACTIVE" and mcp_server.is_file():
        st.caption(
            "磁盘上残留着一份旧的接入文件——不用担心：它每次被调用时都会"
            "自己核对状态账，发现工具已停用会直接拒绝工作。"
        )

expand_manage = status == "REVIEW_REQUIRED"       # 待抽查时默认展开引导
with st.expander("🔧 管理这个工具（做抽查 / 停用 / 查证据）", expanded=expand_manage):
    st.caption(
        "这里的操作只往状态账本上**追加**一条决定：不删除任何文件，"
        "也不改写历史验证结论。"
    )
    available = product_jobs.product_tool_commands()
    if "audit" in available:
        st.markdown("##### 新输入抽查")
        st.caption(AUDIT_EXPLAINER)
        a, b = st.columns(2)
        audit_input = a.text_input(
            "输入文件路径（一份这个工具从没见过的输入）", key="audit_input")
        audit_expected = b.text_input(
            "正确结果文件路径（你自己核实过的期望输出）", key="audit_expected")
        if st.button("运行新输入抽查", disabled=not (audit_input and audit_expected)):
            result = product_jobs.start_tool_audit(
                tool["name"], Path(audit_input).expanduser(),
                Path(audit_expected).expanduser(), Path(library["root"]),
            )
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))
    else:
        st.info("当前版本尚未提供抽查命令；界面已预留。")

    if "withdraw" in available:
        st.markdown("##### 停用这个工具")
        st.caption(
            "停用（撤回）只影响**今后**能否使用：文件不会被删除,历史成绩"
            "永远保留。注意：**主动停用后不能靠普通抽查恢复**——如需再次"
            "使用，要重新构建一个新版本。"
        )
        reason = st.text_input("停用原因（会记入状态账本）", key="withdraw_reason")
        if st.button("停用（撤回）", disabled=not reason):
            result = product_jobs.start_tool_withdraw(
                tool["name"], reason, Path(library["root"]),
            )
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

    st.markdown("##### 证据")
    st.write(f"**工具目录：** `{tool['path']}`")
    st.write(f"**运行证据：** `{tool.get('run_id') or '—'}`")
    st.write(f"**合同指纹：** `{tool.get('contract_sha256') or '—'}`")
