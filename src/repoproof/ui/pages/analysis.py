"""项目分析页 — 调用 Phase 1 Host Analyzer(纯静态,零 LLM)。"""

from __future__ import annotations

import streamlit as st

from repoproof.adoption.analysis.host_analyzer import analyze_host_project
from repoproof.ui.services.facts import repo_root
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander

st.set_page_config(page_title="项目分析 · RepoProof Benchmark Lab", layout="wide")
mode_toggle_sidebar()
st.title("项目分析")
st.caption("静态分析你的项目:不执行代码、不修改文件、不调用 AI。"
           "结论分三级:事实(来自文件)/ 推断(规则)/ 未知(如实说不知道)。")

_default = str(repo_root() / "fixtures" / "consumer_rag_ingest_v2")
path = st.text_input("你的项目路径", value=st.session_state.get("an_path", _default),
                     help="示例项目已预填;换成你自己的 Python 项目路径即可。")
st.session_state["an_path"] = path

if st.button("开始分析", type="primary"):
    st.session_state["an_report"] = analyze_host_project(path).to_dict()

report = st.session_state.get("an_report")
if report:
    def _f(d: dict) -> str:
        tag = {"FACT": "事实", "INFERENCE": "推断", "UNKNOWN": "未知"}[d["provenance"]]
        val = d["value"] if d["value"] is not None else "—"
        return f"{val}({tag})"

    st.subheader("你的项目")
    _mode = report.get("host_mode", {}).get("value")
    if _mode == "BLANK_PROJECT":
        st.info("🈳 空白项目模式:目录为空且可写。可以从三种方式开始(整仓库落地/包装新项目/最小能力提取);"
                "原项目回归 = 不适用,改为验证安装、启动、能力与依赖锁。")
    elif _mode == "INVALID_PATH":
        st.error("路径无效:请提供存在且可写的目录。")
    st.markdown(f"""
- **Python 版本**:{_f(report["python_version"])}
- **框架**:{"、".join(str(f["value"]) for f in report["frameworks"]) or "未检出"}
- **入口**:{"、".join(str(e["value"]) for e in report["entry_points"]) or "未检出"}
- **测试**:{_f(report["test_command"])}
- **项目类型**:{_f(report["project_type"])} · **包管理**:{_f(report["package_manager"])}
""")
    st.subheader("推荐接入点")
    if report["integration_candidates"]:
        for c in report["integration_candidates"][:6]:
            st.markdown(f"- `{c['file']}` —— {c['reason']}")
    else:
        st.markdown("未找到明显接入点——可在采用计划中新建适配模块。")

    st.subheader("发现风险")
    if report["risks"]:
        for r in report["risks"]:
            st.markdown(f"- 🟡 {r}")
    else:
        st.markdown("✅ 未发现阻碍分析的风险。")

    if is_tech():
        with tech_expander("查看技术详情(完整报告 JSON)"):
            st.json(report)

    if st.button("带着分析结果去「采用计划」"):
        st.switch_page("pages/plan_view.py")
