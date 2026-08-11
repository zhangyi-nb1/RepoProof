"""宿主任务 T1–T4 启动台(TESTPLAN-V2)。

用户正式 run 的 UI 入口(常设工作流:用户测试都在 UI 进行)。
v2(2026-08-09 用户决定):模型池内**自由选择、同模型可重复**,每一发
如实入账不挑选;额度=每轮重置(三模型统一,冻结于预注册);
fake 冒烟不计数。任务包内容(需求/oracle/正负控)保持冻结不变。

2026-08-11(用户要求):由 T1 单任务泛化为 T1–T4 选择器,并加"重复发
观察方差"面板。T4 是零模型调用的确定性专项,**没有方差可观察**,
本页只读其台账(见 HOST_TASKS['T4']['why_not_runnable'])。
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from repoproof.ui.services import live_run as _lr
from repoproof.ui.services.facts import repo_root
from repoproof.ui.services.state import mode_toggle_sidebar

st.set_page_config(page_title="宿主任务 T1–T4 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()
st.title("宿主任务 T1–T4:正式 run 启动台")

root = repo_root()

sel = st.radio("选择阶段", list(_lr.HOST_TASKS), horizontal=True)
T = _lr.host_task(sel)
st.caption(T["title"])

# ---- 正在运行:一切让路 ----
info = _lr.active_run(root)
if info and info.get("alive"):
    st.info(
        f"⏳ 正在运行:{info.get('task_id')} · 模型 **{info.get('model')}**"
        f"(后台进程 {info.get('pid')})。宿主级运行通常需要 10-40 分钟;"
        "刷新本页看最新日志。**同时只允许一个运行**。"
    )
    _log = Path(str(info.get("log", "")))
    if _log.exists():
        st.code(_log.read_text(encoding="utf-8", errors="replace")[-1500:]
                or "(启动中……)", language="text")
    st.stop()
if info and info.get("report_ready"):
    st.success(
        f"✅ 上一发已完成:`runs/{info.get('latest_run')}` —— "
        "把这个目录名报给协作 AI 做磁盘取证;结论在「运行进度/结果报告」页可看。"
    )
    _lr.clear_lock_if_done(root)

# ---- T4:只读(确定性专项,无方差) ----
if not T["runnable"]:
    st.warning(f"**{sel} 不能从本页发起**。{T['why_not_runnable']}")
    ledger = root / T["ledger"]
    if ledger.exists():
        rows = [json.loads(x) for x in
                ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
        st.markdown(f"**实验台账**(`{T['ledger']}`,{len(rows)} 行):")
        st.dataframe([{k: r.get(k) for k in
                       ("experiment", "attempt", "verdict", "note")} for r in rows],
                     use_container_width=True, hide_index=True)
    st.markdown("复跑机器钉死(确定性,验证机器未退化):")
    st.code(f".venv/bin/pytest {T['pin_suite']} -q", language="bash")
    st.stop()

# ---- 冻结面与纪律 ----
state = _lr.host_task_state(root, sel)
st.markdown(
    f"- 宿主:**OfferClaw**(副本快照,每 run 一次性会话——宿主副本与主开发"
    f"目录从不被修改)\n"
    f"- 契约(冻结):`{T['contract']}` · 预注册:`{T['prereg']}`\n"
    f"- 规则:模型池内自由选择、可重复;**每一发全部入账不挑选**;"
    f"额度每轮重置;agent 侧 `network=none`(离线)"
)
st.error(
    "⚠️ **批次纪律**:加发属于新批次,TESTPLAN §8 要求**先写预注册**"
    "(冻结模型/发数/停点/判据)再发射。上面那份预注册覆盖的是历史批次;"
    "现在直接发,这些发次在方法学上不受预注册保护——只能作探索性观察,"
    "不能写进正式结论。\n\n"
    "从本页发出的每一发都会在台账里打 `batch=EXPLORATORY_UNPREREGISTERED`,"
    "`count_passes()` **不把它计入阶段闸门**(如实入账、但不充数)。"
)
ack = st.checkbox("我知道这是预注册之外的探索性加发,结果只作观察、不入正式结论")

# ---- 方差面板 ----
st.subheader("重复发与方差")
st.caption(f"只统计当前冻结版 `{T['task_id']}` 的发次。")
if state["older_versions"]:
    _older = " / ".join(f"`{k}` {n} 发" for k, n in
                        sorted(state["older_versions"].items()))
    st.caption(f"⚠️ 本阶段另有更早任务版本的 "
               f"{sum(state['older_versions'].values())} 发({_older})"
               f"**不在此面板**——不同 task_version 不可互比(TESTPLAN §8),"
               "它们没丢,在「结果报告」页与台账里。")
var = _lr.variance_summary(root, sel)
if not var:
    st.caption("该阶段尚无真实模型发次。")
for v in var:
    st.markdown(
        f"**{v['model']}** · n={v['n']} · 有效 PASS={v['passes']}"
        + (f" · 其中探索性加发 {v['exploratory']} 发(闸门不计)"
           if v["exploratory"] else "")
        + ("" if v["enough_for_variance"] else " · ⚠️ n<3,不足以谈方差")
    )
    st.caption("判决分布(已连接人工再分类):"
               + " / ".join(f"{k}×{n}" for k, n in sorted(v["verdicts"].items())))
    if v["stats"]:
        st.dataframe(
            [{"指标": k, "n": s["n"], "最小": s["min"], "最大": s["max"],
              "均值": s["mean"], "极差": s["spread"]}
             for k, s in v["stats"].items()],
            use_container_width=True, hide_index=True)

# ---- 发射 ----
st.subheader("发起一发")
configured = [m for m in T["models"] if _lr.provider_for_model(m)]
missing = [m for m in T["models"] if m not in configured]
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
run_index = _lr.next_run_index(root, sel, model)
st.caption(
    f"这将是 **{model} 在 {sel} 的第 {run_index} 发**"
    f"(全局第 {state['next_global_order']} 发)。"
    "运行期间请勿改动 OfferClaw 主目录与 RepoProof 仓库——指纹对账会在结束时核验。"
)
if st.button(f"启动:{sel} · {model} · 第 {run_index} 发",
             type="primary", disabled=not ack):
    out = _lr.start_host_run(root, model=model,
                             run_order=state["next_global_order"],
                             run_index=run_index, task_key=sel)
    if out.get("ok"):
        st.success(out.get("note"))
        st.rerun()
    else:
        st.error(out.get("error"))

# ---- 已入账 ----
if state["done"]:
    st.subheader("已入账的正式 run(fake 冒烟不计)")
    st.dataframe(
        [{"run_id": d["run_id"], "模型": d["model"], "系统判决": d["verdict"],
          "有效判决": d["effective_verdict"],
          "批次": "探索性(闸门不计)" if d["exploratory"] else "预注册",
          "人工作废": "是" if d["invalidated"] else ""}
         for d in state["done"]],
        use_container_width=True, hide_index=True)
