"""采用计划页 — Phase 3+4+5 真实流水(分析→准入→计划→人工确认)。

演示数据:你的项目=内置示例 fixture,目标仓库=本地固定版
python-frontmatter 快照。「确认开始」真实走 Human Gate 生成冻结
意向(sha 绑定);真实 AI 执行在下一版本开放,页面如实说明。
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from repoproof.adoption.admission.admission_report import decide
from repoproof.adoption.analysis.host_analyzer import analyze_host_project
from repoproof.adoption.analysis.repository_analyzer import analyze_repository_dir
from repoproof.adoption.intent.intent_parser import parse_intent
from repoproof.adoption.planning.adoption_plan import build_plan
from repoproof.adoption.planning.human_gate import ACK_TEXT, HumanGateError, confirm_plan
from repoproof.ui.services.facts import repo_root
from repoproof.ui.services.state import is_tech, mode_toggle_sidebar, tech_expander

st.set_page_config(page_title="采用计划 · RepoProof Studio", layout="wide")
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
    accepted = list(adm.risks) if adm.status == "RISK_REVIEW" else None
    plan = None
    if adm.status in ("READY", "RISK_REVIEW"):
        plan = build_plan(intent, host, repo, adm, accepted_risks=accepted)
    return host, repo, adm, plan, accepted


host, repo, adm, plan, accepted = _pipeline(goal, host_path, repo_path)

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
if accepted:
    st.caption(f"注:适用性检查为「存在风险,需要你确认」;演示中已代为接受 {len(accepted)} 条风险,正式使用需你逐条确认。")

st.subheader("推荐方案")
st.markdown(f"**{plan.recommended}** —— {plan.rationale}")
for s in plan.strategies:
    with st.expander(s.name, expanded=False):
        st.markdown(s.description)
        st.markdown("优点:" + "、".join(s.pros) + " / 代价:" + "、".join(s.cons))

st.subheader("预计修改")
st.markdown(plan.estimated_changes)

st.subheader("成功标准")
for c in plan.success_criteria:
    st.markdown(f"- {c}")

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
            accepted_risks=accepted,
        )
        st.success("已确认并冻结采用意向——此后计划与评分规则不可再改,改动会被指纹校验拒绝。")
        st.info("🟡 本版本为只读演示版:真实 AI 执行(含多轮修复)将在下一版本开放。"
                "你可以先到「修复过程」页看 AI 将如何逐轮工作。")
        if is_tech():
            with tech_expander("查看冻结意向(技术详情)"):
                st.json(frozen.to_dict())
    except HumanGateError as exc:
        st.error(f"还不能开始:{exc}")
st.caption(f"确认即表示:{ACK_TEXT}")
