"""RepoProof Studio — Product Mode 与 Benchmark Lab 的本地中文入口。

Product Mode 是默认表面；历史 Guided Adoption / Benchmark Lab 页面保留在
独立导航分组。默认简单模式，始终只监听 127.0.0.1。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from repoproof.ui.product_theme import apply_product_theme

PAGES = Path(__file__).parent / "pages"

# 浏览器翻译(Google 翻译等)会往 React 管理的 DOM 里插 <font> 节点,
# 下次重渲染即 removeChild NotFoundError 整页红屏(用户实测两次;
# React issue #11538)。本应用是纯中文界面:声明语言并显式禁止翻译,
# 从根上规避。同源 iframe 脚本写入父文档,仅设置语言/翻译属性。
components.html(
    """<script>
    const d = window.parent.document;
    d.documentElement.lang = "zh-CN";
    d.documentElement.setAttribute("translate", "no");
    d.documentElement.classList.add("notranslate");
    if (!d.querySelector('meta[name="google"][content="notranslate"]')) {
      const m = d.createElement("meta");
      m.name = "google"; m.content = "notranslate";
      d.head.appendChild(m);
    }
    </script>""",
    height=0,
)

apply_product_theme()

nav = st.navigation(
    {
        "产品模式": [
            st.Page(str(PAGES / "product_home.py"), title="工作台", icon="🏠", default=True),
            st.Page(str(PAGES / "tool_onboarding.py"), title="新建工具", icon="🧰"),
            st.Page(str(PAGES / "product_activity.py"), title="运行活动", icon="🕒"),
            st.Page(str(PAGES / "tool_library.py"), title="工具库", icon="🧩"),
            st.Page(str(PAGES / "trust_dashboard.py"), title="可信仪表盘", icon="📊"),
        ],
        "Benchmark Lab": [
            st.Page(str(PAGES / "new_task.py"), title="开始新任务", icon="🚀"),
            st.Page(str(PAGES / "host_pilot.py"), title="宿主任务 T1–T4", icon="🧪"),
            st.Page(str(PAGES / "analysis.py"), title="项目分析", icon="🔎"),
            st.Page(str(PAGES / "plan_view.py"), title="采用计划", icon="🗺️"),
            st.Page(str(PAGES / "progress.py"), title="运行进度", icon="⏳"),
            st.Page(str(PAGES / "repair_view.py"), title="修复过程", icon="🔁"),
            st.Page(str(PAGES / "case_view.py"), title="结果报告", icon="📋"),
            st.Page(str(PAGES / "history.py"), title="历史记录", icon="🗂️"),
        ],
        "更多": [
            st.Page(str(PAGES / "settings.py"), title="系统设置", icon="⚙️"),
        ],
    }
)
nav.run()
