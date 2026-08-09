"""RepoProof Studio — 本地中文工作台入口。

主导航四页(开始新任务 / 运行进度 / 结果报告 / 历史记录)+
次级「系统设置」。默认简单模式;127.0.0.1 启动(scripts/run_ui.sh)。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

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

nav = st.navigation(
    {
        "工作台": [
            st.Page(str(PAGES / "new_task.py"), title="开始新任务", icon="🚀", default=True),
            st.Page(str(PAGES / "host_pilot.py"), title="宿主任务 T1", icon="🧪"),
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
