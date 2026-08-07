"""结果与证据 — 内置案例的完整只读视图。

事实源:Evidence Bundle(report / run_manifest / trace / adapter)+
benchmark_summary.json。UI 不复算业务逻辑;「验证 Bundle」直接调用
Core 的 demo_verify(gate 决策表复算),「无模型重放」调用 demo_replay。
"""

from __future__ import annotations

import streamlit as st

from repoproof.runner.demo import CASES
from repoproof.ui.presenters.zh import (
    agent_exit_zh,
    dash,
    failure_owner_zh,
    replay_mode_zh,
    verdict_zh,
)
from repoproof.ui.services import actions, facts

st.set_page_config(page_title="结果与证据 · RepoProof Studio", page_icon="🔍", layout="wide")
st.title("🔍 结果与证据")

# ---- 案例选择:query_params 优先(刷新不丢),其次 session_state ----
_valid = list(CASES)
_default = st.query_params.get("case") or st.session_state.get("case") or "frontmatter-v2-pass"
if _default not in _valid:
    _default = "frontmatter-v2-pass"
case = st.selectbox(
    "选择案例", _valid, index=_valid.index(_default),
    format_func=lambda c: f"{c} — {CASES[c]['headline'][:44]}",
)
st.query_params["case"] = case
st.session_state["case"] = case

report = facts.load_report(case)
manifest = facts.load_run_manifest(case)
srow = facts.summary_row(facts.CASE_TO_SUMMARY[case]) or {}
verdict = report.get("final_verdict") or report.get("verdict")

# ---- 五个核心卡 ----
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("最终 Verdict", verdict_zh(verdict), delta=verdict, delta_color="off")
k2.metric("Capability", dash(
    f"{srow.get('capability_passed')}/{srow.get('capability_total')}"
    if srow.get("capability_passed") is not None else None))
k3.metric("宿主回归", dash(
    f"{srow.get('regression_passed')}/{srow.get('regression_total')}"
    if srow.get("regression_passed") is not None else None))
k4.metric("Policy", dash(srow.get("policy_result")))
k5.metric("重放", replay_mode_zh(srow.get("replay_mode")))

agent = (manifest.get("agent") or report.get("agent") or {})
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("模型调用", dash(agent.get("model_calls")))
m2.metric("执行命令", dash(agent.get("commands")))
m3.metric("Tokens(入/出)", (
    f"{agent['input_tokens']:,} / {agent['output_tokens']:,}"
    if agent.get("input_tokens") is not None else "—"))
m4.metric("模型耗时", (
    f"{(manifest.get('timings') or {}).get('agent_model_call_s', 0):.0f}s"
    if (manifest.get("timings") or {}).get("agent_model_call_s") is not None else "—"))
m5.metric("Adapter 规模", (
    f"{srow.get('adaptation_files')} 文件 / {srow.get('adaptation_lines')} 行"
    if srow.get("adaptation_lines") else "—"))

# ---- Agent 结束原因 ≠ 最终 Verdict ----
exit_status = agent.get("exit_status")
st.info(
    f"**Agent 结束原因:{agent_exit_zh(exit_status)}(`{dash(exit_status)}`)  ≠  "
    f"系统最终 Verdict:{verdict_zh(verdict)}(`{dash(verdict)}`)** — "
    "Agent 的自述与结束状态从不参与判定;Verdict 只由独立 verifier 结果产生。"
)

# ---- 无模型操作 ----
a1, a2 = st.columns(2)
with a1:
    if st.button("🧾 验证 Bundle(复算 Completion Gate 决策)", key=f"verify-{case}"):
        out = actions.verify_case(case)
        ok = out.get("verdict_recomputation_matches")
        (st.success if ok else st.error)(
            f"复算 Verdict = {verdict_zh(out['recomputed_verdict'])}(`{out['recomputed_verdict']}`) · "
            f"与记录一致:{'是' if ok else '否'} · 模型调用:{out['model_calls']}"
        )
        with st.expander("Gate 输入(来自证据,非叙述)"):
            st.json(out["inputs_to_gate"])
            st.json({"verifier_result_hashes": out["verifier_result_hashes"],
                     "trace_sha256": out["trace_sha256"],
                     "agent_claim_consulted": out["agent_claim_consulted"]})
with a2:
    if CASES[case]["kind"] == "positive":
        if st.button("🔁 无模型重放(全新容器重跑已提交 Adapter)", key=f"replay-{case}"):
            with st.status("正在全新容器中重放…(需要 Docker,约 30–60 秒)", expanded=True) as status:
                out = actions.replay_case(case)
                if out.get("replay_ok"):
                    status.update(label="重放完成", state="complete")
                    st.success(
                        f"Capability {out['capability']}(期望 {out['expected']}) · "
                        f"模型调用:{out['model_calls']} · 容器:{out['container']}"
                    )
                else:
                    status.update(label="重放未通过", state="error")
                    st.error(out)
    else:
        st.caption("负向案例无干净重放:其失败已在失败复现重放中确定性复现(见「重放」标签)。")

