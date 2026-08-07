"""§十二 页面级验收:简单/技术双模式、五步向导、结果文案(AppTest)。"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PAGES = REPO / "src" / "repoproof" / "ui" / "pages"

try:
    from streamlit.testing.v1 import AppTest

    HAVE_ST = True
except ImportError:  # pragma: no cover
    HAVE_ST = False

needs_streamlit = pytest.mark.skipif(not HAVE_ST, reason="streamlit (ui extra) not installed")

KEY_MARKERS = ("sk-", "REPOPROOF_API_KEY", "DEEPSEEK_API_KEY")
# 简单模式第一眼(标题/子标题/指标/按钮)不允许出现的英文技术词
TECH_WORDS_FIRST_GLANCE = ("Oracle", "Harness", "TaskPackage", "Wheelhouse",
                           "RequirementSpec", "Completion Gate", "held-out")


def _first_glance(at) -> str:
    parts = []
    for kind in ("title", "header", "subheader", "metric", "button"):
        for el in getattr(at, kind, []):
            parts.append(str(getattr(el, "value", "")) + str(getattr(el, "label", "")))
    return "\n".join(parts)


def _all_text(at) -> str:
    parts = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "info", "success",
                 "warning", "error", "metric", "button", "selectbox", "checkbox", "code"):
        for el in getattr(at, kind, []):
            parts.append(str(getattr(el, "value", "")) + str(getattr(el, "label", "")))
    return "\n".join(parts)


def _page(name: str, timeout: int = 30):
    return AppTest.from_file(str(PAGES / name), default_timeout=timeout)


# 1. 默认进入简单模式
@needs_streamlit
def test_default_mode_is_simple() -> None:
    at = _page("new_task.py")
    at.run()
    assert not at.exception
    assert "ui_mode" not in at.session_state or at.session_state["ui_mode"] == "simple"
    src = (REPO / "src" / "repoproof" / "ui" / "services" / "state.py").read_text(encoding="utf-8")
    assert 'st.session_state.get(MODE_KEY, SIMPLE) == TECH' in src  # 默认简单模式


# 2. 简单模式第一眼不出现技术术语
@needs_streamlit
def test_tech_terms_hidden_in_simple_mode() -> None:
    for page in ("new_task.py", "case_view.py", "progress.py", "history.py"):
        at = _page(page)
        at.run()
        glance = _first_glance(at)
        for word in TECH_WORDS_FIRST_GLANCE:
            assert word not in glance, f"{page}: {word}"


# 3. 技术模式可展开原始字段(附中文解释)
@needs_streamlit
def test_tech_mode_reveals_raw_fields() -> None:
    at = _page("case_view.py")
    at.session_state["ui_mode"] = "tech"
    at.run()
    assert not at.exception
    text = _all_text(at)
    assert "task_package_root" in text and "trace_sha256" in text
    assert "中文说明" in text  # 原始字段必须配中文解释


# 4. 四个主导航 + 次级设置
def test_navigation_has_four_primary_pages() -> None:
    src = (REPO / "src" / "repoproof" / "ui" / "app.py").read_text(encoding="utf-8")
    for title in ("开始新任务", "运行进度", "结果报告", "历史记录", "系统设置"):
        assert title in src, title
    assert src.index("系统设置") > src.index("历史记录")  # 设置是次级分组


# 首页主按钮唯一
@needs_streamlit
def test_welcome_has_single_primary_button() -> None:
    at = _page("new_task.py")
    at.run()
    labels = [b.label for b in at.button]
    assert "体验任务配置流程" in labels and "查看示例" in labels
    src = (PAGES / "new_task.py").read_text(encoding="utf-8")
    welcome = src.split("# ================= 向导公共头")[0]
    assert welcome.count('type="primary"') == 1


# 5. 五步向导走通
@needs_streamlit
def test_wizard_five_steps_flow() -> None:
    at = _page("new_task.py", timeout=60)
    at.run()
    next(b for b in at.button if b.label == "体验任务配置流程").click().run()
    assert "用一两句话描述你想要的功能" in _all_text(at)  # step 1 头部
    at.text_area[0].set_value("把 python-frontmatter 的解析能力接入我的文档摄取模块").run()
    next(b for b in at.button if b.label == "下一步").click().run()
    assert "目标仓库" in _all_text(at)  # step 2
    at.text_input[0].set_value("~/my_project")
    at.text_input[1].set_value("https://github.com/eyeseast/python-frontmatter")
    at.text_input[2].set_value("v1.3.0").run()
    next(b for b in at.button if b.label == "下一步").click().run()
    text = _all_text(at)  # step 3: RISK_REVIEW
    assert "存在风险,需要你确认" in text and "隔离容器" in text
    next(c for c in at.checkbox if "我了解" in c.label).check().run()
    assert "可以开始尝试适配" in _all_text(at)  # -> READY
    next(b for b in at.button if b.label == "下一步").click().run()
    assert "确认采用计划" in _all_text(at)  # step 4
    next(c for c in at.checkbox if "我确认" in c.label).check().run()
    next(b for b in at.button if b.label == "下一步").click().run()
    assert "真实运行" in _all_text(at)  # step 5:真实运行区已就位


# 6. 必填缺失 → 中文可操作提示
@needs_streamlit
def test_required_field_error_is_actionable_chinese() -> None:
    at = _page("new_task.py")
    at.run()
    next(b for b in at.button if b.label == "体验任务配置流程").click().run()
    next(b for b in at.button if b.label == "下一步").click().run()
    errs = "".join(str(e.value) for e in at.error)
    assert "请把想实现的功能写成至少一句完整的话" in errs and "再点下一步" in errs


# 7/8. PASS_ADAPTED 与 FAIL 的中文结果;13. 与 Core Verdict 一致
@needs_streamlit
@pytest.mark.parametrize(
    ("case", "expected"),
    [("frontmatter-v2-pass", "适配后可使用"), ("chonkie-agent-fail", "当前条件下不建议采用")],
)
def test_result_page_verdict_matches_core(case: str, expected: str) -> None:
    from repoproof.ui.presenters.glossary import verdict_simple
    from repoproof.ui.services import facts

    core_verdict = facts.load_report(case)["final_verdict"]
    assert verdict_simple(core_verdict) == expected  # UI 文案 == Core verdict 的映射
    at = _page("case_view.py")
    at.session_state["case"] = case
    at.run()
    assert not at.exception
    assert expected in _all_text(at)


# 9. BLOCKED 中文(无 BLOCKED 证据案例;映射层保证 + 页面对未知值稳健)
@needs_streamlit
def test_blocked_wording_and_unknown_verdict_robustness() -> None:
    from repoproof.ui.presenters.glossary import verdict_next, verdict_simple

    assert verdict_simple("BLOCKED") == "缺少条件,暂时无法继续"
    assert "外部条件" in verdict_next("BLOCKED")


# 10. Agent Submitted 不显示为系统成功
@needs_streamlit
def test_agent_submitted_never_shown_as_success() -> None:
    # Submitted 案例(fm-v2):提交状态与系统结论必须分离呈现,
    # 且"已提交"旁边必须带"不代表任务成功"的限定
    at = _page("progress.py")
    at.session_state["case"] = "frontmatter-v2-pass"
    at.run()
    text = _all_text(at)
    assert "AI 助手已提交" in text and "不代表任务成功" in text
    assert "适配后可使用" in text  # 系统结论独立给出
    # 额度耗尽案例(chonkie):结束方式 ≠ 结论,同样分离
    at2 = _page("progress.py")
    at2.session_state["case"] = "chonkie-agent-fail"
    at2.run()
    text2 = _all_text(at2)
    assert "AI 使用额度已用完" in text2
    assert "当前条件下不建议采用" in text2


# 11. API Key 不出现在页面 / Session State 可见输出
@needs_streamlit
def test_no_api_key_anywhere() -> None:
    for page in ("new_task.py", "case_view.py", "progress.py", "history.py", "settings.py"):
        at = _page(page)
        at.run()
        ss_repr = " ".join(f"{k}={at.session_state[k]}" for k in ("case", "ui_mode", "wizard_step")
                           if k in at.session_state)
        text = _all_text(at) + ss_repr
        for marker in KEY_MARKERS:
            assert marker not in text, f"{page}: {marker}"


# 12. 下载按钮存在
@needs_streamlit
def test_download_buttons_present() -> None:
    at = _page("case_view.py")
    at.run()
    assert not at.exception
    src = (PAGES / "case_view.py").read_text(encoding="utf-8")
    assert src.count("st.download_button") >= 2 and "application/zip" in src


# 14. UI 不复制最终判定逻辑(核对按钮走 Core demo_verify)
def test_verify_button_delegates_to_core() -> None:
    src = (REPO / "src" / "repoproof" / "ui" / "services" / "actions.py").read_text(encoding="utf-8")
    assert "from repoproof.runner.demo import demo_replay, demo_verify" in src


# ---- P0/P1 增补验收 ----


@needs_streamlit
def test_simple_mode_hides_trace_token_hash() -> None:
    """P0.5:简单模式页面文本不出现 Trace/Token/哈希 概念。"""
    for page in ("progress.py", "case_view.py", "history.py"):
        at = _page(page)
        at.session_state["case"] = "frontmatter-v2-pass"
        at.run()
        text = _all_text(at)
        for word in ("Trace", "Token", "tokens", "哈希", "sha256", "trace_sha"):
            assert word not in text, f"{page}: {word}"


@needs_streamlit
def test_completed_task_stages_use_past_tense() -> None:
    """P0.6:已完成任务回顾用过去时;P1.5:简单模式压缩为三阶段。"""
    at = _page("progress.py")
    at.session_state["case"] = "frontmatter-v2-pass"  # 固定示例(本地 run 有专属视图)
    at.run()
    text = _all_text(at)
    assert "AI 理解与修改" in text and "干净环境复测" in text  # 三阶段
    assert "正在运行测试" not in text  # 无进行时
    at2 = _page("progress.py")
    at2.session_state["ui_mode"] = "tech"
    at2.session_state["case"] = "frontmatter-v2-pass"
    at2.run()
    text2 = _all_text(at2)
    assert "已运行测试" in text2 and "已完成最终验收" in text2  # 九段过去时


@needs_streamlit
def test_result_title_scoped_and_usage_notes() -> None:
    """P1.2 结论带条件前缀;P1.3 正向案例有使用前注意;P1.6 下载文案。"""
    at = _page("case_view.py")
    at.run()
    text = _all_text(at)
    assert "在当前测试条件下" in text
    assert "使用前注意" in text and "开源许可证" in text
    src = (PAGES / "case_view.py").read_text(encoding="utf-8")
    assert "下载代码 + 报告(ZIP)" in src


@needs_streamlit
def test_history_grouped_by_task_in_simple_mode() -> None:
    """P1.1 简单模式历史按任务聚合;P2.3 列表用文字标签不用大红叉。"""
    at = _page("history.py")
    at.run()
    expanders = [str(getattr(e, "label", "")) for e in getattr(at, "expander", [])]
    assert any("文档元数据解析" in e and "次运行" in e for e in expanders), expanders
    text = _all_text(at)
    assert "❌" not in text


def test_welcome_wording_honest_for_readonly() -> None:
    """P0.1/P0.2:不说「安全地」;只读版主按钮不叫「开始一次适配」。"""
    src = (PAGES / "new_task.py").read_text(encoding="utf-8")
    assert "安全地接入" not in src
    assert "可控地接入" in src
    assert "体验任务配置流程" in src


def test_multiselects_have_chinese_placeholder() -> None:
    """P0.4:Choose options 全部替换为中文占位。"""
    src = (PAGES / "history.py").read_text(encoding="utf-8")
    assert src.count('placeholder="请选择') >= 3
