"""开始新任务 — 默认落地页:欢迎区(唯一主按钮)+ 五步向导。

第五步不启动真实 AI 运行(本版本为只读演示版);任务草稿生成复用
既有 `repoproof task init`(dry-run 预览,不写文件)。零模型调用。
"""

from __future__ import annotations

import streamlit as st

from repoproof.ui.presenters.glossary import ADMISSION, TERM
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander
from repoproof.ui.services.wizard import check_wizard_inputs

st.set_page_config(page_title="开始新任务 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()

W = "wizard_step"
if W not in st.session_state:
    st.session_state[W] = 0  # 0 = 欢迎区

STEPS = ["你想实现什么", "选择你的项目和目标仓库", "检查是否适合使用", "确认采用计划", "开始执行"]


def _goto(step: int) -> None:
    st.session_state[W] = step
    st.rerun()


# ================= 欢迎区(step 0) =================
if st.session_state[W] == 0:
    st.title("把一个开源仓库的能力,在隔离环境中可控地接入你的项目")
    st.markdown(
        "告诉系统:**你的项目**、**目标仓库**、**想实现的功能**。"
        "AI 开发助手会在隔离环境里尝试适配,独立测试给出**最终结果**——"
        "AI 自己说「做完了」不算数。"
    )
    st.markdown(
        "**三步流程**:\n"
        "1. 说清目标 —— 你的项目 + 目标仓库 + 想实现的功能\n"
        "2. AI 尝试适配 —— 在隔离环境中编写适配代码,不碰你的原文件\n"
        "3. 独立验收 —— 测试、回归、规则检查、干净环境复测,给出最终结果"
    )
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("体验任务配置流程", type="primary", width="stretch"):
        _goto(1)
    if c2.button("查看示例", width="stretch"):
        st.session_state["case"] = "frontmatter-v2-pass"
        st.switch_page("pages/case_view.py")
    st.caption(
        "本版本为只读演示版:可完整体验任务配置流程与三个已完成的真实案例;"
        "真实 AI 运行将在下一版本开放。"
    )
    st.markdown(
        "**当前支持范围**:公开的 GitHub Python 仓库 · CPU 环境 · "
        "本机 Docker · 中小型能力接入(不支持整站迁移或私有仓库)"
    )
    if is_tech():
        with tech_expander():
            st.markdown(
                "- 流程原文:Task Contract(成功标准)→ Contract Adequacy(开始前检查)→ "
                "Single Agent(AI 开发助手)→ Independent Verification(独立验证)→ "
                "Clean Replay(换干净环境再验证)→ Completion Gate(最终判定)\n"
                "- 当前版本对应 Gate 9A:evidence 只读;`task init` 仅 dry-run。"
            )
    st.stop()

# ================= 向导公共头 =================
step = st.session_state[W]
st.title("开始新任务")
st.progress(step / len(STEPS), text=f"第 {step} 步 / 共 {len(STEPS)} 步:{STEPS[step - 1]}")

_HEADERS = {
    1: ("用一两句话描述你想要的功能", "系统会把它整理成可验收的成功标准草稿",
        "没有清晰的目标,就无法公平地判定 AI 做得对不对"),
    2: ("填写你的项目位置和目标仓库", "系统会记录固定版本,保证结果可复现", "锁定版本后,今天的结论明天仍然成立"),
    3: ("让系统检查这些信息是否够用", "做适用性检查:信息完整性与支持范围", "提前发现问题,避免浪费 AI 使用额度"),
    4: ("确认采用计划", "冻结成功标准,划清 AI 与系统各自的职责", "开始后 AI 只能改代码,不能改评分规则"),
    5: ("开始执行", "本版本展示将要发生的流程与真实案例", "真实 AI 运行需要模型连接,将在下一版本开放"),
}
need, will, why = _HEADERS[step]
st.markdown(f"**这一步你需要**:{need}  \n**系统将**:{will}  \n**为什么**:{why}")
st.divider()

ss = st.session_state

# ================= Step 1 =================
if step == 1:
    ss["wz_goal"] = st.text_area(
        "想实现的功能(必填 *)",
        value=ss.get("wz_goal", ""),
        placeholder="示例:把 python-frontmatter 的解析能力接入我的文档摄取模块,"
        "输出结构化的元数据和正文,日期要转成标准字符串。",
        help="一两句话说清楚:接入哪类能力、输出什么。写得越具体,成功标准越可靠。",
    )
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("上一步", width="stretch"):
        _goto(0)
    if c2.button("下一步", type="primary", width="stretch"):
        if len(ss.get("wz_goal", "").strip()) < 10:
            st.error("还差一点:请把想实现的功能写成至少一句完整的话(不少于 10 个字),再点下一步。")
        else:
            _goto(2)

# ================= Step 2 =================
elif step == 2:
    st.subheader(TERM["host_project"])
    ss["wz_project"] = st.text_input(
        "你的项目路径(必填 *)",
        value=ss.get("wz_project", ""),
        placeholder="示例:~/my_rag_project",
        help="AI 只读你的项目源码来理解接口;修改只发生在专门的适配区。",
    )
    st.subheader(TERM["upstream_repository"])
    ss["wz_repo"] = st.text_input(
        "目标仓库地址(必填 *)",
        value=ss.get("wz_repo", ""),
        placeholder="示例:https://github.com/eyeseast/python-frontmatter",
        help="当前版本只支持公开的 GitHub 仓库。",
    )
    ss["wz_rev"] = st.text_input(
        "版本号 Tag 或 Commit(必填 *)",
        value=ss.get("wz_rev", ""),
        placeholder="示例:v1.3.0",
        help="锁定版本保证结果可复现;不确定就填最新的正式发布 Tag。",
    )
    with st.expander("高级设置(默认不用改)"):
        ss["wz_gpu"] = st.checkbox("目标仓库需要 GPU", value=ss.get("wz_gpu", False))
        st.caption("以下上限使用推荐默认值;技术模式下可见原始字段名。")
        st.markdown(f"- {TERM['token_budget']}:40 万输入 / 4 万输出")
        st.markdown(f"- {TERM['patch_budget']}:8 个文件 / 400 行")
        st.markdown("- 测试阶段网络:关闭(隔离运行)")
        if is_tech():
            st.code(
                "max_input_tokens_total=400000  max_output_tokens_total=40000\n"
                "max_patch_files=8  max_patch_lines=400  network_test=false",
                language="text",
            )
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("上一步", width="stretch"):
        _goto(1)
    if c2.button("下一步", type="primary", width="stretch"):
        _goto(3)

# ================= Step 3:适用性检查 =================
elif step == 3:
    result = check_wizard_inputs(
        goal=ss.get("wz_goal", ""),
        project_path=ss.get("wz_project", ""),
        repo_url=ss.get("wz_repo", ""),
        revision=ss.get("wz_rev", ""),
        needs_gpu=ss.get("wz_gpu", False),
        risk_confirmed=ss.get("wz_risk_ok", False),
    )
    meta = ADMISSION[result.state]
    st.subheader(f"{meta['icon']} {meta['title']}")
    st.markdown(f"**原因**:{result.reason}")
    st.markdown("**系统已经确认的事实**:")
    for fact in result.confirmed_facts:
        st.markdown(f"- {fact}")
    if result.missing:
        st.markdown("**缺少的信息**:")
        for m in result.missing:
            st.markdown(f"- 🟡 {m}")
    st.markdown(f"**你的下一步**:{result.next_step}")
    st.markdown(
        f"**是否会执行第三方代码**:{'会(在 Docker 隔离容器中)' if result.executes_third_party_code else '不会'}"
    )
    if result.state == "RISK_REVIEW":
        ss["wz_risk_ok"] = st.checkbox(
            "我了解:系统会在隔离容器中下载并执行我选择的这个公开仓库的代码;我信任该仓库。",
            value=ss.get("wz_risk_ok", False),
        )
        if ss["wz_risk_ok"]:
            st.rerun()
    if is_tech():
        with tech_expander():
            st.markdown(
                f"内部状态:`{result.state}`(这是表单适用性检查,发生在 "
                f"{TERM['contract_adequacy_gate']} 与 {TERM['provider_admission']} 之前,"
                "不替代任何 Core 判定)"
            )
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("上一步", width="stretch"):
        _goto(2)
    if c2.button("下一步", type="primary", disabled=result.state != "READY", width="stretch"):
        _goto(4)

# ================= Step 4:确认采用计划 =================
elif step == 4:
    st.markdown(f"""
| 项目 | 内容 |
|---|---|
| 想实现的功能 | {ss.get("wz_goal", "—")} |
| {TERM["host_project"]} | `{ss.get("wz_project", "—")}` |
| {TERM["upstream_repository"]} | `{ss.get("wz_repo", "—")}` @ `{ss.get("wz_rev", "—")}` |
""")
    st.markdown(
        "**职责划分**:\n"
        f"- **{TERM['agent']}**:阅读两边代码,编写{TERM['adapter']}(只能改专门的适配区)\n"
        f"- **{TERM['harness']}**:隔离执行、记录每一步、拦截越界操作、控制{TERM['token_budget']}\n"
        f"- **独立测试**:用{TERM['held_out_tests']}做{TERM['oracle']},AI 看不到,也改不了\n"
        "- **你**:现在确认成功标准;开始后 AI 只能改解决方案,不能改评分规则"
    )
    ok = st.checkbox("我确认:以上成功标准代表我真实想要的结果", value=ss.get("wz_plan_ok", False))
    ss["wz_plan_ok"] = ok
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("上一步", width="stretch"):
        _goto(3)
    if c2.button("下一步", type="primary", disabled=not ok, width="stretch"):
        _goto(5)

# ================= Step 5:开始执行(只读版) =================
elif step == 5:
    st.info(
        "🟡 本版本为只读演示版,不启动真实 AI 运行(需要模型连接,下一版本开放)。"
        "你可以先预览任务草稿会生成什么,或查看一次真实完成的案例。"
    )
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("预览任务草稿(不写入文件)", type="primary"):
        from repoproof.runner.scaffold import task_init
        from repoproof.ui.services.facts import repo_root

        slug = "adopt-my-new-task-v1"
        out = task_init(repo_root(), task_id=slug, dry_run=True)
        if out.get("ok"):
            st.success(f"草稿预览成功:将生成 {len(out['files'])} 个文件(本次未写入任何文件)。")
            st.markdown("生成后你还需要:补全成功标准细节 → 通过「开始前检查」→ 才能进入真实运行。")
            with tech_expander("查看将生成的文件清单(技术详情)"):
                st.code("\n".join(out["files"] + [d + "/" for d in out["dirs"]]), language="text")
        else:
            st.error(f"无法生成草稿:{out.get('error')}。请更换任务名后重试。")
    if c2.button("查看一次真实完成的案例"):
        st.session_state["case"] = "frontmatter-v2-pass"
        st.switch_page("pages/case_view.py")
    st.divider()
    if st.button("上一步", width="stretch"):
        _goto(4)
