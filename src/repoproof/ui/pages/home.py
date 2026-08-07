"""首页 / 快速体验 — 只读,零模型调用。"""

from __future__ import annotations

import streamlit as st

from repoproof.runner.demo import CASES
from repoproof.ui.presenters.zh import verdict_zh
from repoproof.ui.services import facts

st.set_page_config(page_title="RepoProof Studio", page_icon="🛡️", layout="wide")

st.title("🛡️ RepoProof Studio — 中文工作台")
st.caption("开源仓库能力采用任务:配置 → 执行 → 独立验证 → 可复核证据(Gate 9A:只读快速体验)")

# ---- 顶部状态 ----
docker = facts.docker_status()
c1, c2, c3, c4 = st.columns(4)
c1.metric("RepoProof 版本", f"v{facts.repoproof_version()}")
c2.metric("Docker 守护进程", f"可用 · {docker['server_version']}" if docker["available"] else "不可用")
c3.metric("当前任务运行", "无(只读模式)")
c4.metric("记录在案的运行", str(facts.load_summary()["totals"]["runs_recorded"]))

st.markdown(
    """
```text
冻结任务合同 → Coding Agent 适配 → 独立验证 → 干净重放 → 可信 Verdict
```
**判定权不在 Agent 手里**:Agent 的自述从不参与最终 Verdict;
PASS_ADAPTED 只能由 Capability ∧ 宿主回归 ∧ Policy ∧ 干净采用重放共同产生。
"""
)

# ---- 三个内置案例卡 ----
st.subheader("内置案例(全部无模型、可复核)")
cols = st.columns(3)
_CARDS = [
    ("frontmatter-v2-pass", "✅ Front Matter 正向案例",
     ["Capability:18/18(含 held-out)", "Regression:3/3", "Policy:PASS",
      "Replay:clean_adoption PASS"], "PASS_ADAPTED"),
    ("chonkie-agent-fail", "❌ Chonkie 负向案例",
     ["Capability:31/33", "Regression:PASS", "失败复现重放:PASS",
      "Agent 完成大部分工作,但完整合同未满足,因此未放行"], "FAIL"),
    ("bm25-agent-fail", "❌ rank_bm25 负向案例",
     ["Capability:9/12", "失败类型:SEMANTIC_SUBSTITUTION",
      "Agent 自造 BM25 语义,被行为参考拒绝"], "FAIL"),
]
for col, (case, title, lines, verdict) in zip(cols, _CARDS, strict=True):
    with col:
        with st.container(border=True):
            st.markdown(f"**{title}**")
            for line in lines:
                st.markdown(f"- {line}")
            st.markdown(f"**Verdict:{verdict_zh(verdict)}(`{verdict}`)**")
            st.caption(CASES[case]["headline"])
            if st.button("在结果页查看", key=f"view-{case}"):
                st.session_state["case"] = case
                try:
                    st.switch_page("pages/case_view.py")
                except Exception:  # noqa: BLE001 — AppTest 单页运行时无导航
                    st.info("请在左侧导航打开「结果与证据」页查看该案例。")

# ---- 能力边界 ----
st.subheader("当前能力边界(诚实声明)")
st.markdown(
    """
- 范围:**公开 Python 仓库 / Linux 容器 / CPU-first 能力采用任务**;每个任务都需要人工完成合同、Oracle 与控制组工程。
- 12 次记录运行,**1 次 PASS_ADAPTED**,11 次诚实 FAIL —— 本系统不保证适配成功,也不支持任意仓库。
- 正向案例是 **corrected-spec** 结果(任务规格在两次尝试之间被修复),**不是**单变量提升实验。
- Docker 仅用于隔离、销毁与重放,**不是**面向恶意代码的高强度安全沙箱;
  Trace 是 tamper-evident(哈希链),**不是** tamper-proof。
"""
)
