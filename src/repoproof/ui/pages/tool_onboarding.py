"""Create, review and build a Local Tool without requiring terminal usage."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
import yaml

from repoproof.ui.product_theme import apply_product_theme, hero, section_intro
from repoproof.ui.services import product_jobs
from repoproof.ui.services.product_mode import tool_root, ui_state_root

st.set_page_config(page_title="新建工具 · RepoProof Studio", page_icon="🧰", layout="wide")
apply_product_theme()

hero(
    "从一句需求开始",
    "先生成可审阅的成功标准草稿，再放入你确认过的样例。只有人闸和确定性检查通过后，系统才会消耗真实模型预算。",
    kicker="New verified local tool",
)

job = product_jobs.product_job_state()
if job and job.get("alive"):
    st.info(f"正在执行：{job.get('label')}。可以离开本页，后台任务不会中断。")
elif job and job.get("finished"):
    (st.success if job.get("ok") else st.error)(job.get("note") or "任务已结束")

tab_discover, tab_review, tab_build = st.tabs(["1 · 描述能力", "2 · 审核成功标准", "3 · 构建与验证"])

with tab_discover:
    section_intro("告诉系统你想保留哪项能力", "只选择一个输入输出明确、能用样例验证的能力。")
    with st.form("tool_add_form"):
        repo = st.text_input(
            "公开 GitHub 仓库",
            placeholder="https://github.com/owner/project",
        )
        capability = st.text_area(
            "你想要的能力",
            placeholder="例如：给一个 PDF 文件，提取其中所有表格并输出 Markdown。",
            height=110,
        )
        revision = st.text_input("版本或 Commit（可选）", placeholder="v1.2.3 或完整 commit")
        draft_default = str(ui_state_root() / "drafts" / "my-tool-draft")
        draft_dir = st.text_input("草稿保存位置", value=draft_default)
        offline = st.checkbox("先用离线模板起草（零模型调用）", value=False)
        submitted = st.form_submit_button("分析仓库并生成草稿", type="primary")
    if submitted:
        result = product_jobs.start_tool_add(
            repo=repo,
            capability=capability,
            revision=revision or None,
            draft_dir=Path(draft_dir).expanduser(),
            fake_drafter=offline,
        )
        (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

    st.markdown("#### 系统会先回答")
    c1, c2, c3 = st.columns(3)
    c1.info("**是否支持**\n\nCPU、许可证、密钥和依赖风险是否在 v1 边界内。")
    c2.info("**还缺什么**\n\n哪些字段可自动起草，哪些真值必须由你确认。")
    c3.info("**是否值得运行**\n\n不合适的任务会直接拒绝，避免浪费模型预算。")

with tab_review:
    section_intro("把“什么叫完成”说清楚", "这里编辑的是题面，不是 Agent 的实现。冻结后任何模型都不能再改。")
    inspect_dir = Path(
        st.text_input(
            "草稿目录",
            value=st.session_state.get("rp_draft_dir", str(ui_state_root() / "drafts" / "my-tool-draft")),
            key="review_draft_dir",
        )
    ).expanduser()
    st.session_state["rp_draft_dir"] = str(inspect_dir)
    draft_path = inspect_dir / "draft.yaml"
    if not draft_path.is_file():
        st.info("生成草稿后回到这里审核；当前目录还没有 draft.yaml。")
    else:
        draft = yaml.safe_load(draft_path.read_text(encoding="utf-8")) or {}
        tool = draft.get("tool") or {}
        iface = tool.get("interface") or {}
        cap = draft.get("capability") or {}
        existing_contract = (iface.get("output") or {}).get("contract") or {}
        with st.form("draft_review_form"):
            tool_name = st.text_input("工具名", value=str(tool.get("name") or ""))
            summary = st.text_input("一句话摘要", value=str(tool.get("summary") or ""))
            statement = st.text_area("能力和边界", value=str(cap.get("statement") or ""), height=130)
            a, b = st.columns(2)
            input_format = a.text_input("输入格式", value=str((iface.get("input") or {}).get("format") or ""))
            output_format = b.text_input("输出格式", value=str((iface.get("output") or {}).get("format") or ""))
            output_schema = st.text_input("输出结构名称", value=str(cap.get("output_schema") or ""))
            output_contract_text = st.text_area(
                "可执行输出合同（结构化输出必填）",
                value=json.dumps(existing_contract, ensure_ascii=False, indent=2),
                help="M5 使用它独立解析真实 stdout；文本输出可保留空对象。",
                height=130,
            )
            reference = st.text_area(
                "参考实现（必须真实 import 固定上游）",
                value=(inspect_dir / "reference_impl.py").read_text(encoding="utf-8")
                if (inspect_dir / "reference_impl.py").is_file() else "",
                height=260,
            )
            save = st.form_submit_button("保存审核修改", type="primary")
        if save:
            try:
                output_contract = json.loads(output_contract_text or "{}")
                if not isinstance(output_contract, dict):
                    raise ValueError("输出合同必须是 JSON object")
            except (json.JSONDecodeError, ValueError) as exc:
                result = {"ok": False, "error": f"输出合同不是合法 JSON：{exc}"}
            else:
                result = product_jobs.save_draft_review(
                    inspect_dir,
                    tool_name=tool_name,
                    summary=summary,
                    statement=statement,
                    input_format=input_format,
                    output_format=output_format,
                    output_schema=output_schema,
                    reference_impl=reference,
                    output_contract=output_contract,
                )
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

        st.markdown("#### 加入确认过的 Golden 样例")
        st.caption("至少三组，其中每四组的最后一组会自动成为不交给 Agent 的 held-out 样例。")
        c_in, c_out = st.columns(2)
        uploaded_in = c_in.file_uploader("输入文件", key="golden_input")
        uploaded_out = c_out.file_uploader("期望输出文件", key="golden_expected")
        if st.button("加入这一组样例", disabled=not (uploaded_in and uploaded_out)):
            result = product_jobs.add_golden_example(
                inspect_dir,
                input_name=uploaded_in.name,
                input_bytes=uploaded_in.getvalue(),
                expected_name=uploaded_out.name,
                expected_bytes=uploaded_out.getvalue(),
            )
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))
        examples_path = inspect_dir / "examples.yaml"
        if examples_path.is_file():
            examples = (yaml.safe_load(examples_path.read_text(encoding="utf-8")) or {}).get("examples") or []
            st.metric("已确认样例", len(examples), help="冻结至少需要三组")
            if examples:
                st.dataframe(examples, hide_index=True, use_container_width=True)

        with st.expander("查看原始草稿与缺口清单"):
            st.code(draft_path.read_text(encoding="utf-8"), language="yaml")
            gaps = inspect_dir / "GAPS.md"
            if gaps.is_file():
                st.markdown(gaps.read_text(encoding="utf-8"))

with tab_build:
    section_intro("先彩排，再决定是否启动真实 Agent", "彩排门失败不会消耗真实模型预算；成功后仍需独立验证和干净重放。")
    build_dir = Path(
        st.text_input(
            "已经审核完成的草稿目录",
            value=st.session_state.get("rp_draft_dir", str(ui_state_root() / "drafts" / "my-tool-draft")),
            key="build_draft_dir",
        )
    ).expanduser()
    dest_root = Path(st.text_input("工具库位置", value=str(tool_root()))).expanduser()
    rehearsal_only = st.toggle("只运行离线彩排", value=True)
    confirmed = st.checkbox("我已确认输入输出、样例真值、上游版本和许可证")
    if st.button("开始彩排" if rehearsal_only else "开始完整构建", type="primary", disabled=not confirmed):
        result = product_jobs.start_tool_build(
            draft_dir=build_dir,
            dest_root=dest_root,
            rehearsal_only=rehearsal_only,
        )
        (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

    stages = {
        "1": "确认闸",
        "2": "装配冻结",
        "3": "离线彩排",
        "4": "Agent 构建",
        "5": "独立验证",
        "6": "干净重放",
        "7": "导出并登记",
    }
    st.code(json.dumps(stages, ensure_ascii=False, indent=2), language="json")
