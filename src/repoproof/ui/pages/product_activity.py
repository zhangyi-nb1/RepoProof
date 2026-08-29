"""Current Product Mode background activity and logs."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from repoproof.ui.product_theme import apply_product_theme, hero, section_intro
from repoproof.ui.services import product_jobs
from repoproof.ui.services.product_mode import list_tools, tool_root

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

worker_state = {
    "RUNNING": "正在运行",
    "SUCCEEDED": "已完成",
    "FAILED": "失败",
    "INTERRUPTED": "已中断",
}.get(str(job.get("status")), "状态异常")
semantic = product_jobs.product_job_action_result(job)
result = semantic.get("result") if semantic.get("ok") else None

current_operational = "尚未形成"
current_health = "尚未导出"
core_error = ""
if result and result.get("tool_name"):
    library = list_tools(Path(job.get("dest_root") or tool_root()))
    if library.get("registry_error") or library.get("release_error"):
        current_operational = "状态不可读取"
        current_health = "状态不可读取"
        core_error = str(
            library.get("registry_error") or library.get("release_error")
        )
    else:
        row = next(
            (
                item for item in library.get("tools", [])
                if item.get("name") == result.get("tool_name")
            ),
            None,
        )
        if row:
            current_operational = str(row.get("operational_status") or "REVIEW_REQUIRED")
            current_health = str(row.get("health") or "UNKNOWN")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Worker", worker_state)
c2.metric("Pipeline", str((result or {}).get("pipeline_verdict") or "尚未形成"))
c3.metric("Operational", current_operational)
c4.metric("Package", current_health)
st.caption(
    f"动作：{job.get('action') or job.get('kind') or '—'} · "
    f"任务：{job.get('label') or '—'}。Worker 只描述进程，不代表验证或发布结论。"
)

if job.get("alive"):
    # st.progress 只收 int[0,100]/float[0,1] —— 传 None 会当场抛
    # StreamlitAPIException("Progress Value has invalid type: NoneType"),
    # 也就是**任务正在跑的时候**这一屏必炸(2026-08-27 mypy 首次覆盖 ui
    # 时揪出)。构建没有可靠的百分比进度,给个不谎报进度的运行态提示。
    st.info("⏳ 后台执行中；刷新页面可获取最新状态。")
elif job.get("ok"):
    st.success(job.get("note") or "Worker 已完成；请以下方结构化结果为准。")
else:
    st.error(job.get("note") or "Worker 未形成预期产物。")
    if job.get("error_code"):
        st.caption(f"错误码：`{job['error_code']}`")

log_result = product_jobs.read_product_job_log(job)
st.markdown("#### 结构化动作结论")
if result:
    r1, r2 = st.columns([1.2, 1])
    with r1:
        st.write(f"**执行路线：** `{result.get('route') or '—'}`")
        st.write("**是否调用模型：** " + ("是" if result.get("agent_invoked") else "否"))
        st.write(f"**Pipeline：** `{result.get('pipeline_verdict') or '—'}`")
        st.write(f"**历史结论：** `{result.get('historical_verdict') or '—'}`")
        if result.get("exported_path"):
            st.success("产物已导出；当前是否可用仍以上方 Operational 为准。")
    with r2:
        st.write(f"**终止码：** `{result.get('product_stop_code') or '—'}`")
        st.write(f"**失败责任：** `{result.get('failure_owner') or '—'}`")
        reason_codes = [str(code) for code in result.get("reason_codes") or []]
        if reason_codes:
            st.write("**理由码：** " + ", ".join(f"`{code}`" for code in reason_codes))
        if result.get("recommended_action"):
            st.info(str(result["recommended_action"]))
    if result.get("run_id"):
        st.caption(f"运行证据：`{result['run_id']}`。结论来自独立验证，不来自日志或 Agent 自述。")
else:
    code = str(semantic.get("error_code") or "ACTION_RESULT_UNAVAILABLE")
    message = str(semantic.get("error") or "结构化动作结果不可读取。")
    if job.get("alive") and code == "ACTION_RESULT_PENDING":
        st.info("动作仍在执行，Pipeline 结论尚未形成。")
    else:
        st.error(f"{code}：{message}")
        st.caption("结果缺失或损坏时 fail closed；日志不会被用来推断 READY 或 ACTIVE。")
if core_error:
    st.error(f"CORE_STATUS_UNAVAILABLE：{core_error}")

with st.expander("过程日志（仅供排查）"):
    section_intro("过程日志", "它不是 PASS 的来源；模型的完成声明不会在这里变成系统结论。")
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
