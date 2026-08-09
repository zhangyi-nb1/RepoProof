"""宿主任务 T1 — pilot 启动台(TESTPLAN-V2 Phase 1,预注册 v2 规则)。

用户正式 run 的 UI 入口(常设工作流:用户测试都在 UI 进行)。
v2(2026-08-09 用户决定):模型池内**自由选择、同模型可重复**,每一发
如实入账不挑选;额度=每轮重置(三模型统一,冻结于预注册 v2);
fake 冒烟不计数。任务包内容(需求/oracle/正负控)保持冻结不变。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from repoproof.ui.services import live_run as _lr
from repoproof.ui.services.facts import repo_root
from repoproof.ui.services.state import mode_toggle_sidebar

st.set_page_config(page_title="宿主任务 T1 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()
st.title("宿主任务 T1:OfferClaw × fastapi-mcp(校准 pilot · v2 规则)")

root = repo_root()
P = _lr.HOST_PILOT
st.markdown(
    "- 宿主:**OfferClaw**(副本快照,每 run 一次性会话——宿主副本与主开发"
    "目录从不被修改,失败自动'归零'由隔离结构保证)\n"
    "- 目标:`fastapi_mcp @ e5cad13c` · 预算(v2 冻结):≤3 轮,"
    "**每轮** 30 调用 / 80 命令 / 500k 读入 / 50k 输出;补丁 10 文件/800 行\n"
    f"- 规则:模型池内自由选择、可重复到你满意;每一发全部入账不挑选 · 依据 `{P['prereg']}`"
)

info = _lr.active_run(root)
if info and info.get("alive"):
    st.info(
        f"⏳ 正在运行:{info.get('task_id')} · 模型 **{info.get('model')}**"
        f"(后台进程 {info.get('pid')})。宿主级运行通常需要 10-40 分钟;"
        "刷新本页看最新日志。同时只允许一个运行。"
    )
    _log = Path(str(info.get("log", "")))
    if _log.exists():
        st.code(_log.read_text(encoding="utf-8", errors="replace")[-1200:]
                or "(启动中……)", language="text")
    st.stop()
if info and info.get("report_ready"):
    st.success(
        f"✅ 上一发已完成:`runs/{info.get('latest_run')}` —— "
        "把这个目录名报给协作 AI 做磁盘取证;结论在「运行进度/结果报告」页可看。"
    )
    _lr.clear_lock_if_done(root)

state = _lr.host_pilot_state(root)
if state["done"]:
    st.markdown("**已入账的正式 run(fake 冒烟不计):**")
    for d in state["done"]:
        st.markdown(f"- `{d['run_id']}` · {d['model']} · {d['verdict']}")

configured = [m for m in P["models"] if _lr.provider_for_model(m)]
missing = [m for m in P["models"] if m not in configured]
if missing:
    st.caption(f"未配置连接的模型(不可选):{', '.join(missing)}——需要时经 "
               "`scripts/run_ui_live.sh` 环境补齐。")
if not configured:
    st.error("没有任何已配置连接的模型(REPOPROOF_*)。请用 `scripts/run_ui_live.sh` "
             "启动工作台——密钥只进进程环境,不落盘、不显示。")
    st.stop()

model = st.selectbox(
    "选择本发模型(池内自由选择,可对同一模型重复测试)",
    configured,
    format_func=lambda m: f"{m} · 已跑 {state['by_model'].get(m, 0)} 发",
)
run_index = state["by_model"].get(model, 0) + 1
st.caption(
    f"这将是 **{model} 的第 {run_index} 发**(全局第 {state['next_global_order']} 发)。"
    "运行期间请勿改动 OfferClaw 主目录与 RepoProof 仓库——指纹对账会在结束时核验。"
)
if st.button(f"启动:{model} · 第 {run_index} 发", type="primary"):
    out = _lr.start_host_run(root, model=model,
                             run_order=state["next_global_order"],
                             run_index=run_index)
    if out.get("ok"):
        st.success(out.get("note"))
        st.rerun()
    else:
        st.error(out.get("error"))
