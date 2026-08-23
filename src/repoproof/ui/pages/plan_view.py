"""采用计划页 — Phase 3+4+5 真实流水(分析→准入→计划→人工确认)。

演示数据:你的项目=内置示例 fixture,目标仓库=本地固定版
python-frontmatter 快照。「确认开始」真实走 Human Gate 生成冻结
意向(sha 绑定);真实 AI 执行在下一版本开放,页面如实说明。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from repoproof.adoption.admission.admission_report import decide
from repoproof.adoption.analysis.host_analyzer import analyze_host_project
from repoproof.adoption.analysis.repository_analyzer import analyze_repository_dir
from repoproof.adoption.intent.intent_parser import parse_intent
from repoproof.adoption.planning.adoption_plan import build_plan
from repoproof.adoption.planning.human_gate import ACK_TEXT, HumanGateError, confirm_plan
from repoproof.execution.core_execution import (
    CoreExecutionConflictError,
    core_execution_lease,
)
from repoproof.ui.services.facts import repo_root
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander

st.set_page_config(page_title="采用计划 · RepoProof Benchmark Lab", layout="wide")
mode_toggle_sidebar()
st.title("采用计划")

ROOT = repo_root()
PINNED = ROOT / "upstream-cache" / "upstream-dc7c0af5466b"

goal = st.text_input("你的目标", value=st.session_state.get("plan_goal",
                     "把 thefuzz 的模糊匹配能力接入我的笔记搜索,输入是查询词,输出为按相似度排序的笔记列表"))
st.session_state["plan_goal"] = goal

_default_host = "/Users/zhangronglei/Desktop/XIANGMU/demo-notes-app"
host_path = st.text_input(
    "你的项目路径", value=st.session_state.get("plan_host",
    _default_host if Path(_default_host).is_dir() else str(ROOT)))
st.session_state["plan_host"] = host_path

_repo_options = sorted(str(p) for p in (ROOT / "upstream-cache" / "analysis").glob("*/") if p.is_dir())
if PINNED.exists():
    _repo_options.append(str(PINNED))
if not _repo_options:
    st.warning("本地没有可分析的目标仓库缓存;先在终端运行 repoproof analyze-repo --url <github-url>。")
    st.stop()
_repo_default = st.session_state.get("plan_repo") or _repo_options[0]
if _repo_default not in _repo_options:
    _repo_default = _repo_options[0]
repo_path = st.selectbox("目标仓库(本地已缓存的分析副本)", _repo_options,
                         index=_repo_options.index(_repo_default),
                         format_func=lambda s: Path(s).name)
st.session_state["plan_repo"] = repo_path


@st.cache_data(show_spinner="正在分析双方并生成计划……")
def _pipeline(goal_text: str, host_p: str, repo_p: str):
    host = analyze_host_project(host_p)
    repo = analyze_repository_dir(repo_p, url=Path(repo_p).name)
    adm = decide(host, repo)
    intent = parse_intent(goal_text)
    # 计划仅为预览而按「全部风险已接受」构建;真正的接受动作发生在
    # 下方逐条勾选 + Human Gate(F1),预览不等于放行。
    preview_accept = list(adm.risks) if adm.status == "RISK_REVIEW" else None
    plan = None
    if adm.status in ("READY", "RISK_REVIEW"):
        plan = build_plan(intent, host, repo, adm, accepted_risks=preview_accept)
    return host, repo, adm, plan, intent


host, repo, adm, plan, intent = _pipeline(goal, host_path, repo_path)

if plan is None:
    _icon = {"NEED_INFORMATION": "🟡 还需要补充一些信息", "UNSUPPORTED": "❌ 当前版本暂不支持"}
    st.subheader(_icon.get(adm.status, adm.status))
    for f in adm.confirmed_facts:
        st.markdown(f"- ✅ {f}")
    for q in adm.questions:
        st.markdown(f"- 🟡 {q}")
    for b in adm.blockers:
        st.markdown(f"- ❌ {b}")
    st.markdown(f"**你的下一步**:{adm.next_step}")
    st.stop()

st.subheader("AI 理解")
st.markdown(plan.understanding)

st.subheader("推荐方案")
if plan.requires_user_choice:
    st.markdown(f"**空白项目模式**:{plan.rationale}")
else:
    st.markdown(f"**{plan.recommended}** —— {plan.rationale}")
for s in plan.strategies:
    with st.expander(s.name, expanded=False):
        st.markdown(s.description)
        st.markdown("优点:" + "、".join(s.pros) + " / 代价:" + "、".join(s.cons))
        if s.verification:
            st.markdown(f"验证方法:{s.verification}")

_names = [s.name for s in plan.strategies]
_default = _names.index(plan.recommended) if plan.recommended in _names else 0
chosen = st.radio("选定接入方式(你有最终决定权;空白项目必须自己选)", _names, index=_default)

st.subheader("预计修改")
st.markdown(plan.estimated_changes)

st.subheader("成功标准")
for c in plan.success_criteria:
    st.markdown(f"- {c}")

if adm.risks:
    st.subheader("风险(需要你逐条确认接受)")
    _accepted_now: list[str] = []
    for i, r in enumerate(adm.risks):
        if st.checkbox(r, key=f"plan_risk_{i}"):
            _accepted_now.append(r)
else:
    _accepted_now = []

st.subheader("需要确认")
answers: dict[str, str] = {}
for i, q in enumerate(plan.questions):
    answers[q] = st.text_input(q, key=f"plan_q_{i}", placeholder="必填")

c1, c2 = st.columns(2)
if c1.button("修改计划", width="stretch"):
    st.switch_page("pages/new_task.py")
if c2.button("确认开始", type="primary", width="stretch"):
    try:
        frozen = confirm_plan(
            plan, adm, answers=answers, user_ack=ACK_TEXT,
            confirmed_at=datetime.now(UTC).isoformat(),
            accepted_risks=_accepted_now or None,
            intent_dict=intent.to_dict(), chosen_strategy=chosen,
        )
        from repoproof.adoption.delivery.intent_store import save_frozen_intent

        with core_execution_lease(
            repo_root(),
            kind="lab-freeze-intent",
            label="Lab 冻结采用意向",
        ):
            save_frozen_intent(repo_root() / "runs", frozen.to_dict())
        st.success("已确认并冻结采用意向(已保存)——此后计划与评分规则不可再改,改动会被指纹校验拒绝。")
        st.info("下一步:到「开始新任务」第 4/5 步给出验收样例并装配冻结,然后由你亲手点「真实运行」。")
        if is_tech():
            with tech_expander("查看冻结意向(技术详情)"):
                st.json(frozen.to_dict())
    except HumanGateError as exc:
        st.error(f"还不能开始:{exc}")
    except CoreExecutionConflictError as exc:
        st.error(str(exc))
st.caption(f"确认即表示:{ACK_TEXT}")
