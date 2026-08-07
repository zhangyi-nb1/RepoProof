"""新增三页(项目分析/采用计划/修复过程)AppTest 验收,零 LLM。"""

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

needs_streamlit = pytest.mark.skipif(not HAVE_ST, reason="streamlit not installed")


def _all_text(at) -> str:
    parts = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "info", "success",
                 "warning", "error", "metric", "button", "text_input"):
        for el in getattr(at, kind, []):
            parts.append(str(getattr(el, "value", "")) + str(getattr(el, "label", "")))
    return "\n".join(parts)


@needs_streamlit
def test_analysis_page_runs_real_analyzer() -> None:
    at = AppTest.from_file(str(PAGES / "analysis.py"), default_timeout=60)
    at.run()
    next(b for b in at.button if b.label == "开始分析").click().run()
    assert not at.exception
    text = _all_text(at)
    for section in ("你的项目", "Python 版本", "测试", "推荐接入点", "发现风险"):
        assert section in text, section
    assert "事实" in text or "未知" in text  # 三级出处中文标注
    assert "ingest.py" in text  # 示例 fixture 的真实接入点


@needs_streamlit
def test_plan_page_shows_plan_and_gate_blocks_unanswered() -> None:
    if not (REPO / "upstream-cache" / "upstream-dc7c0af5466b").exists():
        pytest.skip("pinned cache absent")
    at = AppTest.from_file(str(PAGES / "plan_view.py"), default_timeout=120)
    at.session_state["plan_host"] = str(REPO)  # 确定性:宿主=RepoProof 自身
    at.session_state["plan_repo"] = str(REPO / "upstream-cache" / "upstream-dc7c0af5466b")
    at.run()
    assert not at.exception
    text = _all_text(at)
    for section in ("你的目标", "AI 理解", "推荐方案", "预计修改", "成功标准", "需要确认"):
        assert section in text, section
    labels = [b.label for b in at.button]
    assert "修改计划" in labels and "确认开始" in labels
    # 未回答问题 → Human Gate 拒绝(真实 gate,不是 UI 判定)
    next(b for b in at.button if b.label == "确认开始").click().run()
    errs = "".join(str(e.value) for e in at.error)
    assert "还不能开始" in errs


@needs_streamlit
def test_repair_page_teaches_multi_round() -> None:
    at = AppTest.from_file(str(PAGES / "repair_view.py"), default_timeout=60)
    at.run()
    assert not at.exception
    text = _all_text(at)
    assert "AI 不是一次生成答案" in text
    for section in ("第1轮", "第2轮", "第3轮", "修改", "测试", "失败", "改善"):
        assert section in text, section
    assert "5/9" in text and "8/9" in text and "9/9" in text
    assert "永远不宣布成功" in text  # 全绿≠最终成功的诚实边界
