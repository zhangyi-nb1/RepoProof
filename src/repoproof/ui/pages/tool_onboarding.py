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

def _require_service(name: str) -> bool:
    """新接口是否已在**运行中的进程**里(LESSONS #50)。

    Streamlit 只重新 exec 页面文件,不重载它 import 的 services 模块 ——
    刚加的函数在磁盘上有、在进程里没有,直接调用会甩一串英文
    AttributeError 给用户。这里探测一次,给人话提示。
    """
    if hasattr(product_jobs, name):
        return True
    st.warning(
        "这个功能刚更新过,但当前 Studio 进程还是旧的(Streamlit 只热重载页面,"
        "不重载后台服务模块)。**请重启 Studio 后再用**;已有的草稿和工具不受影响。"
    )
    return False


tab_discover, tab_review, tab_build = st.tabs(["1 · 描述能力", "2 · 审核成功标准", "3 · 构建与验证"])

with tab_discover:
    section_intro("告诉系统你想保留哪项能力", "只选择一个输入输出明确、能用样例验证的能力。")
    # 仓库与版本放在表单**之外**:这样填完仓库就能先读一份简介,再回来
    # 写"你想要的能力" —— 不了解这个仓库的人,写不出准确的能力描述。
    repo = st.text_input(
        "公开 GitHub 仓库",
        placeholder="https://github.com/owner/project",
        key="rp_repo_url",
    )
    revision = st.text_input("版本或 Commit（可选）", placeholder="v1.2.3 或完整 commit",
                             key="rp_repo_rev")

    if (st.button("读取仓库简介（零模型，只做静态分析）", disabled=not repo.strip())
            and _require_service("read_repo_overview")):
        with st.spinner("匿名浅克隆并静态分析中……（不会执行仓库代码）"):
            st.session_state["rp_overview"] = product_jobs.read_repo_overview(
                repo, revision or None)
        st.session_state.pop("rp_overview_summary", None)

    _ov_result = st.session_state.get("rp_overview") or {}
    if _ov_result and not _ov_result.get("ok"):
        st.error(_ov_result.get("error") or "读取失败")
    elif _ov_result.get("ok"):
        _ov = _ov_result["overview"]
        with st.container(border=True):
            st.markdown("#### 这个仓库是做什么的")
            if _ov.get("headline"):
                st.markdown(f"**{_ov['headline']}**")
            if _ov.get("prose"):
                with st.expander("README 原文摘录（未经模型改写）", expanded=True):
                    st.write(_ov["prose"])
                    st.caption(f"来源：{_ov.get('prose_source') or 'README'}")
            if _ov.get("quickstart"):
                st.caption(f"上手片段（{_ov.get('quickstart_evidence') or 'README'}）")
                st.code(_ov["quickstart"], language="python")
            elif _ov.get("quickstart_note"):
                st.caption(f"上手片段：{_ov['quickstart_note']}"
                           f"（{_ov.get('quickstart_evidence') or 'README'}）")

            if _ov.get("facts"):
                st.markdown("**静态分析确认的事实**（每条都可追到出处）")
                st.dataframe(
                    [{"事实": f["label"], "值": f["value"],
                      "依据": f.get("evidence") or "—",
                      "来源档位": f.get("provenance") or "—"} for f in _ov["facts"]],
                    hide_index=True, width="stretch")
            if _ov.get("surfaces"):
                st.markdown("**它对外提供的入口**（你要的能力大概率在这里面）")
                st.dataframe(
                    [{"类型": s["kind"], "名称": s["value"],
                      "依据": s.get("evidence") or "—"} for s in _ov["surfaces"]],
                    hide_index=True, width="stretch")
            if _ov.get("risks"):
                st.warning("需要注意：" + "；".join(_ov["risks"][:3]))

            sc1, sc2 = st.columns([1, 2])
            _sum_offline = sc2.checkbox("用离线模板（零模型调用）", value=False,
                                        key="rp_sum_offline")
            if sc1.button("让模型总结/翻译一下"):
                with st.spinner("生成摘要中……"):
                    st.session_state["rp_overview_summary"] = (
                        product_jobs.summarize_repo_overview(_ov, offline=_sum_offline))
            _sum = st.session_state.get("rp_overview_summary") or {}
            if _sum and not _sum.get("ok"):
                st.error(_sum.get("error"))
            elif _sum.get("ok"):
                st.info(f"**模型摘要（{_sum.get('drafter')}）**\n\n{_sum['summary']}")
                st.caption(
                    "这是模型对上面原文的复述，**不是事实来源**；判定只认原文与静态分析。"
                    "它也不会替你决定要哪个能力——那一句必须你自己写。")

    with st.form("tool_add_form"):
        capability = st.text_area(
            "你想要的能力",
            placeholder="例如：给一个 PDF 文件，提取其中所有表格并输出 Markdown。",
            height=110,
        )
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

        # ---------------- 样例助手:模型出输入、上游出输出、你逐条确认 ----------------
        with st.expander("🧪 不知道样例怎么写？让系统给你候选（真值仍由你确认）",
                         expanded=False):
            st.caption(
                "分工是固定的：**候选输入**由模型出（输入不是判据）；**期望输出**由"
                "钉住的那一版上游**真跑**给出（不是模型猜的）；最后**每一条都要你点确认**"
                "才会成为验收真值。没有「全部确认」——一次点击只为一条负责。"
            )
            gp1, gp2, gp3 = st.columns([1, 1, 2])
            _n = gp1.number_input("要几条候选", min_value=1, max_value=8, value=4,
                                  key="rp_cand_n")
            _cand_offline = gp2.checkbox("离线模板", value=True, key="rp_cand_offline",
                                         help="零模型调用，先把流程走通")
            if (gp3.button("生成候选（含边界/畸形输入）", key="rp_cand_go")
                    and _require_service("propose_example_candidates")):
                with st.spinner("模型出候选输入 → 钉版上游真跑……"):
                    st.session_state["rp_cands"] = product_jobs.propose_example_candidates(
                        inspect_dir, n=int(_n), offline=_cand_offline)

            _cr = st.session_state.get("rp_cands") or {}
            if _cr and not _cr.get("ok"):
                st.error(_cr.get("error"))
            elif _cr.get("ok"):
                st.caption(f"候选来源：{_cr.get('drafter')} · {_cr.get('note')}")
                _usable = [c for c in _cr["candidates"]
                           if c.get("upstream_output") and not c.get("upstream_error")]
                _errs = [c for c in _cr["candidates"] if c.get("upstream_error")]

                for i, c in enumerate(_usable):
                    with st.container(border=True):
                        st.markdown(f"**候选 {i + 1} · `{c['input_name']}`**"
                                    + (f" — {c['why']}" if c.get("why") else ""))
                        e1, e2 = st.columns(2)
                        _in_text = e1.text_area(
                            "输入（可改）", value=c["input_text"], height=120,
                            key=f"rp_cand_in_{i}")
                        _out_text = e2.text_area(
                            "上游实际输出（可改；改了以你的为准）",
                            value=c["upstream_output"], height=120,
                            key=f"rp_cand_out_{i}")
                        st.caption(
                            "⚠️ 这是**上游此刻的实际输出，不是对错判定**——"
                            "它是不是你要的能力，仍然由你判断。")
                        if st.button("✅ 我确认这一条，加入样例", key=f"rp_cand_ok_{i}"):
                            r = product_jobs.confirm_candidate_as_example(
                                inspect_dir, c, expected_text=_out_text,
                                input_text=_in_text)
                            (st.success if r.get("ok") else st.error)(
                                (r.get("note") or r.get("error") or "")
                                + (f"（真值来源：{r.get('truth_provenance')}）"
                                   if r.get("ok") else ""))

                if _errs:
                    st.markdown("**这些候选让上游抛了错——它们做不成样例，但很有用**")
                    st.caption(
                        "Golden 样例只表达成功路径。这些是「这类输入会炸」的行为证据："
                        "把它们写进上面的**能力和边界**，别等真发时被隐藏验收撞出来。")
                    st.dataframe(
                        [{"输入": (c["input_text"][:40] or "（空）"),
                          "上游错误": c["upstream_error"]} for c in _errs],
                        hide_index=True, width="stretch")

        st.markdown("#### 加入确认过的 Golden 样例")
        st.caption("至少三组，其中每四组的最后一组会自动成为不交给 Agent 的 held-out 样例。")
        st.caption("文本样例可以直接在下方「在线填写」；二进制输入（PDF、图片等）请用上传。")

        with st.expander("✍️ 在线填写一组样例（文本）", expanded=False):
            w1, w2 = st.columns(2)
            _wname = w1.text_input("样例文件名", value="case_1.txt", key="rp_write_name")
            _wint = w1.text_area("输入内容", height=140, key="rp_write_in")
            _woutt = w2.text_area("期望输出（你核实过的真值）", height=185, key="rp_write_out")
            if st.button("加入这一组（在线填写）", disabled=not _wname.strip()):
                r = product_jobs.add_golden_example(
                    inspect_dir,
                    input_name=Path(_wname).name,
                    input_bytes=_wint.encode("utf-8"),
                    expected_name=f"{Path(_wname).stem}.expected.txt",
                    expected_bytes=_woutt.encode("utf-8"))
                (st.success if r.get("ok") else st.error)(
                    r.get("note") or r.get("error"))

        c_in, c_out = st.columns(2)
        uploaded_in = c_in.file_uploader("输入文件", key="golden_input")
        uploaded_out = c_out.file_uploader("期望输出文件", key="golden_expected")
        # disabled 只挡点击,挡不住类型(也挡不住 Streamlit 版本差异下的
        # 意外触发)—— 两个文件都在场才进这一段,缺一个如实不做事。
        if (st.button("加入这一组样例",
                      disabled=not (uploaded_in and uploaded_out))
                and uploaded_in is not None and uploaded_out is not None):
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
            # P1(外部审计 2026-08-25,easter 实例):analyzer 是**表面
            # 检测器**,不是意图匹配器 —— 这条边界必须向用户明说,
            # 不许用"自动理解你的需求"式话术把把关责任揽到系统身上。
            st.warning(
                "**请核对上面的「定位」再确认。** 系统只根据代码的表面特征"
                "(导出名单、函数签名、文件位置)找出候选入口,它**不理解**"
                "这个函数是否真是你想要的能力 —— 候选与你的意图是否相符,"
                "由你在确认这一步把关(术语:用户确认 callable locator)。"
            )

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
