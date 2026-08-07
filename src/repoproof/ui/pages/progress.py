"""运行进度 — 已完成任务的回顾视图(过去时)。

本版本无实时任务。简单模式:三阶段回顾,不出现 Trace/Token/Hash;
「显示技术详情」开启后:九阶段 + 用量明细 + 执行记录。
常驻区分「AI 助手状态」与「最终系统结论」。
"""

from __future__ import annotations

import streamlit as st

from repoproof.runner.demo import CASES
from repoproof.ui.presenters.glossary import (
    STAGES_DONE,
    STAGES_DONE_3,
    agent_exit_simple,
    verdict_icon,
    verdict_simple,
)
from repoproof.ui.services import facts
from repoproof.ui.services import live_run as _lr
from repoproof.ui.services.facts import repo_root as _rr2
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander

st.set_page_config(page_title="运行进度 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()
st.title("运行进度")

_root2 = _rr2()
_info = _lr.active_run(_root2)
if _info and _info.get("alive"):
    st.info(f"⏳ 正在运行:{_info.get('task_id')}(后台进程 {_info.get('pid')})。"
            "本页每次刷新读取最新状态;运行通常需要 2-6 分钟。")
    from pathlib import Path as _P
    _log = _P(str(_info.get("log", "")))
    if _log.exists():
        st.code(_log.read_text(encoding="utf-8", errors="replace")[-800:] or "(启动中……)",
                language="text")
elif _info and _info.get("report_ready"):
    from repoproof.ui.presenters.glossary import verdict_icon as _vi
    from repoproof.ui.presenters.glossary import verdict_simple as _vs
    _v = _info.get("verdict")
    st.success(f"✅ 你的任务 {_info.get('task_id')} 已完成 —— 最终结论:{_vi(_v)} **{_vs(_v)}**"
               f"(本地运行目录:runs/{_info.get('latest_run')})")
    st.caption("完整产物(适配代码/执行记录/各项检查输出)都在上述目录;结论由独立验证产生,AI 自述不参与。")
    _lr.clear_lock_if_done(_root2)
else:
    st.info("🟡 当前没有正在运行的任务。下面可以回顾一次已完成任务的全过程。")

_names = {
    "frontmatter-v2-pass": "示例:文档元数据解析(成功案例)",
    "chonkie-agent-fail": "示例:文本分块(未通过案例)",
    "bm25-agent-fail": "示例:检索排序(未通过案例)",
}
_valid = list(CASES)
_default = st.session_state.get("case") or _valid[0]
if _default not in _valid:
    _default = _valid[0]
case = st.selectbox(
    "选择要回顾的任务", _valid, index=_valid.index(_default), format_func=lambda c: _names[c]
)
st.session_state["case"] = case

report = facts.load_report(case)
manifest = facts.load_run_manifest(case)
agent = manifest.get("agent") or report.get("agent") or {}
verdict = report.get("final_verdict") or report.get("verdict")

# ---- 阶段回顾(过去时;简单=3 段,技术=9 段) ----
st.subheader("这次任务经历了什么")
if is_tech():
    for i, stage in enumerate(STAGES_DONE, 1):
        st.markdown(f"✅ 第 {i} 步 · {stage}")
else:
    for stage, detail in STAGES_DONE_3:
        st.markdown(f"✅ **{stage}** —— {detail}")
st.progress(1.0, text="该任务已执行完毕")

# ---- AI 状态 ≠ 系统结论(§七 硬性要求) ----
st.subheader("状态对照")
st.markdown(
    f"**AI 助手状态:{agent_exit_simple(agent.get('exit_status'))}**"
    "(这只是 AI 的结束方式,不代表任务成功)"
)
st.markdown(
    f"**最终系统结论:{verdict_icon(verdict)} {verdict_simple(verdict)}**"
    "(由独立测试与最终判定产生,AI 的自述不参与)"
)

# ---- 用量(简单模式不出现 Token 概念,P0.5) ----
st.subheader("本次用量")
if is_tech():
    u1, u2, u3 = st.columns(3)
    u1.metric("AI 对话轮数", str(agent.get("model_calls", "—")))
    u2.metric("执行命令数", str(agent.get("commands", "—")))
    u3.metric("Tokens(入/出)", (
        f"{agent['input_tokens']:,} / {agent['output_tokens']:,}"
        if agent.get("input_tokens") is not None else "—"))
else:
    u1, u2 = st.columns(2)
    u1.metric("AI 对话轮数", str(agent.get("model_calls", "—")))
    u2.metric("执行命令数", str(agent.get("commands", "—")))

# ---- 执行记录:仅技术模式渲染(P0.5) ----
if is_tech():
    with tech_expander("查看技术详情(执行记录 Trace)"):
        st.caption("执行记录 = 每一步动作的防篡改哈希链(tamper-evident,非 tamper-proof)。")
        st.dataframe(
            facts.trace_preview(case, limit=100), width="stretch", hide_index=True, height=280
        )

if st.button("查看结果报告", type="primary"):
    st.switch_page("pages/case_view.py")
