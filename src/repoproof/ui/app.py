"""RepoProof Studio — 本地中文工作台入口(Gate 9A:只读)。

启动:scripts/run_ui.sh(默认 127.0.0.1,不对局域网/公网开放)。
事实源:benchmark_summary.json + Evidence Bundle;UI 不改写任何历史。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

PAGES_DIR = Path(__file__).parent / "pages"

nav = st.navigation(
    [
        st.Page(str(PAGES_DIR / "home.py"), title="首页 / 快速体验", icon="🛡️", default=True),
        st.Page(str(PAGES_DIR / "case_view.py"), title="结果与证据", icon="🔍"),
        st.Page(str(PAGES_DIR / "history.py"), title="历史运行", icon="🗂️"),
    ]
)
nav.run()
