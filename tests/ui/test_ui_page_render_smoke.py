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


def _stub_jobs(
    monkeypatch: pytest.MonkeyPatch,
    job: dict,
    *,
    action_result: dict | None = None,
) -> None:
    from repoproof.ui.services import product_jobs

    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: job)
    monkeypatch.setattr(product_jobs, "read_product_job_log", lambda *a, **k: {"ok": False, "error": "stub"})
    monkeypatch.setattr(
        product_jobs,
        "product_job_action_result",
        lambda *a, **k: (
            action_result
            or {
                "ok": False,
                "error_code": "ACTION_RESULT_UNAVAILABLE",
                "error": "stub",
            }
        ),
    )


@pytest.mark.parametrize(
    ("label", "job"),
    [
        (
            "running",
            {"status": "RUNNING", "alive": True, "kind": "tool-build", "action": "build", "label": "demo", "pid": 4242},
        ),
        (
            "succeeded",
            {
                "status": "SUCCEEDED",
                "alive": False,
                "ok": True,
                "kind": "tool-build",
                "action": "build",
                "label": "demo",
                "pid": 4242,
                "note": "done",
            },
        ),
        (
            "failed",
            {
                "status": "FAILED",
                "alive": False,
                "ok": False,
                "kind": "tool-build",
                "action": "build",
                "label": "demo",
                "pid": 4242,
                "note": "boom",
                "error_code": "X1",
            },
        ),
        ("no-job", {}),
    ],
)
def test_activity_page_renders_every_state(label: str, job: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    _stub_jobs(monkeypatch, job)
    at = AppTest.from_file(str(PAGES / "product_activity.py"), default_timeout=60).run()
    assert not [str(e.value) for e in at.exception], f"{label} 分支渲染抛异常:{[str(e.value) for e in at.exception]}"


def test_activity_page_uses_structured_stop_instead_of_log_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest

    from repoproof.ui.services import product_mode

    job = {
        "job_id": "a" * 32,
        "status": "FAILED",
        "alive": False,
        "ok": False,
        "kind": "tool-build",
        "action": "build",
        "label": "demo",
        "pid": 4242,
        "note": "NONZERO_EXIT",
    }
    _stub_jobs(
        monkeypatch,
        job,
        action_result={
            "ok": True,
            "result": {
                "tool_name": "demo-tool",
                "pipeline_verdict": "BLOCKED",
                "product_stop_code": "STOP_HARNESS_OR_EXTERNAL",
                "failure_owner": "HARNESS",
                "reason_codes": ["UPSTREAM_WHEEL_MISSING"],
                "recommended_action": "修复 wheelhouse 后重试",
                "route": "AGENT_ADAPT",
                "agent_invoked": False,
            },
        },
    )
    monkeypatch.setattr(
        product_mode,
        "list_tools",
        lambda *_a, **_k: {
            "tools": [],
            "registry_error": None,
            "release_error": None,
        },
    )
    at = AppTest.from_file(str(PAGES / "product_activity.py"), default_timeout=60).run()
    assert not [str(e.value) for e in at.exception]
    rendered = " ".join(str(item.value) for group in (at.markdown, at.error, at.info, at.caption) for item in group)
    assert "STOP_HARNESS_OR_EXTERNAL" in rendered
    assert "UPSTREAM_WHEEL_MISSING" in rendered
    assert "修复 wheelhouse 后重试" in rendered
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Worker"] == "失败"
    assert metrics["Pipeline"] == "BLOCKED"
    assert metrics["Operational"] == "尚未形成"


def test_activity_page_projects_exported_tool_from_fresh_core_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest

    from repoproof.ui.services import product_mode

    job = {
        "job_id": "a" * 32,
        "status": "SUCCEEDED",
        "alive": False,
        "ok": True,
        "kind": "tool-build",
        "action": "tool-build-real",
        "label": "markdown build",
        "pid": 4242,
        "note": "done",
        "dest_root": "/managed/tools",
    }
    _stub_jobs(
        monkeypatch,
        job,
        action_result={
            "ok": True,
            "result": {
                "tool_name": "markdown-it-py-tool",
                "pipeline_verdict": "VERIFIED_TOOL_READY",
                "exported_path": "/managed/tools/markdown-it-py-tool",
            },
        },
    )
    monkeypatch.setattr(
        product_mode,
        "list_tools",
        lambda *_a, **_k: {
            "tools": [{
                "name": "markdown-it-py-tool",
                "operational_status": "REVIEW_REQUIRED",
                "health": "OK",
            }],
            "registry_error": None,
            "release_error": None,
        },
    )

    at = AppTest.from_file(str(PAGES / "product_activity.py"), default_timeout=60).run()

    assert not [str(e.value) for e in at.exception]
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Pipeline"] == "VERIFIED_TOOL_READY"
    assert metrics["Operational"] == "REVIEW_REQUIRED"
    assert metrics["Package"] == "OK"


def test_onboarding_keeps_historical_pipeline_visible_after_active_audit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest

    from repoproof.ui.services import product_jobs, product_journeys

    journey = product_journeys.ProductJourneyRefV1(
        journey_id="a" * 32,
        tool_name="markdown-it-py-tool",
        source_repo_url="https://github.com/executablebooks/markdown-it-py",
        draft_dir=str(tmp_path / "draft"),
        task_id="tool-markdown-it-py-tool-v2",
        dest_root=str(tmp_path / "tools"),
        updated_at="2026-08-29T00:00:00Z",
    )
    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: {})
    monkeypatch.setattr(product_journeys, "list_journeys", lambda: [journey])
    monkeypatch.setattr(
        product_journeys,
        "journey_snapshot",
        lambda _journey: {
            "journey": journey.model_dump(mode="json"),
            "phase": "ACTIVE",
            "worker": {"status": "SUCCEEDED", "action": "tool-audit"},
            "action_result": {
                "action": "tool-audit",
                "ok": True,
                "pipeline_verdict": None,
                "reason_codes": ["FRESH_INPUT_PASS"],
            },
            "task_id": journey.task_id,
            "tool_name": journey.tool_name,
            "historical_verdict": "VERIFIED_TOOL_READY",
            "operational_status": "ACTIVE",
            "package_health": "OK",
        },
    )

    at = AppTest.from_file(str(PAGES / "tool_onboarding.py"), default_timeout=60).run()

    assert not [str(e.value) for e in at.exception]
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Pipeline"] == "VERIFIED_TOOL_READY"
    assert metrics["Operational"] == "ACTIVE"


