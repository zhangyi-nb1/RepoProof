"""修复过程页 — 用真实 RepairLoop 引擎演示多轮工作方式。

核心信息:**AI 不是一次生成答案**——每轮:修改 → 跑公开测试 →
失败被翻译成结构化提示 → 下一轮修复;有上限、有回滚、有停滞检测。
本页驱动数据为脚本化演示轮(零模型调用),循环引擎是真实代码。
"""

from __future__ import annotations

import streamlit as st

from repoproof.adoption.repair.repair_loop import RepairLoop, RoundResult
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander

st.set_page_config(page_title="修复过程 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()
st.title("修复过程")
st.info("**AI 不是一次生成答案。** 它每轮只做一件事:改代码 → 跑公开测试 → 看哪里错了 → 下一轮修。"
        "轮数有上限(默认 3 轮),变差会回滚,连续不进步会停,越界要问你。")

_DEMO_ROUNDS = [
    RoundResult(adapter_snapshot="第1轮适配代码", passed=5,
                failed_nodes=["cap::test_schema_fields", "cap::test_upstream_wrapped",
                              "cap::test_order", "cap::test_dates"],
                failure_details={"cap::test_schema_fields": "KeyError: missing field doc_id"},
                diff_lines=60, tokens_used=20_000, commands_used=8),
    RoundResult(adapter_snapshot="第2轮适配代码", passed=8,
                failed_nodes=["cap::test_upstream_wrapped"],
                failure_details={"cap::test_upstream_wrapped": "TypeError: unexpected keyword"},
                diff_lines=25, tokens_used=12_000, commands_used=5),
    RoundResult(adapter_snapshot="第3轮适配代码", passed=9, failed_nodes=[],
                diff_lines=8, tokens_used=6_000, commands_used=3),
]


@st.cache_data
def _run_demo():
    def run_round(i, packets, best_snapshot):
        return _DEMO_ROUNDS[i - 1]

    out = RepairLoop(run_round).run()
    return out.to_dict()


out = _run_demo()

_total = 9
for cp in out["checkpoints"]:
    idx = cp["round_index"]
    st.subheader(f"第{idx}轮")
    if idx == 1:
        st.markdown("**修改**:首次编写适配代码(约 60 行)")
    else:
        prev = out["checkpoints"][idx - 2]
        delta = cp["passed"] - prev["passed"]
        st.markdown(f"**修改**:根据上一轮失败提示修复(改动 {cp['diff_lines']} 行)")
        st.markdown(f"**改善**:通过数 {prev['passed']} → {cp['passed']}(+{delta})")
    st.markdown(f"**测试**:公开测试 {cp['passed']}/{_total} 通过")
    if cp["failed_nodes"]:
        st.markdown("**失败**:")
        for n in cp["failed_nodes"]:
            human = n.split("::")[-1].replace("test_", "").replace("_", " ")
            st.markdown(f"- ❌ 检查项「{human}」未通过")
    else:
        st.markdown("**失败**:无——公开测试全部通过")
    st.divider()

st.markdown(
    f"**循环结束**:共 {out['rounds_run']} 轮,最佳为第 {out['best_round']} 轮"
    f"({out['best_passed']}/{_total})。"
)
st.warning("公开测试全绿 ≠ 最终成功:接下来仍要经过冻结产物 → 独立验收测试"
           "(AI 看不到)→ 原项目回归 → 操作规则检查 → 干净环境复测 → 最终判定。"
           "修复循环自己永远不宣布成功。")
st.caption("本页为演示轮次(零模型调用);循环引擎、回滚与停滞规则为真实代码。真实多轮运行在下一版本开放。")

if is_tech():
    with tech_expander("查看技术详情(RepairOutcome 原始输出)"):
        st.json(out)
