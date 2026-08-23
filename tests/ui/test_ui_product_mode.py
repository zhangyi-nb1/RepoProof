"""Product Mode Studio: fact projection, safe argv and page smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from repoproof.ui.services import product_jobs, product_mode

REPO = Path(__file__).resolve().parents[2]
PAGES = REPO / "src" / "repoproof" / "ui" / "pages"

try:
    from streamlit.testing.v1 import AppTest

    HAVE_ST = True
except ImportError:  # pragma: no cover
    HAVE_ST = False

needs_streamlit = pytest.mark.skipif(not HAVE_ST, reason="streamlit (ui extra) not installed")


def _tool_world(root: Path) -> Path:
    tools = root / "tools"
    package = tools / "alpha-tool"
    package.mkdir(parents=True)
    manifest = {
        "name": "alpha-tool",
        "summary": "把 Alpha 文本转换为规范化结果",
        "source": {
            "url": "https://github.com/acme/alpha",
            "distribution": "alpha",
            "resolved_commit": "a" * 40,
        },
        "verification": {
            "verdict": "VERIFIED_TOOL_READY",
            "run_id": "tool-alpha-v1-20260824-000000",
            "contract_sha256": "b" * 64,
        },
    }
    (package / "tool.json").write_text(json.dumps(manifest), encoding="utf-8")
    evidence = package / "evidence"
    evidence.mkdir()
    (evidence / "provenance.json").write_text(
        json.dumps({
            "tool": "alpha-tool",
            "task_id": "tool-alpha-tool-v1",
            "run_id": manifest["verification"]["run_id"],
            "tool_contract_sha256": manifest["verification"]["contract_sha256"],
        }),
        encoding="utf-8",
    )
    (tools / ".repoproof-registry.json").write_text(
        json.dumps({
            "schema_version": 1,
            "tools": {
                "alpha-tool": {
                    "path": str(package),
                    "task_id": "tool-alpha-tool-v1",
                    "run_id": manifest["verification"]["run_id"],
                    "contract_sha256": manifest["verification"]["contract_sha256"],
                    "verdict": "VERIFIED_TOOL_READY",
                    "historical_verdict": "VERIFIED_TOOL_READY",
                    "summary": manifest["summary"],
                    "source": manifest["source"],
                }
            },
        }),
        encoding="utf-8",
    )
    return tools


def _decision(decision: str, reason_code: str) -> dict:
    return {
        "schema_version": 1,
        "tool": "alpha-tool",
        "task_id": "tool-alpha-tool-v1",
        "run_id": "tool-alpha-v1-20260824-000000",
        "decision": decision,
        "reason_code": reason_code,
        "reason": reason_code.replace("_", " ").lower(),
        "evidence_sha256": "c" * 64,
        "decided_at": "2026-08-24T00:00:00Z",
        "actor": "operator",
    }


def test_verified_tool_defaults_to_review_without_release_ledger(tmp_path: Path) -> None:
    tools = _tool_world(tmp_path)
    result = product_mode.list_tools(tools)
    assert result["release_ledger_present"] is False
    assert result["tools"][0]["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert result["tools"][0]["operational_status"] == "REVIEW_REQUIRED"


def test_release_ledger_folds_without_rewriting_history(tmp_path: Path) -> None:
    tools = _tool_world(tmp_path)
    ledger = tools / product_mode.RELEASE_LEDGER_NAME
    ledger.write_text(
        "\n".join([
            json.dumps(_decision("ACTIVE", "FRESH_INPUT_PASS")),
            json.dumps(_decision("REVOKED", "USER_WITHDRAWAL")),
        ]) + "\n",
        encoding="utf-8",
    )
    row = product_mode.list_tools(tools)["tools"][0]
    assert row["historical_verdict"] == "VERIFIED_TOOL_READY"
    assert row["operational_status"] == "REVOKED"
    assert row["operational_reason"] == "USER_WITHDRAWAL"


def test_bad_release_ledger_fails_closed(tmp_path: Path) -> None:
    tools = _tool_world(tmp_path)
    (tools / product_mode.RELEASE_LEDGER_NAME).write_text(
        json.dumps({"tool": "alpha-tool", "decision": "MAGIC"}) + "\n",
        encoding="utf-8",
    )
    result = product_mode.list_tools(tools)
    assert result["release_error"]
    assert result["tools"] == []
    assert result["projection_errors"][0]["reason_code"] == "RELEASE_LEDGER_INVALID"


def test_dashboard_keeps_recorded_and_operational_counts_separate(tmp_path: Path) -> None:
    tools = _tool_world(tmp_path)
    (tools / product_mode.RELEASE_LEDGER_NAME).write_text(
        json.dumps(_decision("ACTIVE", "FRESH_INPUT_PASS")) + "\n",
        encoding="utf-8",
    )
    project = tmp_path / "project"
    (project / "docs").mkdir(parents=True)
    (project / "docs" / "m4_metrics.json").write_text(json.dumps({
        "submitted": 12, "accepted": 11, "tool_ready": 10,
        "false_success": {"audited": 10, "flagged": 1},
    }), encoding="utf-8")
    out = product_mode.dashboard_snapshot(tools, project)
    assert out["historically_verified"] == 1
    assert out["operational"]["ACTIVE"] == 1
    assert out["metrics"]["tool_ready"] == 10
    assert out["false_success"] == 1


def test_product_argv_is_shell_free_and_contains_no_credentials(tmp_path: Path) -> None:
    argv = product_jobs.tool_add_argv(
        REPO,
        repo="https://github.com/acme/alpha",
        capability="把 Alpha 能力包装成本地工具",
        draft_dir=tmp_path / "draft",
        revision="v1.0.0",
        fake_drafter=True,
    )
    assert argv[-1] == "--fake-drafter"
    assert "https://github.com/acme/alpha" in argv
    assert not any("KEY" in arg or "TOKEN" in arg or "sk-" in arg for arg in argv)
    assert all(";" not in arg for arg in argv)


def test_review_editor_and_examples_only_write_inside_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    doc = {
        "task_id": "tool-alpha-tool-v1",
        "tool": {
            "name": "alpha-tool", "summary": "",
            "interface": {
                "input": {"format": ""}, "output": {"format": ""},
            },
        },
        "capability": {"statement": "", "output_schema": ""},
    }
    (draft / "draft.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    (draft / "reference_impl.py").write_text("", encoding="utf-8")
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")

    saved = product_jobs.save_draft_review(
        draft, tool_name="alpha-tool", summary="Alpha 转换",
        statement="读取 Alpha 输入并返回规范化文本", input_format="TXT",
        output_format="TXT", output_schema="AlphaText",
        reference_impl="import alpha\n", output_contract={},
    )
    assert saved["ok"]
    added = product_jobs.add_golden_example(
        draft, input_name="a.txt", input_bytes=b"a",
        expected_name="a.expected.txt", expected_bytes=b"A",
    )
    assert added["ok"]
    assert (draft / "examples" / "inputs" / "a.txt").read_bytes() == b"a"
    examples = yaml.safe_load((draft / "examples.yaml").read_text())
    assert examples["examples"] == [
        {"input_file": "inputs/a.txt", "expected_file": "expected/a.expected.txt"}]
    review = product_jobs.read_managed_draft_review(draft)
    assert review["ok"] is True
    assert review["reference_impl"] == "import alpha\n"


def test_activity_log_reader_never_follows_untrusted_state_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    logs = state_root / "logs"
    logs.mkdir(parents=True)
    valid = logs / "tool-build.log"
    valid.write_text("safe log\n", encoding="utf-8")
    assert product_jobs.read_product_job_log({"log": str(valid)}) == {
        "ok": True,
        "text": "safe log\n",
    }

    outside = tmp_path / "secret.txt"
    outside.write_text("must not render\n", encoding="utf-8")
    blocked = product_jobs.read_product_job_log({"log": str(outside)})
    assert blocked["ok"] is False
    assert "受管目录" in blocked["error"]

    linked = logs / "linked.log"
    linked.symlink_to(outside)
    blocked = product_jobs.read_product_job_log({"log": str(linked)})
    assert blocked["ok"] is False


def test_product_paths_and_github_url_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "draft.yaml").write_text("{}\n", encoding="utf-8")

    escaped = product_jobs.start_tool_add(
        repo="https://github.com/acme/demo",
        capability="把公开能力包装为本地离线工具",
        draft_dir=outside / "new-draft",
        fake_drafter=True,
    )
    assert escaped["ok"] is False
    assert "受管目录" in escaped["error"]

    drafts = state_root / "drafts"
    drafts.mkdir(parents=True)
    linked = drafts / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    linked_result = product_jobs.save_draft_review(
        linked,
        tool_name="alpha-tool",
        summary="summary",
        statement="statement",
        input_format="text",
        output_format="text",
        output_schema="text",
        reference_impl="",
    )
    assert linked_result["ok"] is False
    assert "symlink" in linked_result["error"]

    spoofed = product_jobs.start_tool_add(
        repo="https://github.com.evil.example/acme/demo",
        capability="把公开能力包装为本地离线工具",
        draft_dir=drafts / "spoofed",
        fake_drafter=True,
    )
    assert spoofed["ok"] is False
    assert "公开 GitHub" in spoofed["error"]

    broad, broad_error = product_jobs._validated_dest_root(Path.home())
    assert broad is None
    assert "过于宽泛" in str(broad_error)


def test_build_reports_invalid_task_version_lineage_without_starting_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "state"
    monkeypatch.setattr(product_jobs, "ui_state_root", lambda: state_root)
    draft = state_root / "drafts" / "draft"
    (draft / "examples").mkdir(parents=True)
    (draft / "draft.yaml").write_text(
        yaml.safe_dump({"tool": {"name": "alpha-tool"}}),
        encoding="utf-8",
    )
    (draft / "reference_impl.py").write_text("", encoding="utf-8")
    (draft / "examples.yaml").write_text("examples: []\n", encoding="utf-8")
    monkeypatch.setattr(
        product_jobs,
        "next_tool_task_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("malformed task version anchor")
        ),
    )
    monkeypatch.setattr(
        product_jobs,
        "_start_product_job",
        lambda *_args, **_kwargs: pytest.fail("worker must not start"),
    )

    result = product_jobs.start_tool_build(
        draft_dir=draft,
        dest_root=tmp_path / "tools",
        rehearsal_only=True,
    )

    assert result["ok"] is False
    assert result["error_code"] == "TASK_VERSION_LINEAGE_INVALID"


def _all_text(at) -> str:
    values: list[str] = []
    for kind in (
        "title", "header", "subheader", "markdown", "caption", "info",
        "success", "warning", "error", "metric", "button", "selectbox",
        "text_input", "text_area",
    ):
        for element in getattr(at, kind, []):
            values.append(str(getattr(element, "value", "")))
            values.append(str(getattr(element, "label", "")))
    return "\n".join(values)


@needs_streamlit
@pytest.mark.parametrize(
    ("page", "marker"),
    [
        ("product_home.py", "GitHub 能力"),
        ("tool_onboarding.py", "从一句需求开始"),
        ("product_activity.py", "每一步都看得见"),
        ("tool_library.py", "AI Tool Library"),
        ("trust_dashboard.py", "成功率不是唯一答案"),
    ],
)
def test_product_pages_render_without_user_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, page: str, marker: str,
) -> None:
    monkeypatch.setenv("REPOPROOF_TOOL_ROOT", str(tmp_path / "tools"))
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(tmp_path / "state"))
    at = AppTest.from_file(str(PAGES / page), default_timeout=30)
    at.run()
    assert not at.exception
    assert marker in _all_text(at)


@needs_streamlit
def test_library_shows_historical_and_operational_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _tool_world(tmp_path)
    monkeypatch.setenv("REPOPROOF_TOOL_ROOT", str(tools))
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(tmp_path / "state"))
    at = AppTest.from_file(str(PAGES / "tool_library.py"), default_timeout=30)
    at.run()
    assert not at.exception
    text = _all_text(at)
    assert "alpha-tool" in text
    assert "VERIFIED_TOOL_READY" in text
    assert "待审核" in text


def test_navigation_keeps_product_and_benchmark_apps_separate() -> None:
    ui = REPO / "src" / "repoproof" / "ui"
    product_source = (ui / "app.py").read_text(encoding="utf-8")
    lab_source = (ui / "lab_app.py").read_text(encoding="utf-8")
    for title in ("工作台", "新建工具", "运行活动", "工具库", "可信仪表盘"):
        assert title in product_source
        assert title not in lab_source
    for title in ("开始新任务", "宿主任务 T1–T4", "结果报告", "历史记录", "系统设置"):
        assert title in lab_source
        assert title not in product_source
    assert "Benchmark Lab" not in product_source
    assert "product_theme" not in lab_source


def test_runtime_services_have_separate_state_domains() -> None:
    services = REPO / "src" / "repoproof" / "ui" / "services"
    lab_source = (services / "live_run.py").read_text(encoding="utf-8")
    product_source = (services / "product_jobs.py").read_text(encoding="utf-8")
    assert "product_job_state" not in lab_source
    assert "product_mode" not in lab_source
    assert "runs/.ui_live.lock" not in product_source
    assert "benchmarks/" not in product_source
    assert "docs/evidence" not in product_source


def test_public_launchers_use_distinct_apps_and_ports() -> None:
    scripts = REPO / "scripts"
    product = (scripts / "run_ui.sh").read_text(encoding="utf-8")
    product_live = (scripts / "run_ui_live.sh").read_text(encoding="utf-8")
    lab = (scripts / "run_lab_ui.sh").read_text(encoding="utf-8")
    lab_live = (scripts / "run_lab_ui_live.sh").read_text(encoding="utf-8")
    assert "ui/app.py" in product and "--server.port 8501" in product
    assert "ui/app.py" in product_live and "--server.port 8501" in product_live
    assert "ui/lab_app.py" in lab and "--server.port 8502" in lab
    assert "ui/lab_app.py" in lab_live and "--server.port 8502" in lab_live
    assert "lab_app.py" not in product and "ui/app.py" not in lab


@needs_streamlit
def test_navigation_entrypoint_accepts_all_icons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOPROOF_TOOL_ROOT", str(tmp_path / "tools"))
    monkeypatch.setenv("REPOPROOF_UI_STATE_ROOT", str(tmp_path / "state"))
    at = AppTest.from_file(str(REPO / "src" / "repoproof" / "ui" / "app.py"))
    at.run()
    assert not at.exception


@needs_streamlit
def test_benchmark_lab_entrypoint_renders_independently() -> None:
    at = AppTest.from_file(
        str(REPO / "src" / "repoproof" / "ui" / "lab_app.py"),
        default_timeout=30,
    )
    at.run()
    assert not at.exception
    assert "把一个开源仓库的能力" in _all_text(at)
