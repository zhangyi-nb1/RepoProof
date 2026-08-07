"""运行进度 — 通俗九阶段视图。

本版本无实时任务;选择一个已完成的真实案例,按九阶段回顾其执行,
并常驻区分「AI 助手状态」与「最终系统结论」。技术执行记录默认折叠。
"""

from __future__ import annotations

import streamlit as st

from repoproof.runner.demo import CASES
from repoproof.ui.presenters.glossary import (
    STAGES_SIMPLE,
    agent_exit_simple,
    verdict_icon,
    verdict_simple,
)
from repoproof.ui.services import facts
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander

st.set_page_config(page_title="运行进度 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()
st.title("运行进度")

st.info("🟡 当前没有正在运行的任务(本版本为只读演示版)。下面可以回顾一次已完成任务的全过程。")

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

# ---- 九阶段(已完成运行 → 全部走完) ----
st.subheader("执行阶段")
done = len(STAGES_SIMPLE)
for i, stage in enumerate(STAGES_SIMPLE, 1):
    st.markdown(f"{'✅' if i < done else verdict_icon(verdict)} 第 {i} 步 · {stage}")
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

if agent.get("exit_status") == "Submitted" and verdict == "FAIL":
    st.warning("注意:AI 助手已提交 ≠ 成功。本例中独立测试未全部通过,最终结论是「当前条件下不建议采用」。")

# ---- 用量(简单) ----
st.subheader("本次用量")
u1, u2, u3 = st.columns(3)
u1.metric("AI 对话轮数", str(agent.get("model_calls", "—")))
u2.metric("执行命令数", str(agent.get("commands", "—")))
u3.metric("AI 使用额度(字符量级)", (
    f"读 {agent['input_tokens']:,} / 写 {agent['output_tokens']:,}"
    if agent.get("input_tokens") is not None else "—"))

# ---- 技术执行记录(折叠) ----
with tech_expander("查看技术详情(执行记录 Trace)"):
    if is_tech():
        st.caption("执行记录 = 每一步动作的防篡改哈希链(tamper-evident,非 tamper-proof)。")
    st.dataframe(facts.trace_preview(case, limit=100), width="stretch", hide_index=True, height=280)

if st.button("查看结果报告", type="primary"):
    st.switch_page("pages/case_view.py")