def test_primary_journey_has_no_raw_draft_path_dead_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from streamlit.testing.v1 import AppTest

    from repoproof.ui.services import product_jobs, product_journeys

    state = tmp_path / "state"
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_journeys, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: {})

    at = AppTest.from_file(str(PAGES / "tool_onboarding.py"), default_timeout=60).run()
    assert not [str(e.value) for e in at.exception]
    labels = [field.label for field in at.text_input]
    assert "草稿保存位置" not in labels
    assert "草稿目录" not in labels
    assert any("固定版本" in label for label in labels)
    assert any("LLM 分析仓库和这项能力" in button.label for button in at.button)
    assert any(button.label == "创建任务并生成草稿" for button in at.button)
    backend = next(radio for radio in at.radio if radio.label == "真实构建 Agent")
    assert backend.value.startswith("mini-swe（API 网关")


def test_primary_journey_renders_llm_repo_analysis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仓库+能力分析必须出现在主任务卡，而不是只留在高级编辑器。"""
    from streamlit.testing.v1 import AppTest

    from repoproof.ui.services import product_jobs, product_journeys

    state = tmp_path / "state"
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_journeys, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: {})
    monkeypatch.setattr(
        product_jobs,
        "online_drafter_status",
        lambda: {"ready": True, "backend": "litellm", "label": "API provider 已配置"},
    )
    overview = {
        "repository": "https://github.com/example/demo",
        "headline": "demo repository",
        "surfaces": [{"kind": "公开符号", "value": "merge", "evidence": "src/demo.py"}],
        "risks": [],
    }
    monkeypatch.setattr(
        product_jobs,
        "read_repo_overview",
        lambda *_a, **_k: {"ok": True, "overview": overview},
    )
    seen: dict[str, str] = {}

    def _summarize(_overview, *, offline, capability_goal=""):
        assert offline is False
        seen["goal"] = capability_goal
        return {"ok": True, "summary": "该入口可以支撑合并能力。", "drafter": "gateway"}

    monkeypatch.setattr(product_jobs, "summarize_repo_overview", _summarize)

    at = AppTest.from_file(str(PAGES / "tool_onboarding.py"), default_timeout=60)
    at.session_state["rp_journey_repo"] = "https://github.com/example/demo"
    at.session_state["rp_journey_capability"] = "合并多份报告并输出 JSON"
    at.run()
    button = next(b for b in at.button if "LLM 分析仓库和这项能力" in b.label)
    button.click().run()

    assert not [str(e.value) for e in at.exception]
    assert seen["goal"] == "合并多份报告并输出 JSON"
    rendered = " ".join(str(item.value) for group in (at.markdown, at.info, at.caption) for item in group)
    assert "该入口可以支撑合并能力" in rendered
    assert any("merge" in frame.value.to_string() for frame in at.dataframe)


def test_draft_journey_exposes_contract_llm_and_sample_inputs_without_advanced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage 2 is a product workbench, so its required inputs cannot hide in advanced UI."""
    from streamlit.testing.v1 import AppTest

    from repoproof.ui.services import product_jobs, product_journeys

    state = tmp_path / "state"
    draft_dir = state / "drafts" / "journey-demo"
    draft_dir.mkdir(parents=True)
    draft_text = """tool:
  name: demo-tool
  summary: demo
  interface:
    input: {format: TXT}
    output:
      format: TEXT
      contract: {media_type: text/plain, root_type: text, required: {}}
capability: {statement: convert one input, output_schema: DemoText}
source_repo:
  distribution: demo
  import_module: demo
  license: MIT
"""
    (draft_dir / "draft.yaml").write_text(draft_text, encoding="utf-8")
    (draft_dir / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    (draft_dir / "reference_impl.py").write_text("import demo\n", encoding="utf-8")
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
            "capability": {"statement": "convert one input", "output_schema": "DemoText"},
            "source_repo": {"distribution": "demo", "import_module": "demo", "license": "MIT"},
        },
        "raw_draft": draft_text,
        "examples": [],
        "reference_impl": "import demo\n",
        "gaps": "",
        "dependency_lock": {"source": "derived", "pins": ["demo==1.0"], "note": "locked"},
    }
    journey = product_journeys.ProductJourneyRefV1(
        journey_id="a" * 32,
        tool_name="demo-tool",
        source_repo_url="https://github.com/example/demo",
        draft_dir=str(draft_dir),
        dest_root=str(tmp_path / "tools"),
        agent_backend="mini-swe",
    )
    snapshot = {
        "journey": journey.model_dump(mode="json"),
        "phase": "DRAFT",
        "worker": None,
        "action_result": None,
        "task_id": None,
        "tool_name": "demo-tool",
        "draft_review": review,
        "operational_status": "UNVERIFIED",
        "package_health": "NOT_EXPORTED",
    }
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(state))
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state)
    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: {})
    monkeypatch.setattr(product_jobs, "read_managed_draft_review", lambda *_a, **_k: review)
    monkeypatch.setattr(
        product_jobs,
        "online_drafter_status",
        lambda: {"ready": True, "backend": "litellm", "label": "API provider 已配置"},
    )
    proposed: dict[str, object] = {}

    def _propose(_draft_dir: Path, *, n: int, offline: bool) -> dict:
        proposed.update({"n": n, "offline": offline})
        return {
            "ok": True,
            "drafter": "gateway",
            "note": "four upstream outputs",
            "requested": n,
            "usable_count": n,
            "confirmed_count": 0,
            "shortfall": False,
            "candidates": [
                {
                    "input_name": f"case-{index}.txt",
                    "input_text": f"input {index}",
                    "upstream_output": f"output {index}",
                    "upstream_error": None,
                    "why": "boundary",
                }
                for index in range(n)
            ],
        }

    monkeypatch.setattr(product_jobs, "propose_example_candidates", _propose)
    monkeypatch.setattr(product_journeys, "list_journeys", lambda: [journey])
    monkeypatch.setattr(product_journeys, "journey_snapshot", lambda *_a, **_k: snapshot)
    monkeypatch.setattr(product_journeys, "synthesized_read_only_cards", lambda: [])

    at = AppTest.from_file(str(PAGES / "tool_onboarding.py"), default_timeout=90).run()

    assert not [str(e.value) for e in at.exception], [str(e.value) for e in at.exception]
    assert at.session_state["rp_advanced_editor"] is False
    text_inputs = [field.label for field in at.text_input]
    text_areas = [field.label for field in at.text_area]
    buttons = [button.label for button in at.button]
    uploaders = [uploader.label for uploader in at.file_uploader]
    assert "工具名" in text_inputs
    assert "固定依赖锁（每行一个 包名==精确版本）" in text_areas
    assert "可执行输出合同" in text_areas
    assert "上游参考实现（必须真实 import 固定版本）" in text_areas
    assert "让 LLM 生成样例候选" in buttons
    assert "样例输入内容" in text_areas
    assert "你核实过的期望输出" in text_areas
    assert "输入文件" in uploaders
    assert "期望输出文件（UTF-8）" in uploaders

    next(button for button in at.button if button.label == "让 LLM 生成样例候选").click().run()
    assert not [str(e.value) for e in at.exception], [str(e.value) for e in at.exception]
    assert proposed == {"n": 4, "offline": False}
    assert len([button for button in at.button if button.label == "确认这一条并加入样例"]) == 4


