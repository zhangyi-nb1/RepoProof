"""系统设置(次级入口)— 环境状态与固定安全提示,全部只读。
本版本不包含模型连接配置(真实运行在下一版本开放)。"""

from __future__ import annotations

import streamlit as st

from repoproof.ui.services import facts
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander

st.set_page_config(page_title="系统设置 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()
st.title("系统设置")

st.subheader("运行环境")
docker = facts.docker_status()
c1, c2, c3 = st.columns(3)
c1.metric("RepoProof 版本", f"v{facts.repoproof_version()}")
c2.metric("Docker 守护进程", "✅ 可用" if docker["available"] else "❌ 不可用")
c3.metric("界面模式", "技术模式" if is_tech() else "简单模式(默认)")
if not docker["available"]:
    st.warning(
        "Docker 未运行。影响:「在全新环境里再测一遍」将不可用;查看结果报告不受影响。"
        "下一步:启动 Docker(或 colima)后刷新本页。"
    )
with tech_expander("查看技术详情(环境)"):
    st.markdown(f"""
| 字段 | 值 | 中文说明 |
|---|---|---|
| server_version | `{docker.get("server_version") or "—"}` | Docker 服务端版本 |
| workspace | `{facts.repo_root()}` | 当前工作区路径 |
| streamlit | `1.60.0`(pinned) | 界面框架版本 |
""")

st.subheader("模型连接")
st.markdown(
    "本版本为只读演示版,**不需要也不接受任何 API Key**。"
    "真实 AI 运行(含模型连接检查)将在下一版本提供;届时密钥只保存在当前进程内存,"
    "不写入文件、执行记录或结果文件。"
)

st.subheader("安全提示")
st.warning(
    "RepoProof 会在 Docker 中执行你选择的第三方仓库代码。当前 Docker 仅用于隔离、"
    "销毁和重放,不是面向恶意代码的高强度安全沙箱。请只运行你主动选择并信任的公开仓库。"
)
