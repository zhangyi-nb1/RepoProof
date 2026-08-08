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
_locals = facts.local_runs()
if _locals:
    from repoproof.ui.presenters.glossary import verdict_icon as _vic0
    from repoproof.ui.presenters.glossary import verdict_simple as _vsi0

    for _ln in _locals:
        _m0 = facts.local_run_meta(_ln)
        _names[_ln] = (f"你的运行:{_ln} · {facts.run_ts_human(_ln)} · "
                       f"{facts.run_mode_zh(_m0['mode'])} · {_m0.get('model') or '—'} · "
                       f"{_vic0(_m0['verdict'])}{_vsi0(_m0['verdict'])}")
_valid = [*_locals, *list(CASES)]
_default = st.session_state.get("case") or _valid[0]
if _default not in _valid:
    _default = _valid[0]
case = st.selectbox(
    "选择要回顾的任务", _valid, index=_valid.index(_default), format_func=lambda c: _names[c]
)
st.session_state["case"] = case

if case in _locals:
    # ---- 你的本地真实运行:持久回看(不依赖运行锁) ----
    from repoproof.ui.presenters.glossary import verdict_icon as _vic
    from repoproof.ui.presenters.glossary import verdict_simple as _vs2

    _lr_data = facts.load_local_run(case)
    _rep, _man = _lr_data["report"], _lr_data["manifest"]
    _ag = _man.get("agent") or {}
    _v2 = _rep.get("final_verdict")
    st.markdown(f"## {_vic(_v2)} {_vs2(_v2)}")
    st.markdown(
        f"**AI 助手状态:{agent_exit_simple(_ag.get('exit_status'))}**"
        "(结束方式不代表结论)  \n"
        f"**最终系统结论:{_vs2(_v2)}**(由独立验证产生)"
    )
    if _ag.get("exit_status") == "TokenBudgetExhausted":
        st.warning("本次失败原因:AI 使用额度在完成前耗尽"
                   f"(读入量 {_ag.get('input_tokens', 0):,}(字符量级)超过合同上限),"
                   "验收未能运行。额度限制是合同的一部分——防止无界消耗。")
    _cap = _rep.get("capability")
    st.markdown(f"- 目标功能验收:{_cap if _cap else '—'}\n"
                f"- AI 对话轮数:{_ag.get('model_calls', '—')} · 执行命令:{_ag.get('commands', '—')}\n"
                f"- 本地目录:`{_lr_data['dir']}`(适配代码在 adaptation/ 内)")
    # ---- Gate C:导出可移交的结果包(EXPORT_ONLY,不碰你的项目) ----
    from pathlib import Path as _P2
    _bundle_dir = _P2(_lr_data["dir"]) / "integration_bundle"
    if _bundle_dir.is_dir():
        st.success(f"📦 结果包已导出:`{_bundle_dir}`(适配代码/公开测试/依赖锁定/集成指南/报告)")
    elif st.button("导出结果包(适配代码 + 集成指南 + 报告)"):
        _out_b = _lr.export_bundle_for_run(_root2, case)
        if _out_b.get("ok"):
            st.success(f"📦 已导出:`{_out_b['bundle_dir']}`——失败的运行同样导出当前产物与失败报告。")
        else:
            st.error(f"导出失败:{_out_b.get('error')}")
    st.caption("说明:导出只写 runs/ 下的运行目录,不会写入你的项目;隐藏验收样例永远不包含在结果包里。")

    # ---- Gate E:三级安全写入(仅 PASS 结果;fixture 已验证,首次真实使用请先拿不重要的项目试) ----
    if _bundle_dir.is_dir() and str(_v2).startswith("PASS"):
        with st.expander("应用到我的项目(三级安全写入:副本 → 预览 → 确认)"):
            st.caption("流程:先在你项目的临时副本上落位并生成改动清单;你看过清单与改动、"
                       "逐字确认后才写回;写回可一键回滚。项目在确认前保持只读。")
            _proj_in = st.text_input("你的项目路径(将先做只读分析与临时副本)",
                                     key="ap_proj", placeholder="~/my_project 或一个空目录")
            if st.button("第 1 步:创建临时副本并生成改动清单"):
                from repoproof.ui.services import apply_service
                _stg = apply_service.stage(_root2, _proj_in, str(_bundle_dir))
                if _stg.get("ok"):
                    st.session_state["ap_state"] = _stg
                    st.success("已在临时副本落位;下方核对改动。你的项目尚未被修改。")
                else:
                    st.error(_stg.get("error"))
            _aps = st.session_state.get("ap_state")
            if _aps and _aps.get("ok"):
                st.markdown(f"**将新增文件**:{_aps['created'] or '无'}  \n"
                            f"**将修改文件**:{_aps['modified'] or '无'}  \n"
                            f"**依赖变化**:{_aps['deps'] or '无'}  \n"
                            f"**将执行的命令**:无(只落文件,依赖安装由你按集成指南执行)  \n"
                            f"**回滚方式**:逐文件恢复(preimage 备份 + 哈希校验,可反复执行)")
                st.code(_aps["diff"], language="text")
                _c1 = st.checkbox("我已查看将写入的文件清单", key="ap_c1")
                _c2 = st.checkbox("我已查看上方改动预览", key="ap_c2")
                from repoproof.adoption.delivery.apply import CONFIRM_TOKEN
                _tok = st.text_input(f"第 2 步:逐字输入确认语——{CONFIRM_TOKEN}", key="ap_tok")
                if st.button("第 3 步:写入我的项目", type="primary",
                             disabled=not (_c1 and _c2)):
                    from repoproof.ui.services import apply_service
                    _res = apply_service.apply(_root2, _aps, viewed_files=_c1,
                                               viewed_diff=_c2, token=_tok)
                    (st.success if _res.get("ok") else st.error)(
                        _res.get("note") or _res.get("error"))
                    if _res.get("ok"):
                        st.session_state["ap_applied"] = _res
                _apd = st.session_state.get("ap_applied")
                if _apd and st.button("回滚上次写入(恢复到写入前)"):
                    from repoproof.ui.services import apply_service
                    _rb = apply_service.roll_back(_root2, _apd)
                    (st.success if _rb.get("ok") else st.error)(
                        _rb.get("note") or _rb.get("error"))
    if is_tech():
        with tech_expander("查看技术详情(report 原始字段)"):
            st.json(_rep)
    st.stop()

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