def test_onboarding_page_renders_with_repo_overview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(product_jobs, "read_managed_draft_review", lambda *_args, **_kwargs: review)

    overview = {
        "repository": "https://example.invalid/demo",
        "headline": "demo does one thing well",
        "prose": "demo does one thing well\n\nIt has two modes.",
        "prose_source": "README 原文摘录(未经模型改写)",
        "quickstart": "import demo",
        "quickstart_evidence": "README.md 首个代码块",
        "facts": [{"label": "许可证", "value": "MIT", "evidence": "LICENSE", "provenance": "FACT"}],
        "surfaces": [{"kind": "公开符号", "value": "convert", "evidence": "__all__"}],
        "risks": ["无测试目录"],
        "sources": ["README.md"],
    }
    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: {})
    monkeypatch.setattr(product_jobs, "read_repo_overview", lambda *a, **k: {"ok": True, "overview": overview})

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PAGES / "tool_onboarding.py"), default_timeout=90)
    at.session_state["rp_overview"] = {"ok": True, "overview": overview}
    at.session_state["rp_advanced_editor"] = True
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
    at.session_state["rp_advanced_editor"] = True
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

    def _old_save(
        draft_dir,
        *,
        tool_name,
        summary,
        statement,
        input_format,
        output_format,
        output_schema,
        reference_impl,
        output_contract=None,
    ):  # 旧签名:不收上游身份三件
        return {"ok": True}

    monkeypatch.setattr(product_jobs, "product_job_state", lambda *a, **k: {})
    monkeypatch.setattr(product_jobs, "save_draft_review", _old_save)

    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(PAGES / "tool_onboarding.py"), default_timeout=90)
    at.session_state["rp_advanced_editor"] = True
    at.run()

    assert not [str(e.value) for e in at.exception], [str(e.value) for e in at.exception]
    said = [m.value for m in at.error] + [m.value for m in at.warning]
    assert any("重启" in m for m in said), said
    assert any("distribution" in m for m in said), said  # 点名到具体参数
