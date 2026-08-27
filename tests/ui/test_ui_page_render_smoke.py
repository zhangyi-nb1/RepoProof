"""Product 页面的**渲染钉**:每条状态分支都得真渲染一次,不许只被读过。

来由(2026-08-27):`运行活动` 页在「任务正在跑」那条分支上写的是
`st.progress(None, text=...)`,而 Streamlit 的 progress 只收
int[0,100] / float[0,1] —— 于是**用户盯着构建跑的时候**这一屏必抛
`StreamlitAPIException: Progress Value has invalid type: NoneType`。
它活了很久,因为既有 UI 测试都只测服务层投影,没有一条真把页面
渲染出来;mypy 首次覆盖 ui 时才把它当类型错报出来。

这里用 Streamlit 官方 AppTest 端到端跑页面本体:钉的是「这条分支
渲染得出来」,不是文案。
"""

from __future__ import annotations

from pathlib import Path

import pytest

PAGES = Path(__file__).resolve().parents[2] / "src" / "repoproof" / "ui" / "pages"


def _stub_jobs(monkeypatch: pytest.MonkeyPatch, job: dict) -> None:
    from repoproof.ui.services import product_jobs

    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: job)
    monkeypatch.setattr(product_jobs, "read_product_job_log",
                        lambda *a, **k: {"ok": False, "error": "stub"})


@pytest.mark.parametrize(
    ("label", "job"),
    [
        ("running", {"status": "RUNNING", "alive": True, "kind": "tool-build",
                     "action": "build", "label": "demo", "pid": 4242}),
        ("succeeded", {"status": "SUCCEEDED", "alive": False, "ok": True,
                       "kind": "tool-build", "action": "build",
                       "label": "demo", "pid": 4242, "note": "done"}),
        ("failed", {"status": "FAILED", "alive": False, "ok": False,
                    "kind": "tool-build", "action": "build", "label": "demo",
                    "pid": 4242, "note": "boom", "error_code": "X1"}),
        ("no-job", {}),
    ],
)
def test_activity_page_renders_every_state(
    label: str, job: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from streamlit.testing.v1 import AppTest

    _stub_jobs(monkeypatch, job)
    at = AppTest.from_file(str(PAGES / "product_activity.py"), default_timeout=60).run()
    assert not [str(e.value) for e in at.exception], (
        f"{label} 分支渲染抛异常:{[str(e.value) for e in at.exception]}")


def test_onboarding_page_renders_with_repo_overview(monkeypatch: pytest.MonkeyPatch) -> None:
    """新建工具页 + 仓库简介面板真渲染一次。

    2026-08-27 新增「仓库简介」与「样例助手」两块都在这一页;它们含表格、
    可编辑区与逐条确认按钮,正是最容易写出运行期崩溃的形态(上一次
    `st.progress(None)` 的教训)。这里只钉「渲染得出来」,不钉文案。
    """
    from repoproof.ui.services import product_jobs

    overview = {
        "repository": "https://example.invalid/demo",
        "headline": "demo does one thing well",
        "prose": "demo does one thing well\n\nIt has two modes.",
        "prose_source": "README 原文摘录(未经模型改写)",
        "quickstart": "import demo",
        "quickstart_evidence": "README.md 首个代码块",
        "facts": [{"label": "许可证", "value": "MIT",
                   "evidence": "LICENSE", "provenance": "FACT"}],
        "surfaces": [{"kind": "公开符号", "value": "convert", "evidence": "__all__"}],
        "risks": ["无测试目录"],
        "sources": ["README.md"],
    }
    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: {})
    monkeypatch.setattr(product_jobs, "read_repo_overview",
                        lambda *a, **k: {"ok": True, "overview": overview})

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PAGES / "tool_onboarding.py"), default_timeout=90)
    at.session_state["rp_overview"] = {"ok": True, "overview": overview}
    at.run()
    assert not [str(e.value) for e in at.exception], [str(e.value) for e in at.exception]
    labels = [b.label for b in at.button]
    assert any("仓库简介" in x for x in labels), labels
    assert any("候选" in x for x in labels), labels
