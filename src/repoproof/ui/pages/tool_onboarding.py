"""Create, review and build a Local Tool without requiring terminal usage."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from repoproof.ui.product_theme import apply_product_theme, hero, section_intro
from repoproof.ui.services import product_jobs
from repoproof.ui.services.product_mode import (
    default_output_contract,
    next_task_version_preview,
    parse_output_contract,
    tool_root,
    ui_state_root,
    validate_draft_output_examples,
)

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
    review_bundle = product_jobs.read_managed_draft_review(inspect_dir)
    if not review_bundle.get("ok"):
        st.info(
            "生成受管草稿后回到这里审核；当前路径不可读取。"
            f" {review_bundle.get('error') or ''}"
        )
    else:
        inspect_dir = Path(review_bundle["draft_dir"])
        draft = review_bundle["draft"]
        tool = draft.get("tool") or {}
        iface = tool.get("interface") or {}
        cap = draft.get("capability") or {}
        saved_output_format = str((iface.get("output") or {}).get("format") or "")
        existing_contract = (iface.get("output") or {}).get("contract")
        if not existing_contract:
            existing_contract = default_output_contract(saved_output_format)
        with st.form("draft_review_form"):
            tool_name = st.text_input("工具名", value=str(tool.get("name") or ""))
            summary = st.text_input("一句话摘要", value=str(tool.get("summary") or ""))
            statement = st.text_area("能力和边界", value=str(cap.get("statement") or ""), height=130)
            a, b = st.columns(2)
            input_format = a.text_input("输入格式", value=str((iface.get("input") or {}).get("format") or ""))
            output_format = b.text_input("输出格式", value=saved_output_format)
            output_schema = st.text_input("输出结构名称", value=str(cap.get("output_schema") or ""))
            output_contract_text = st.text_area(
                "可执行输出合同（所有 v2 工具必填）",
                value=json.dumps(existing_contract, ensure_ascii=False, indent=2),
                help=(
                    "由 Core ToolOutputContract 验证；普通文本也必须明确声明 "
                    "text/plain + text。"
                ),
                height=130,
            )
            reference = st.text_area(
                "参考实现（必须真实 import 固定上游）",
                value=review_bundle["reference_impl"],
                height=260,
            )
            save = st.form_submit_button("保存审核修改", type="primary")
        if save:
            parsed_contract, contract_errors = parse_output_contract(
                output_contract_text,
                output_format=output_format,
            )
            if contract_errors:
                result = {"ok": False, "error": "；".join(contract_errors)}
            elif parsed_contract is not None:
                result = product_jobs.save_draft_review(
                    inspect_dir,
                    tool_name=tool_name,
                    summary=summary,
                    statement=statement,
                    input_format=input_format,
                    output_format=output_format,
                    output_schema=output_schema,
                    reference_impl=reference,
                    output_contract=parsed_contract.model_dump(mode="json"),
                )
            else:  # pragma: no cover - defensive, parser returns one side
                result = {"ok": False, "error": "OUTPUT_CONTRACT_INVALID"}
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

        if tool_name:
            try:
                preview = next_task_version_preview(tool_name)
            except (OSError, ValueError) as exc:
                st.error(f"任务版本谱系无法安全计算：{exc}")
            else:
                st.caption(
                    f"冻结版本只读预览：`{preview['task_id']}`。{preview['note']}"
                )

        st.markdown("#### 加入确认过的 Golden 样例")
        st.caption("至少三组，其中每四组的最后一组会自动成为不交给 Agent 的 held-out 样例。")
        c_in, c_out = st.columns(2)
        uploaded_in = c_in.file_uploader("输入文件", key="golden_input")
        uploaded_out = c_out.file_uploader("期望输出文件", key="golden_expected")
        if st.button("加入这一组样例", disabled=not (uploaded_in and uploaded_out)):
            current_contract, contract_errors = parse_output_contract(
                output_contract_text,
                output_format=output_format,
            )
            golden_errors: list[str] = []
            if current_contract is not None:
                try:
                    expected_text = uploaded_out.getvalue().decode("utf-8")
                except UnicodeDecodeError:
                    golden_errors = ["GOLDEN_OUTPUT_INVALID: 期望输出必须是 UTF-8"]
                else:
                    from repoproof.adoption.assembly.output_contract import (
                        validate_output_text,
                    )

                    golden_errors = [
                        f"GOLDEN_OUTPUT_INVALID: {detail}"
                        for detail in validate_output_text(expected_text, current_contract)
                    ]
            if contract_errors or golden_errors:
                result = {
                    "ok": False,
                    "error": "；".join([*contract_errors, *golden_errors]),
                }
            else:
                result = product_jobs.add_golden_example(
                    inspect_dir,
                    input_name=uploaded_in.name,
                    input_bytes=uploaded_in.getvalue(),
                    expected_name=uploaded_out.name,
                    expected_bytes=uploaded_out.getvalue(),
                )
            (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))
        # Gate 4:能力计划人读卡(RFC-013)—— 束内 plan.yaml 存在即渲染;
        # 证据、支持状态与执行路线都可审查,不是一句模糊的"可以做"。
        plan_file = Path(review_bundle["draft_dir"]) / "plan.yaml"
        if plan_file.is_file():
            import yaml as _yaml

            from repoproof.ui.services.product_mode import ROUTE_LABELS

            plan_doc = _yaml.safe_load(plan_file.read_text(encoding="utf-8")) or {}
            status = str(plan_doc.get("support_status") or "—")
            route = str(plan_doc.get("implementation_route") or "NONE")
            st.markdown("#### 能力计划(证据化)")
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric("支持状态", status)
            pc2.metric("执行路线", route)
            pc3.metric("用户已确认", "是" if plan_doc.get("confirmed") else "否")
            st.write(f"**路线含义：** {ROUTE_LABELS.get(route, route)}")
            codes = plan_doc.get("reason_codes") or []
            if codes:
                st.write("**理由码：** " + ", ".join(f"`{x}`" for x in codes))
            surfaces = plan_doc.get("detected_surfaces") or []
            if surfaces:
                st.dataframe(
                    [{
                        "类型": s.get("kind"),
                        "定位": s.get("locator"),
                        "签名": s.get("signature") or "—",
                        "置信度": s.get("confidence"),
                        "证据": "; ".join(s.get("evidence") or []) or "—",
                        "未选用原因": s.get("exclusion_reason") or "(已选用)",
                    } for s in surfaces],
                    hide_index=True, use_container_width=True)
            st.caption(
                "路由由确定性规则给出;LLM 建议不能改变支持状态或路线,"
                "未确认的计划不会触发任何真实模型。")

        examples = review_bundle["examples"]
        st.metric("已确认样例", len(examples), help="冻结至少需要三组")
        if examples:
            st.dataframe(examples, hide_index=True, use_container_width=True)

        with st.expander("查看原始草稿与缺口清单"):
            st.code(review_bundle["raw_draft"], language="yaml")
            if review_bundle["gaps"]:
                st.markdown(review_bundle["gaps"])

with tab_build:
    section_intro("先彩排，再决定是否启动真实 Agent", "彩排门失败不会消耗真实模型预算；成功后仍需独立验证和干净重放。")
    st.caption(
        "默认 Agent backend：mini-swe。DeepSeek Harness（DSH）目前仅为可选实验后端，"
        "不作为 Studio 默认执行路径。"
    )
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
    lineage_ready = True
    build_bundle = product_jobs.read_managed_draft_review(build_dir)
    if build_bundle.get("ok"):
        build_dir = Path(build_bundle["draft_dir"])
        # Gate 4:构建前的路线预告 —— 用户在点按钮前就知道会不会调模型。
        bp = build_dir / "plan.yaml"
        if bp.is_file():
            import yaml as _byaml

            _pd = _byaml.safe_load(bp.read_text(encoding="utf-8")) or {}
            _rt = str(_pd.get("implementation_route") or "NONE")
            if _rt == "DIRECT_WRAP":
                st.info("本次构建走确定性直连包装:**不会调用任何模型**;"
                        "验证链(held-out/上游采用/干净重放)照常全跑。")
            elif _rt == "AGENT_ADAPT":
                st.info("本次构建需要受限 Coding Agent 适配:"
                        "先离线彩排,真实模型仅在彩排通过后按预算调用。")
        output_preflight = validate_draft_output_examples(build_dir)
        preview_doc = build_bundle["draft"]
        preview_name = str((preview_doc.get("tool") or {}).get("name") or "")
        if preview_name:
            try:
                preview = next_task_version_preview(preview_name)
            except (OSError, ValueError) as exc:
                lineage_ready = False
                st.error(f"任务版本谱系无法安全计算：{exc}")
            else:
                st.caption(
                    f"本次冻结版本只读预览：`{preview['task_id']}`。{preview['note']}"
                )
    else:
        output_preflight = {
            "ok": False,
            "errors": [str(build_bundle.get("error") or "MANAGED_DRAFT_INVALID")],
        }
    if output_preflight["ok"]:
        st.success("OUTPUT_CONTRACT_READY：合同与 Golden 输出通过构建前只读检查。")
    else:
        st.error("构建前输出合同检查未通过：\n\n- " + "\n- ".join(output_preflight["errors"]))
    if st.button(
        "开始彩排" if rehearsal_only else "开始完整构建",
        type="primary",
        disabled=(
            not confirmed
            or not output_preflight["ok"]
            or not lineage_ready
        ),
    ):
        result = product_jobs.start_tool_build(
            draft_dir=build_dir,
            dest_root=dest_root,
            rehearsal_only=rehearsal_only,
        )
        (st.success if result.get("ok") else st.error)(result.get("note") or result.get("error"))

    st.markdown("**构建全流程(每一步失败即停,不烧后续预算):**")
    st.markdown(
        "1. 确认闸 → 2. 装配冻结 → 3. 离线彩排 → 4. Agent 构建 → "
        "5. 独立验证 → 6. 干净重放 → 7. 导出并登记"
    )
