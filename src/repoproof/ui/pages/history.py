"""历史运行 — 数据源:docs/benchmark_summary.json(机器可读事实源)。
缺失字段显示 — ,绝不推断;不声称任何 Harness 提升成功率。"""

from __future__ import annotations

import streamlit as st

from repoproof.ui.presenters.zh import dash, run_type_zh, verdict_zh
from repoproof.ui.services import facts

st.set_page_config(page_title="历史运行 · RepoProof Studio", page_icon="🗂️", layout="wide")
st.title("🗂️ 历史运行")

summary = facts.load_summary()
totals = summary["totals"]
st.caption(
    f"事实源:docs/benchmark_summary.json · {totals['capability_domains']} 个能力域 · "
    f"{totals['runs_recorded']} 次记录运行 · {totals['pass_adapted']} 次 PASS_ADAPTED · "
    f"{totals['honest_fails']} 次诚实 FAIL(仅展示事实,不做成功率归因)"
)

runs = summary["runs"]

# ---- 筛选 ----
f1, f2, f3, f4 = st.columns(4)
verdicts = sorted({r["final_verdict"] for r in runs if r["final_verdict"]})
tasks = sorted({r["task_version"] for r in runs})
types = sorted({r["run_type"] for r in runs})
failures = sorted({r["failure_type"] for r in runs if r["failure_type"]})
sel_verdict = f1.multiselect("Verdict", verdicts)
sel_task = f2.multiselect("任务版本", tasks)
sel_type = f3.multiselect("运行类型", types, format_func=run_type_zh)
sel_failure = f4.multiselect("失败类型", failures)

rows = [
    r for r in runs
    if (not sel_verdict or r["final_verdict"] in sel_verdict)
    and (not sel_task or r["task_version"] in sel_task)
    and (not sel_type or r["run_type"] in sel_type)
    and (not sel_failure or (r["failure_type"] and r["failure_type"] in sel_failure))
]

table = [
    {
        "案例": r["case_id"],
        "任务版本": r["task_version"],
        "运行类型": run_type_zh(r["run_type"]),
        "模型": dash(r["model"]),
        "Capability": (
            f"{r['capability_passed']}/{r['capability_total']}"
            if r["capability_passed"] is not None else "—"
        ),
        "回归": (
            f"{r['regression_passed']}/{r['regression_total']}"
            if r["regression_passed"] is not None else "—"
        ),
        "Verdict": f"{verdict_zh(r['final_verdict'])} ({dash(r['final_verdict'])})",
        "重放": dash(r["replay_mode"]),
        "失败类型": dash(r["failure_type"]),
        "模型调用": dash(r["model_calls"]),
        "Tokens(入/出)": (
            f"{r['input_tokens']:,} / {r['output_tokens']:,}"
            if r["input_tokens"] is not None else "—"
        ),
        "证据": r["evidence_path"],
    }
    for r in rows
]
st.dataframe(table, width="stretch", hide_index=True)

# ---- 两次运行对比(只列事实) ----
st.subheader("两次运行对比")
pick = st.multiselect("选择两条运行(仅事实并排,不做因果推断)", [r["case_id"] for r in runs], max_selections=2)
if len(pick) == 2:
    a, b = (facts.summary_row(cid) for cid in pick)
    fields = [
        ("任务版本", "task_version"), ("运行类型", "run_type"), ("模型", "model"),
        ("Capability 通过", "capability_passed"), ("Capability 总数", "capability_total"),
        ("Verdict", "final_verdict"), ("重放模式", "replay_mode"),
        ("模型调用", "model_calls"), ("命令数", "commands"),
        ("输入 Tokens", "input_tokens"), ("输出 Tokens", "output_tokens"),
        ("Adapter 行数", "adaptation_lines"), ("失败类型", "failure_type"),
    ]
    st.dataframe(
        [{"指标": label, pick[0]: dash(a.get(key)), pick[1]: dash(b.get(key))} for label, key in fields],
        width="stretch", hide_index=True,
    )
    st.caption("注意:不同运行之间任务版本 / 规格 / 预算可能不同;上表只是事实并排,不构成任何提升声称。")
