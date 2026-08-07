"""UI 模式状态:简单模式(默认)/ 技术模式(可选)。

Session State 只保存界面选择;真实事实永远来自事实源文件。"""

from __future__ import annotations

import streamlit as st

MODE_KEY = "ui_mode"
SIMPLE, TECH = "simple", "tech"


def is_tech() -> bool:
    return st.session_state.get(MODE_KEY, SIMPLE) == TECH


def mode_toggle_sidebar() -> None:
    """侧边栏统一的模式开关(默认简单模式)+ 页面公共样式。"""
    with st.sidebar:
        tech = st.toggle(
            "显示技术详情",
            value=is_tech(),
            help="默认只出现:你的项目 / 目标仓库 / 想实现的功能 / 最终结果。"
            "打开后展示执行记录、哈希等原始字段(附中文解释)。",
        )
        st.session_state[MODE_KEY] = TECH if tech else SIMPLE
    # P2.2 控制正文最大宽度,移动端不横向溢出
    st.markdown(
        "<style>.block-container{max-width:1100px;padding-left:1.5rem;"
        "padding-right:1.5rem;}</style>",
        unsafe_allow_html=True,
    )


def tech_expander(title: str = "查看技术详情"):
    """技术内容的统一容器:技术模式默认展开。
    注意:简单模式下调用方应先用 ``if is_tech():`` 判断——
    Trace / Token / Hash 等在简单模式必须整体隐藏(P0.5),
    而不是折叠可见。"""
    return st.expander(title, expanded=is_tech())
