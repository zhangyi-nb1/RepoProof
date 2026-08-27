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


def test_onboarding_page_renders_with_repo_overview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """新建工具页 + 仓库简介面板真渲染一次。

    2026-08-27 新增「仓库简介」与「样例助手」两块都在这一页;它们含表格、
    可编辑区与逐条确认按钮,正是最容易写出运行期崩溃的形态(上一次
    `st.progress(None)` 的教训)。这里只钉「渲染得出来」,不钉文案。
    """
    from repoproof.ui.services import product_jobs

    # The page must not depend on whichever draft the developer happens to
    # have under ~/.repoproof.  In particular, a successful confirm moves that
    # directory into tool_tasks/_drafts, which used to make this render test
    # disappear with the user's draft.
    state_root = tmp_path / "state"
    draft_dir = state_root / "drafts" / "my-tool-draft"
    draft_dir.mkdir(parents=True)
    (draft_dir / "draft.yaml").write_text(
        """tool:
  name: demo-tool
  summary: demo
  interface:
    input: {format: TXT}
    output:
      format: TEXT
      contract: {media_type: text/plain, root_type: text, required: {}}
capability: {statement: demo, output_schema: DemoText}
""",
        encoding="utf-8",
    )
    (draft_dir / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft_dir / "reference_impl.py").write_text("# demo\n", encoding="utf-8")
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state_root))
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    review = {
        "ok": True,
        "draft_dir": draft_dir,
        "draft": {
            "tool": {
                "name": "demo-tool",
                "summary": "demo",
                "interface": {
                    "input": {"format": "TXT"},
                    "output": {
                        "format": "TEXT",
                        "contract": {
                            "media_type": "text/plain",
                            "root_type": "text",
                            "required": {},
                        },
                    },
                },
            },
            "capability": {"statement": "demo", "output_schema": "DemoText"},
        },
        "raw_draft": (draft_dir / "draft.yaml").read_text(encoding="utf-8"),
        "examples": [],
        "reference_impl": "# demo\n",
        "gaps": "",
    }
    monkeypatch.setattr(
        product_jobs, "read_managed_draft_review", lambda *_args, **_kwargs: review
    )

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


def test_stale_service_process_gets_a_readable_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    """**负控**:运行中的 Studio 进程缺少新接口时,给人话提示而不是 AttributeError。

    LESSONS #50(第二次咬人):Streamlit 只重新 exec 页面文件,不重载它
    import 的 services 模块 —— 刚加的函数"磁盘上有、进程里没有",用户点
    按钮就吃一串英文 AttributeError(2026-08-27 用户实测)。
    """
    from repoproof.ui.services import product_jobs

    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: {})
    monkeypatch.delattr(product_jobs, "read_repo_overview", raising=False)

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PAGES / "tool_onboarding.py"), default_timeout=90)
    at.session_state["rp_repo_url"] = "https://github.com/example/demo"
    at.run()
    btn = [b for b in at.button if "仓库简介" in b.label][0]
    btn.click().run()

    assert not [str(e.value) for e in at.exception], [str(e.value) for e in at.exception]
    assert any("重启" in w.value for w in at.warning), [w.value for w in at.warning]


def test_stale_service_signature_is_caught_before_the_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**负控 · 同一坑第三次**:接口还在、但**签名旧了**,也要给人话提示。

    LESSONS #50 的第一版守卫只查 `hasattr` —— 而 2026-08-28 用户吃到的是
    `TypeError: save_draft_review() got an unexpected keyword argument
    'distribution'`:函数在,参数不认。所以守卫必须连参数一起查,并且在
    **页面顶部**就体检,而不是等用户点了保存才炸。
    """
    from repoproof.ui.services import product_jobs

    def _old_save(draft_dir, *, tool_name, summary, statement, input_format,
                  output_format, output_schema, reference_impl,
                  output_contract=None):          # 旧签名:不收上游身份三件
        return {"ok": True}

    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: {})
    monkeypatch.setattr(product_jobs, "save_draft_review", _old_save)

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PAGES / "tool_onboarding.py"), default_timeout=90).run()

    assert not [str(e.value) for e in at.exception], [str(e.value) for e in at.exception]
    said = [m.value for m in at.error] + [m.value for m in at.warning]
    assert any("重启" in m for m in said), said
    assert any("distribution" in m for m in said), said     # 点名到具体参数

