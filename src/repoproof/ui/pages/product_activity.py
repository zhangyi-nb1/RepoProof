"""Current Product Mode background activity and logs."""

from __future__ import annotations

import streamlit as st

from repoproof.ui.product_theme import apply_product_theme, hero, section_intro
from repoproof.ui.services import product_jobs

st.set_page_config(page_title="运行活动 · RepoProof Studio", page_icon="🕒", layout="wide")
apply_product_theme()

hero(
    "每一步都看得见",
    "这里显示 Product Mode 最近一次后台任务。日志只帮助理解过程，最终结论仍来自独立验证、干净重放和运营状态账。",
    kicker="Bounded execution",
)

job = product_jobs.product_job_state()
if not job:
    st.info("当前没有 Product Mode 后台任务。")
    if st.button("创建一个工具", type="primary"):
        st.switch_page("pages/tool_onboarding.py")
    st.stop()

state = {
    "RUNNING": "正在运行",
    "SUCCEEDED": "已完成",
    "FAILED": "失败",
    "INTERRUPTED": "已中断",
}.get(str(job.get("status")), "状态异常")
c1, c2, c3, c4 = st.columns(4)
c1.metric("状态", state)
c2.metric("阶段", str(job.get("action") or job.get("kind") or "—"))
c3.metric("任务", str(job.get("label") or "—"))
c4.metric("进程", str(job.get("pid") or "—"))

if job.get("alive"):
    st.progress(None, text="后台执行中；刷新页面可获取最新状态。")
elif job.get("ok"):
    st.success(job.get("note") or "任务已完成。")
else:
    st.error(job.get("note") or "任务没有形成预期产物，请查看日志。")
    if job.get("error_code"):
        st.caption(f"错误码：`{job['error_code']}`")

# Gate 4:构建结论人读卡(路线/终止码/归因)—— 从日志尾部结论 JSON
# 确定性投影;解析不出就只显示原始日志,不猜。
log_result = product_jobs.read_product_job_log(job)
if str(job.get("kind") or "") == "tool-build" and log_result.get("ok"):
    from repoproof.ui.services.product_mode import (
        build_conclusion,
        parse_build_summary,
    )

    summary = parse_build_summary(log_result.get("text") or "")
    if summary:
        c = build_conclusion(summary)
        st.markdown("#### 构建结论")
        r1, r2 = st.columns([1.2, 1])
        with r1:
            st.write(f"**执行路线：** {c['route_label']}")
            st.write("**是否调用模型：** " + ("否(零模型)" if not c["agent_invoked"] else "是"))
            st.write(f"**结论：** {c['verdict'] or '—'}")
            if c["exported"]:
                st.success(f"已导出:`{c['exported']}`")
        with r2:
            st.write(f"**终止码：** `{c['product_stop_code'] or '—'}`")
            st.write(f"**含义：** {c['stop_label']}")
            if c["failure_owner"]:
                st.write(f"**失败归属：** {c['failure_owner']}")
            if c["reason_codes"]:
                st.write("**理由码：** " + ", ".join(f"`{x}`" for x in c["reason_codes"]))
        if c["run_id"]:
            st.caption(f"运行证据:`{c['run_id']}`(结论来自独立验证,不来自本页日志)")

section_intro("过程日志", "它不是 PASS 的来源；模型的完成声明也不会在这里变成系统结论。")
if log_result.get("ok"):
    st.code(log_result.get("text") or "（任务刚启动，暂无输出）", language="text")
else:
    st.caption(log_result.get("error") or "日志文件尚未创建。")

with st.expander("技术信息（人读字段 + 原始 JSON）"):
    safe = {k: v for k, v in job.items() if k not in {"env"}}
    labels = {
        "status": "状态", "action": "阶段", "kind": "类型", "label": "任务",
        "pid": "进程", "alive": "仍在运行", "ok": "是否成功", "note": "结果说明",
        "error_code": "错误码", "started_at": "开始时间", "finished_at": "结束时间",
        "log_path": "日志文件", "draft_dir": "草稿目录", "dest_root": "工具库位置",
    }
    st.dataframe(
        [{"字段": labels.get(k, k), "值": "—" if v is None else str(v)}
         for k, v in safe.items()],
        hide_index=True,
        use_container_width=True,
    )
    st.caption("以下为同一信息的原始 JSON（供排查与审计）:")
    st.json(safe)
