"""RepoProof Benchmark Lab — preserved research and historical workspace."""

from __future__ import annotations

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

PAGES = Path(__file__).parent / "pages"

# Keep the legacy Chinese workspace safe from browser translation DOM mutation.
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
        "RepoProof Benchmark Lab": [
            st.Page(str(PAGES / "new_task.py"), title="开始新任务", icon="🚀", default=True),
            st.Page(str(PAGES / "host_pilot.py"), title="宿主任务 T1–T4", icon="🧪"),
            st.Page(str(PAGES / "analysis.py"), title="项目分析", icon="🔎"),
            st.Page(str(PAGES / "plan_view.py"), title="采用计划", icon="🗺️"),
            st.Page(str(PAGES / "progress.py"), title="运行进度", icon="⏳"),
            st.Page(str(PAGES / "repair_view.py"), title="修复过程", icon="🔁"),
            st.Page(str(PAGES / "case_view.py"), title="结果报告", icon="📋"),
            st.Page(str(PAGES / "history.py"), title="历史记录", icon="🗂️"),
        ],
        "Benchmark Lab 设置": [
            st.Page(str(PAGES / "settings.py"), title="系统设置", icon="⚙️"),
        ],
    }
)
nav.run()