# ---- 详情标签页 ----
tabs = st.tabs(["结果概览", "适配产物", "能力验收", "宿主回归", "Policy", "重放", "失败归因", "证据下载"])

with tabs[0]:
    st.markdown(f"""
- **任务**:`{report.get("task_id")}` · Run:`{report.get("run_id")}`
- **目标仓库**:{dash(srow.get("source_repo"))} @ `{dash((srow.get("source_commit") or "")[:12])}`
- **模型**:{dash(srow.get("model"))} · 温度 {dash(report.get("temperature"))} ·
  协议 {dash(report.get("action_protocol"))}
- **判定依据**:{dash("; ".join(report.get("gate_reasons") or []))}
- **TaskPackage Root**:`{dash((report.get("task_package_root_hash") or "")[:16])}…` ·
  **Adaptation Root**:`{dash((report.get("adaptation_root") or "")[:16])}…`
""")
    if CASES[case]["kind"] == "positive":
        st.success(
            "责任分离:确定性输入校验(text=None、缺字段、坏 doc_id)由宿主 "
            "InputContractGuard 完成——不计入 Agent 能力;Agent 负责调用 pinned "
            "上游、旗标拆分、JSON-safe 投影与异常包装。"
        )
    else:
        st.warning("Agent 完成了大部分适配,但完整合同未满足;独立 verifier 拒绝放行,失败已在干净环境确定性复现。")

with tabs[1]:
    src = facts.adapter_source(case)
    if src:
        st.caption(f"Agent 生成的 adapter.py({len(src.splitlines())} 行,冻结于 Adaptation Root)")
        st.code(src, language="python")
    else:
        st.caption("该案例证据中未包含 adapter 文件。")

with tabs[2]:
    st.markdown(f"**Capability verifier 输出**:`{dash(report.get('capability'))}`")
    failed = report.get("capability_failed_tests") or []
    if failed:
        st.markdown("**未通过的验收节点(held-out oracle):**")
        for node in failed:
            st.markdown(f"- `{node}`")
    else:
        st.success("全部能力验收节点通过(含 held-out 输入)。")

with tabs[3]:
    st.markdown(f"**宿主回归 verifier 输出**:`{dash(report.get('regression'))}`")
    st.caption("回归 = 宿主项目原有功能(loader / health)在适配后保持不变。")

with tabs[4]:
    st.markdown(f"**Policy verifier 输出**:`{dash(report.get('policy'))}`")
    st.caption("覆盖:oracle/upstream 完整性 · 写入区约束 · action_id 因果链 · 命令/Token/Patch 预算。")

with tabs[5]:
    st.markdown(f"""
- **Replay verifier 输出**:`{dash(report.get("replay"))}`
- **模式**:{replay_mode_zh(srow.get("replay_mode"))}(`{dash(srow.get("replay_mode"))}`)
- **Image Digest**:`{dash((report.get("image_digest") or "").split("@")[-1][:20])}…`
- **Wheelhouse Root**:`{dash((report.get("wheelhouse_root") or "")[:16])}…`
- **重放中的模型调用:0**(重放只执行冻结产物,不重跑 Agent)
""")

with tabs[6]:
    ftype = srow.get("failure_type")
    if verdict == "PASS_ADAPTED":
        st.success("无失败归因:四项独立验证与干净采用重放全部通过。")
    else:
        st.markdown(f"""
- **失败类型**:`{dash(ftype)}`
- **主要责任方**:{failure_owner_zh(ftype)}
- **证据**:`{dash(srow.get("evidence_path"))}` · Trace sha `{dash((srow.get("trace_sha256") or "")[:16])}…`
- 详细分类学见 `docs/FAILURE_TAXONOMY.md`(每类都挂真实 run 证据)。
""")

with tabs[7]:
    st.markdown("**单文件下载(只读证据副本,均已通过脱敏扫描):**")
    for label, path in facts.evidence_files(case):
        st.download_button(
            label=f"⬇️ {label}", data=path.read_bytes(), file_name=path.name,
            key=f"dl-{case}-{path.name}",
        )
    st.divider()
    st.download_button(
        label="📦 下载完整 Evidence Bundle(ZIP)",
        data=facts.bundle_zip_bytes(case),
        file_name=f"{facts.evidence_dir(case).name}.zip",
        mime="application/zip",
        key=f"dl-bundle-{case}",
    )
    st.divider()
    st.markdown("**Trace 预览(前 200 行事件):**")
    st.dataframe(facts.trace_preview(case), width="stretch", hide_index=True, height=300)
