"""UI 模式状态:简单模式(默认)/ 技术模式(可选)。

Session State 只保存界面选择;真实事实永远来自事实源文件。"""

from __future__ import annotations

import streamlit as st

MODE_KEY = "ui_mode"
SIMPLE, TECH = "simple", "tech"


def is_tech() -> bool:
    return st.session_state.get(MODE_KEY, SIMPLE) == TECH


def mode_toggle_sidebar() -> None:
    """侧边栏统一的模式开关(默认简单模式)。"""
    with st.sidebar:
        tech = st.toggle(
            "技术模式",
            value=is_tech(),
            help="默认为简单模式,只出现:你的项目 / 目标仓库 / 想实现的功能 / 最终结果。"
            "打开后展示内部字段(附中文解释)。",
        )
        st.session_state[MODE_KEY] = TECH if tech else SIMPLE


def tech_expander(title: str = "查看技术详情"):
    """技术内容的统一容器:简单模式折叠,技术模式默认展开。"""
    return st.expander(title, expanded=is_tech())
