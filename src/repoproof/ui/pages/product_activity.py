"""Current Product Mode background activity and logs."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from repoproof.ui.product_theme import apply_product_theme, hero, section_intro
from repoproof.ui.services import live_run

st.set_page_config(page_title="运行活动 · RepoProof Studio", page_icon="🕒", layout="wide")
apply_product_theme()

hero(
    "每一步都看得见",
    "这里显示 Product Mode 最近一次后台任务。日志只帮助理解过程，最终结论仍来自独立验证、干净重放和运营状态账。",
    kicker="Bounded execution",
)

job = live_run.product_job_state()
if not job:
    st.info("当前没有 Product Mode 后台任务。")
    if st.button("创建一个工具", type="primary"):
        st.switch_page("pages/tool_onboarding.py")
    st.stop()

state = "正在运行" if job.get("alive") else ("完成" if job.get("ok") else "未完成")
c1, c2, c3, c4 = st.columns(4)
c1.metric("状态", state)
c2.metric("阶段", str(job.get("kind") or "—"))
c3.metric("任务", str(job.get("label") or "—"))
c4.metric("进程", str(job.get("pid") or "—"))

if job.get("alive"):
    st.progress(None, text="后台执行中；刷新页面可获取最新状态。")
elif job.get("ok"):
    st.success(job.get("note") or "任务已完成。")
else:
    st.error(job.get("note") or "任务没有形成预期产物，请查看日志。")

section_intro("过程日志", "它不是 PASS 的来源；模型的完成声明也不会在这里变成系统结论。")
log = Path(str(job.get("log") or ""))
if log.is_file():
    text = log.read_text(encoding="utf-8", errors="replace")
    st.code(text[-12000:] or "（任务刚启动，暂无输出）", language="text")
else:
    st.caption("日志文件尚未创建。")

with st.expander("技术信息"):
    safe = {k: v for k, v in job.items() if k not in {"env"}}
    st.json(safe)
