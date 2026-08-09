"""宿主任务 T1 — 预注册 pilot 启动台(TESTPLAN-V2 Phase 1)。

用户正式 run 的 UI 入口(常设工作流:用户测试都在 UI 进行,2026-08-09
用户重申)。顺序由预注册冻结,本页**不提供**改序/改模型/改预算手段;
fake 冒烟不计入顺序。任务包为手写任务工程产物(不经样例向导),本页
只负责"按预注册启动 + 观察"。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from repoproof.ui.services import live_run as _lr
from repoproof.ui.services.facts import repo_root
from repoproof.ui.services.state import mode_toggle_sidebar

st.set_page_config(page_title="宿主任务 T1 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()
st.title("宿主任务 T1:OfferClaw × fastapi-mcp(校准 pilot)")

root = repo_root()
P = _lr.HOST_PILOT
st.markdown(
    "- 宿主:**OfferClaw**(副本 `~/RepoProofBench/offerclaw-t1-fastapi-mcp`,"
    "主开发目录有硬护栏 + 运行前后指纹对账双保险)\n"
    "- 目标:`fastapi_mcp @ e5cad13c` · 预算(冻结):≤3 轮 / 24 调用 / "
    "60 命令 / 30 分钟\n"
    f"- 预注册顺序(冻结,执行时不得调整):① {P['order'][0]} ② {P['order'][1]}"
    f" · 依据 `{P['prereg']}`"
)

info = _lr.active_run(root)
if info and info.get("alive"):
    st.info(
        f"⏳ 正在运行:{info.get('task_id')} · 模型 **{info.get('model')}**"
        f"(后台进程 {info.get('pid')})。宿主级运行通常需要 10-40 分钟;"
        "刷新本页看最新日志。"
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
    st.markdown("**已完成的正式 run(fake 冒烟不计):**")
    for d in state["done"]:
        st.markdown(f"- `{d['run_id']}` · {d['model']} · {d['verdict']}")

nxt = state["next_model"]
if nxt is None:
    st.success(
        "🎯 预注册的两发 pilot 已全部完成。停点规则:双方均首轮通过 → "
        "T1=CALIBRATION_ONLY 直接进 T2;有区分度 → 与协作 AI 确认补齐方案"
        "(补齐需重新预注册)。"
    )
    st.stop()

prov = _lr.provider_for_model(nxt)
st.subheader(f"本发应跑:第 {state['next_order']} 发 · {nxt}")
if prov is None:
    st.error(
        f"当前工作台环境缺少 **{nxt}** 的连接配置(REPOPROOF_*)。"
        "请用 `scripts/run_ui_live.sh` 启动工作台——它从仓库 .env 注入连接信息,"
        "密钥只进进程环境,不落盘、不显示。"
    )
    st.stop()
st.caption(
    "模型按预注册顺序自动锁定(本页无改序手段,批次纪律)。"
    "运行期间请勿改动 OfferClaw 主目录与 RepoProof 仓库——指纹对账会在结束时核验。"
)
if st.button(f"启动第 {state['next_order']} 发正式 run({nxt})", type="primary"):
    out = _lr.start_host_run(root, model=nxt, run_order=state["next_order"])
    if out.get("ok"):
        st.success(out.get("note"))
        st.rerun()
    else:
        st.error(out.get("error"))
