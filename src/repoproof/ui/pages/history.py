"""历史记录 — 事实源:docs/benchmark_summary.json。
简单模式:每行一个任务的通俗结果;技术模式:完整原始表。
缺失字段显示 — ,绝不推断;不做成功率归因。"""

from __future__ import annotations

import streamlit as st

from repoproof.ui.presenters.glossary import (
    dash,
    run_type_zh,
    verdict_simple,
    verdict_zh,
)
from repoproof.ui.services import facts
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander

st.set_page_config(page_title="历史记录 · RepoProof Studio", layout="wide")
mode_toggle_sidebar()
st.title("历史记录")

_locals = facts.local_runs()
if _locals:
    st.subheader("你的运行(本机产品模式,持久保存)")
    _rows_local = []
    for _rn in _locals:
        _d = facts.load_local_run(_rn)
        _rep0, _man0 = _d["report"], _d["manifest"]
        _ag0 = _man0.get("agent") or {}
        _rows_local.append({
            "时间": facts.run_ts_human(_rn),
            "运行": _rn,
            "最终结果": verdict_simple(_rep0.get("final_verdict")),
            "AI 结束方式": _ag0.get("exit_status") or _rep0.get("agent", {}).get("exit_status") or "—",
        })
    st.dataframe(_rows_local, width="stretch", hide_index=True)
    st.caption("在「运行进度」或「结果报告」页选择对应条目可看详情;这些运行不进入下方公开基准。")
    st.divider()

st.subheader("公开基准(随项目发布的参考校准级案例)")
summary = facts.load_summary()
totals = summary["totals"]
runs = summary["runs"]
st.caption(
    f"共记录 {totals['runs_recorded']} 次运行(其中 {totals['pass_adapted']} 次「{verdict_simple('PASS_ADAPTED')}」)。"
    "下表只列事实,不同任务的标准与预算不同,不能直接比较成功率。"
)

_DOMAIN = {"chonkie": "文本分块", "rank-bm25": "检索排序", "frontmatter": "文档元数据解析"}


def _domain(task_version: str) -> str:
    for key, name in _DOMAIN.items():
        if task_version.startswith(key):
            return name
    return task_version


# ---- 筛选 ----
f1, f2 = st.columns(2)
sel_verdict = f1.multiselect(
    "按最终结果筛选", sorted({r["final_verdict"] for r in runs if r["final_verdict"]}),
    format_func=verdict_simple, placeholder="请选择(可多选)",
)
sel_domain = f2.multiselect(
    "按功能类型筛选", sorted({_domain(r["task_version"]) for r in runs}),
    placeholder="请选择(可多选)",
)

rows = [
    r for r in runs
    if (not sel_verdict or r["final_verdict"] in sel_verdict)
    and (not sel_domain or _domain(r["task_version"]) in sel_domain)
]

def _plain_result(v: str | None) -> str:
    """P2.3:列表里用文字标签,不用大红叉;图标只留给结果页大结论。"""
    return {"PASS_ADAPTED": "可使用(适配后)", "PASS_DIRECT": "可直接使用"}.get(
        v or "", "未达标" if v == "FAIL" else verdict_simple(v)
    )


if not is_tech():
    # P1.1 按任务聚合:一个功能类型一组,组内列每次运行
    for domain in sorted({_domain(r["task_version"]) for r in rows}):
        group = [r for r in rows if _domain(r["task_version"]) == domain]
        best = "可使用(适配后)" if any(r["final_verdict"] == "PASS_ADAPTED" for r in group) else "未达标"
        with st.expander(f"{domain} —— {len(group)} 次运行 · 最好结果:{best}",
                         expanded=(best.startswith("可使用"))):
            st.dataframe(
                [
                    {
                        "运行方式": run_type_zh(r["run_type"]),
                        "最终结果": _plain_result(r["final_verdict"]),
                        "AI 是否参与": "是" if r["run_type"] != "direct_baseline" else "否(直连基线)",
                    }
                    for r in group
                ],
                width="stretch", hide_index=True,
            )
    st.caption("想看测试通过数、用量、原始字段?打开左侧「显示技术详情」。")
else:
    st.dataframe(
        [
            {
                "case_id": r["case_id"],
                "任务版本": r["task_version"],
                "运行类型": run_type_zh(r["run_type"]),
                "模型": dash(r["model"]),
                "Capability": (f"{r['capability_passed']}/{r['capability_total']}"
                               if r["capability_passed"] is not None else "—"),
                "回归": (f"{r['regression_passed']}/{r['regression_total']}"
                        if r["regression_passed"] is not None else "—"),
                "Verdict": f"{verdict_zh(r['final_verdict'])} ({dash(r['final_verdict'])})",
                "重放": dash(r["replay_mode"]),
                "失败类型": dash(r["failure_type"]),
                "Tokens(入/出)": (f"{r['input_tokens']:,} / {r['output_tokens']:,}"
                                  if r["input_tokens"] is not None else "—"),
                "证据": r["evidence_path"],
            }
            for r in rows
        ],
        width="stretch", hide_index=True,
    )

if not is_tech():
    st.stop()  # P0.5:对比与原始字段仅在「显示技术详情」下渲染

with tech_expander("两次运行对比(技术详情)"):
    pick = st.multiselect("选择两条运行", [r["case_id"] for r in runs], max_selections=2,
                          placeholder="请选择两条")
    if len(pick) == 2:
        a, b = (facts.summary_row(cid) for cid in pick)
        fields = [
            ("任务版本", "task_version"), ("运行类型", "run_type"), ("模型", "model"),
            ("Capability 通过", "capability_passed"), ("Capability 总数", "capability_total"),
            ("Verdict", "final_verdict"), ("重放模式", "replay_mode"),
            ("模型调用", "model_calls"), ("输入 Tokens", "input_tokens"),
            ("输出 Tokens", "output_tokens"), ("Adapter 行数", "adaptation_lines"),
            ("失败类型", "failure_type"),
        ]
        st.dataframe(
            [{"指标": lb, pick[0]: dash(a.get(k)), pick[1]: dash(b.get(k))} for lb, k in fields],
            width="stretch", hide_index=True,
        )
        st.caption("仅事实并排:两次运行的任务版本/规格/预算可能不同,不构成任何提升声称。")
