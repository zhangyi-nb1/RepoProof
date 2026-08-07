"""结果报告 — 第一屏只回答:能不能用 / 为什么 / 下一步。

简单模式:通俗结论 + 四项检查 + AI 修改 + 下载。
技术模式 / 「查看技术详情」:原始 verifier 输出、哈希、枚举、Trace。
「核对判定」按钮直接调用 Core 的 demo_verify;UI 不复算判定逻辑。
"""

from __future__ import annotations

import streamlit as st

from repoproof.runner.demo import CASES
from repoproof.ui.presenters.glossary import (
    FOUR_CHECKS,
    TERM,
    agent_exit_simple,
    dash,
    failed_node_hint,
    failure_owner_zh,
    replay_mode_zh,
    verdict_icon,
    verdict_next,
    verdict_simple,
    verdict_zh,
)
from repoproof.ui.services import actions, facts
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander

st.set_page_config(page_title="结果报告 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()
st.title("结果报告")

_names = {
    "frontmatter-v2-pass": "文档元数据解析(python-frontmatter)— 成功案例",
    "chonkie-agent-fail": "文本分块(Chonkie)— 未通过案例",
    "bm25-agent-fail": "检索排序(rank_bm25)— 未通过案例",
}
_valid = list(CASES)
_default = st.query_params.get("case") or st.session_state.get("case") or "frontmatter-v2-pass"
if _default not in _valid:
    _default = "frontmatter-v2-pass"
case = st.selectbox("选择任务", _valid, index=_valid.index(_default), format_func=lambda c: _names[c])
st.query_params["case"] = case
st.session_state["case"] = case

report = facts.load_report(case)
manifest = facts.load_run_manifest(case)
srow = facts.summary_row(facts.CASE_TO_SUMMARY[case]) or {}
agent = manifest.get("agent") or report.get("agent") or {}
verdict = report.get("final_verdict") or report.get("verdict")

# ================= 第一屏:结论 / 为什么 / 下一步 =================
with st.container(border=True):
    st.caption("在当前测试条件下(固定版本、固定成功标准):")
    st.markdown(f"## {verdict_icon(verdict)} {verdict_simple(verdict)}")
    if verdict == "PASS_ADAPTED":
        why = "四项检查全部通过:目标功能可用、原项目不受影响、操作合规、并且在全新环境复测成功。"
    elif verdict == "FAIL":
        n_fail = len(report.get("capability_failed_tests") or [])
        why = f"独立验收中仍有 {n_fail} 项测试未通过,未达到成功标准(即使 AI 已完成大部分工作)。"
    else:
        why = "详见下方检查明细。"
    st.markdown(f"**为什么**:{why}")
    st.markdown(f"**你的下一步**:{verdict_next(verdict)}")

# ---- AI 状态 ≠ 系统结论 ----
st.caption(
    f"AI 助手状态:**{agent_exit_simple(agent.get('exit_status'))}** · "
    f"最终结论:**{verdict_simple(verdict)}** —— AI 的自述不参与判定。"
)

# ================= 四项通俗检查 =================
st.subheader("四项检查")
_check_pass = {
    "capability": (srow.get("capability_passed") == srow.get("capability_total")
                   and srow.get("capability_total") is not None),
    "regression": (srow.get("regression_passed") == srow.get("regression_total")
                   and srow.get("regression_total") is not None),
    "policy": srow.get("policy_result") == "PASS",
    "replay": srow.get("replay_mode") == "clean_adoption" and srow.get("replay_result") == "PASS",
}
cols = st.columns(4)
for col, (key, label, _term) in zip(cols, FOUR_CHECKS, strict=True):
    ok = _check_pass[key]
    if key == "replay" and not ok and srow.get("replay_result") == "PASS":
        text, icon = "已复现失败(确认问题真实存在)", "❌"
    else:
        text, icon = ("通过", "✅") if ok else ("未通过", "❌")
    with col, st.container(border=True):
        st.markdown(f"**{label}**")
        st.markdown(f"{icon} {text}")

# ================= AI 修改了什么 =================
st.subheader("AI 修改了什么")
src = facts.adapter_source(case)
if src:
    n_lines = len(src.splitlines())
    st.markdown(f"AI 写了 **1 个适配文件,共 {n_lines} 行**;你的项目原有文件没有被修改。")
    with st.expander("查看适配代码"):
        st.code(src, language="python")
else:
    st.markdown("本次记录中没有适配代码文件。")

# ================= 使用前注意(P1.3,正向案例) =================
if verdict in ("PASS_ADAPTED", "PASS_DIRECT"):
    st.subheader("使用前注意")
    st.markdown(
        "- 合入前**通读一遍适配代码**——最终采用决定在你,不在系统\n"
        "- 结论只对**当前锁定的目标仓库版本**成立;升级版本需要重新验证\n"
        "- 确认目标仓库的**开源许可证**与你的项目兼容\n"
        "- 建议先在测试分支合入,跑一遍你自己的测试再上主分支"
    )

# ================= 哪些问题没解决(FAIL 时默认展开) =================
failed = report.get("capability_failed_tests") or []
if failed:
    st.subheader("哪些问题没解决")
    for node in failed:
        st.markdown(f"- ❌ {failed_node_hint(node)}")
    ftype = srow.get("failure_type")
    if ftype:
        st.markdown(f"**主要责任方**:{failure_owner_zh(ftype)}")
    if is_tech():
        with tech_expander("查看原始测试名称(技术详情)"):
            for node in failed:
                st.code(node, language="text")
            if ftype:
                st.markdown(f"失败类型(内部枚举):`{ftype}`")

# ================= 下载 =================
st.subheader("下载结果")
st.download_button(
    label="下载代码 + 报告(ZIP)",
    data=facts.bundle_zip_bytes(case),
    file_name=f"{facts.evidence_dir(case).name}.zip",
    mime="application/zip",
    type="primary",
    key=f"dl-bundle-{case}",
)
st.caption(f"即{TERM['adoption_bundle']}:适配代码、结果报告、执行记录与全部检查输出,可离线复核。")
with st.expander("单独下载某个文件"):
    for label, path in facts.evidence_files(case):
        st.download_button(label=label, data=path.read_bytes(), file_name=path.name,
                           key=f"dl-{case}-{path.name}")

# ================= 核对与复测(调用 Core,零模型) =================
st.subheader("不放心?自己核对")
c1, c2 = st.columns(2)
with c1:
    if st.button("核对最终判定(用检查数据重新推导结论)"):
        out = actions.verify_case(case)
        ok = out.get("verdict_recomputation_matches")
        if ok:
            st.success(f"核对一致:根据检查数据重新推导,结论同样是「{verdict_simple(out['recomputed_verdict'])}」。"
                       "整个核对没有调用任何 AI 模型。")
        else:
            st.error("核对不一致——请展开技术详情查看原始数据。")
        if is_tech():
            with tech_expander("查看核对明细(技术详情)"):
                st.json(out["inputs_to_gate"])
                st.json({"recorded": out["recorded_verdict"], "recomputed": out["recomputed_verdict"],
                         "trace_sha256": out["trace_sha256"],
                         "verifier_result_hashes": out["verifier_result_hashes"]})
with c2:
    if CASES[case]["kind"] == "positive":
        if st.button("在全新环境里再测一遍(约 1 分钟,需要 Docker)"):
            with st.status("正在全新隔离环境中复测……", expanded=True) as status:
                out = actions.replay_case(case)
                if out.get("replay_ok"):
                    status.update(label="复测完成", state="complete")
                    st.success(f"✅ 复测通过:{out['capability']} 项测试在全新环境中再次全部通过,"
                               "全程零 AI 调用——结果由代码本身承载,不依赖当时的 AI 会话。")
                else:
                    status.update(label="复测未通过", state="error")
                    st.error("复测未通过——打开左侧「显示技术详情」查看原始输出。")
                    if is_tech():
                        with tech_expander():
                            st.json(out)
    else:
        st.caption("未通过案例的问题已在干净环境中复现过(见上方「新环境中是否还能运行」)。")

# ================= 技术详情(全部原始字段;仅技术模式渲染,P0.5) =================
if is_tech():
    with tech_expander("查看技术详情(原始字段与哈希)"):
        st.markdown(f"""
    | 字段 | 值 | 中文说明 |
    |---|---|---|
    | final_verdict | `{dash(verdict)}` | 最终判定:{verdict_zh(verdict)} |
    | task_id | `{dash(report.get("task_id"))}` | 任务标识 |
    | run_id | `{dash(report.get("run_id"))}` | 本次运行标识 |
    | capability | `{dash(report.get("capability"))}` | {TERM["capability_verification"]}原始输出 |
    | regression | `{dash(report.get("regression"))}` | {TERM["host_regression"]}原始输出 |
    | policy | `{dash(report.get("policy"))}` | {TERM["policy"]}原始输出 |
    | replay | `{dash(report.get("replay"))}` | {replay_mode_zh(srow.get("replay_mode"))}原始输出 |
    | agent.exit_status | `{dash(agent.get("exit_status"))}` | AI 助手结束方式(不参与判定) |
    | task_package_root | `{dash((report.get("task_package_root_hash") or "")[:16])}…` | 任务包指纹 |
    | adaptation_root | `{dash((report.get("adaptation_root") or "")[:16])}…` | 适配产物指纹 |
    | trace_sha256 | `{dash((report.get("final_trace_sha256") or "")[:16])}…` | 执行记录链指纹 |
    | model | `{dash(srow.get("model"))}` | 使用的模型 |
    | tokens | `{dash(agent.get("input_tokens"))}/{dash(agent.get("output_tokens"))}` | 用量(入/出) |
    """)
        st.markdown("**执行记录预览(前 100 行)**:")
        st.dataframe(facts.trace_preview(case, limit=100), width="stretch", hide_index=True, height=260)
