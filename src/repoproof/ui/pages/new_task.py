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
    from repoproof.ui.services import live_run as _lr0
    from repoproof.ui.services.facts import repo_root as _rr0

    _root0 = _rr0()
    _tasks0 = _lr0.frozen_tasks(_root0)
    if _tasks0:
        st.divider()
        st.subheader("已就绪的任务(装配/冻结过的任务在这里,刷新不丢)")
        _sel0 = st.selectbox("直接选择并运行,无需重走五步", _tasks0, index=len(_tasks0) - 1)
        if st.button("直接开始真实运行", disabled=not _lr0.provider_ready()):
            _out0 = _lr0.start_run(_root0, _sel0)
            (st.success if _out0.get("ok") else st.error)(_out0.get("note") or _out0.get("error"))
            if _out0.get("ok"):
                st.markdown("到「运行进度」页查看实时状态与最终结论。")
        if not _lr0.provider_ready():
            st.caption("模型连接未配置:用 ./scripts/run_ui_live.sh 启动即可启用。")
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
    st.subheader("给出验收样例(必填,至少 3 行)")
    st.caption("每行一组:输入 => 期望。期望以 contains: 开头表示「包含即通过」,否则要求完全相等。"
               "这些样例就是你的成功标准:大部分给 AI 看并自测,至少 1 组会被留作它看不到的隐藏验证。")
    ss["wz_examples"] = st.text_area(
        "样例(输入 => 期望)", value=ss.get("wz_examples",
        "周合 => contains:周会纪要\n读书 => contains:测试驱动\n咖啡 => contains:购物清单\nkafei => contains:购物清单"),
        height=140)
    ok = st.checkbox("我确认:以上成功标准代表我真实想要的结果", value=ss.get("wz_plan_ok", False))
    ss["wz_plan_ok"] = ok
    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("上一步", width="stretch"):
        _goto(3)
    if c2.button("下一步", type="primary", disabled=not ok, width="stretch"):
        _goto(5)

# ================= Step 5:开始执行(只读版) =================
elif step == 5:
    from repoproof.ui.services import live_run
    from repoproof.ui.services.facts import repo_root as _rr

    _root = _rr()
    live_run.clear_lock_if_done(_root)
    tasks = live_run.frozen_tasks(_root)
    st.subheader("真实运行(在你自己的机器上跑一次完整流程)")
    if not live_run.provider_ready():
        st.warning("模型连接未配置。用 `./scripts/run_ui_live.sh` 启动工作台即可开启此入口"
                   "(密钥只进进程环境,不落盘、不显示)。")
    task_sel = st.selectbox(
        "选择一个已冻结的任务(合同与验收已封存,AI 只能改解决方案)",
        tasks, index=len(tasks) - 1 if tasks else 0,
        help="只有完成「开始前检查」并冻结的任务才能真实运行;新任务需先完成任务工程。")
    st.caption("说明:这是产品模式运行——结果写入本地 runs/,不进入公开 benchmark,不触碰历史证据。"
               "一次运行会真实调用你配置的模型(消耗额度)。")
    if st.button("开始真实运行", type="primary", disabled=not live_run.provider_ready()):
        out = live_run.start_run(_root, task_sel)
        if out.get("ok"):
            st.success(out["note"])
            st.markdown("到「运行进度」页可查看状态;完成后在本地 `runs/` 目录与「结果报告」思路一致地复核 "
                        "`report.json`(最终判定由独立验证产生,AI 自述不算数)。")
        else:
            st.error(out["error"])
    info = live_run.active_run(_root)
    if info and info.get("alive"):
        st.info(f"⏳ 正在运行:{info.get('task_id')}(后台进程 {info.get('pid')};刷新页面不会中断)")
    st.divider()
    st.subheader("装配你的新任务(全自动,无需任何外部 AI)")
    st.caption("把你确认的目标 + 样例编译成完整任务(合同/验收测试/控制组)并冻结;"
               "冻结成功后它会出现在上方「真实运行」下拉框,由你亲手运行。验收强度=用户样例级。")
    if st.button("装配并冻结新任务", width="stretch"):
        import subprocess as _sp

        from repoproof.adoption.analysis.repository_analyzer import analyze_repository_dir
        from repoproof.adoption.assembly.example_compiler import CompileError
        from repoproof.adoption.assembly.task_assembler import assemble_task

        try:
            exs = []
            for line in (ss.get("wz_examples") or "").splitlines():
                if "=>" in line:
                    left, right = line.split("=>", 1)
                    exs.append({"input": left.strip(), "expected": right.strip()})
            _url = (ss.get("wz_repo") or "").strip().rstrip("/")
            repo_name = _url.rsplit("/", 1)[-1].removesuffix(".git").strip()
            cand = sorted((_root / "upstream-cache" / "analysis").glob(f"{repo_name}-*"))
            if not cand:
                st.error(f"未找到目标仓库的本地分析副本({repo_name})——请先在终端运行 "
                         f"repoproof analyze-repo --url {ss.get('wz_repo', '<url>')}")
                st.stop()
            rep = analyze_repository_dir(cand[0], url=_url)
            with st.status("装配任务文件……", expanded=True) as _s:
                out = assemble_task(
                    _root, goal=ss.get("wz_goal", ""), repo_url=_url,
                    resolved_commit=str(rep.commit.value), distribution=repo_name,
                    import_module=repo_name.replace("-", "_"),
                    license_id=str(rep.license.value), examples=exs)
                steps = [
                    (["freeze-task", "--contract", f"contracts/{out['task_id']}.yaml"],
                     "封存合同、获取目标仓库固定版本……"),
                    (["baseline", "--contract", f"contracts/{out['task_id']}.yaml"],
                     "构建离线依赖 + 直连基线(未适配时样例应当失败,这是正常的)……"),
                    (["freeze-task", "--contract", f"contracts/{out['task_id']}.yaml", "--full"],
                     "冻结验收集合 + 控制组自检……"),
                ]
                proc = None
                for args_, label_ in steps:
                    _s.update(label=f"({out['public']} 公开 + {out['held']} 隐藏样例){label_}")
                    proc = _sp.run([str(_root / ".venv" / "bin" / "python"), "-m", "repoproof.cli",
                                    *args_], capture_output=True, text=True, cwd=str(_root),
                                   timeout=900, check=False)
                    if proc.returncode != 0:
                        break
                if proc and proc.returncode == 0:
                    _s.update(label="装配并冻结完成", state="complete")
                    st.success(f"任务 {out['task_id']} 已冻结——刷新后在上方「真实运行」选择它,"
                               "亲手开始你的第一次运行。")
                else:
                    _s.update(label="冻结未通过", state="error")
                    st.error("冻结失败(通常是控制组自检或依赖构建问题)。技术输出末段:")
                    st.code((proc.stdout + proc.stderr)[-1200:], language="text")
        except CompileError as exc:
            st.error(f"样例不满足要求:{exc}")
    st.divider()
    st.subheader("或者:先看看流程与案例")
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("预览任务草稿(不写入文件)"):
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
