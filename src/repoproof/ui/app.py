"""RepoProof Studio — 本地中文工作台入口。

主导航四页(开始新任务 / 运行进度 / 结果报告 / 历史记录)+
次级「系统设置」。默认简单模式;127.0.0.1 启动(scripts/run_ui.sh)。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

PAGES = Path(__file__).parent / "pages"

nav = st.navigation(
    {
        "工作台": [
            st.Page(str(PAGES / "new_task.py"), title="开始新任务", icon="🚀", default=True),
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
