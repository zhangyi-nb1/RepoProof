"""Gate 9A — 中文只读工作台测试(pytest + streamlit AppTest,零 LLM)。"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.ui.presenters import zh
from repoproof.ui.services import facts

REPO = Path(__file__).resolve().parents[2]
PAGES = REPO / "src" / "repoproof" / "ui" / "pages"

try:
    from streamlit.testing.v1 import AppTest

    HAVE_ST = True
except ImportError:  # pragma: no cover — ui extra not installed
    HAVE_ST = False

needs_streamlit = pytest.mark.skipif(not HAVE_ST, reason="streamlit (ui extra) not installed")

KEY_MARKERS = ("sk-", "REPOPROOF_API_KEY", "DEEPSEEK_API_KEY", "api_key")


def _tree_text(at) -> str:
    parts: list[str] = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "info",
                 "success", "warning", "error", "metric", "button", "selectbox"):
        for el in getattr(at, kind, []):
            parts.append(str(getattr(el, "value", "")) + str(getattr(el, "label", "")))
    return "\n".join(parts)


# ---- presenters:中文映射 ----


def test_verdict_mapping_complete_and_chinese() -> None:
    assert zh.verdict_zh("PASS_ADAPTED") == "适配后通过"
    assert zh.verdict_zh("FAIL") == "未满足采用合同"
    assert zh.verdict_zh("INVALID_TASK_SPEC") == "任务规格不充分"
    assert zh.verdict_zh(None) == "—"
    assert zh.verdict_zh("SOMETHING_NEW") == "SOMETHING_NEW"  # 未知值原样透传,不猜


def test_agent_exit_and_owner_mappings() -> None:
    assert zh.agent_exit_zh("Submitted") == "Agent 主动提交"
    assert zh.agent_exit_zh("LimitsExceeded") == "Agent 预算耗尽"
    assert zh.failure_owner_zh("SEMANTIC_SUBSTITUTION") == "Agent 适配器"
    assert zh.failure_owner_zh("CONTRACT_UNDERSPECIFICATION") == "任务作者"
    combo = zh.failure_owner_zh("CONTRACT_UNDERSPECIFICATION + CONTRACT_REQUIREMENT_OMISSION")
    assert "任务作者" in combo and "Agent 适配器" in combo
    assert zh.dash(None) == "—" and zh.dash(0) == "0"


# ---- services:事实源只读 ----


def test_facts_read_the_committed_sources() -> None:
    assert facts.repo_root() == REPO
    summary = facts.load_summary()
    assert summary["totals"]["runs_recorded"] == 12
    row = facts.summary_row("frontmatter-v2-agent-g72")
    assert row and row["final_verdict"] == "PASS_ADAPTED"
    assert facts.load_report("frontmatter-v2-pass")["final_verdict"] == "PASS_ADAPTED"
    src = facts.adapter_source("frontmatter-v2-pass")
    assert src and "ingest_documents" in src
    files = dict(facts.evidence_files("frontmatter-v2-pass"))
    assert any("trace" in p.name for p in files.values())


def test_bundle_zip_contains_evidence_only() -> None:
    import io
    import zipfile

    data = facts.bundle_zip_bytes("chonkie-agent-fail")
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert all(n.startswith("gate3c-real-run/") for n in names)
    assert any(n.endswith("report.json") for n in names)


def test_trace_preview_parses_events() -> None:
    rows = facts.trace_preview("frontmatter-v2-pass", limit=10)
    assert rows and {"seq", "actor", "event", "摘要"} <= set(rows[0].keys())


def test_ui_modules_are_read_only_and_isolated() -> None:
    """UI 铁律:不写 evidence、不访问 LocalFlow、不读 API Key、不复制 gate 逻辑。"""
    ui_src = ""
    for p in (REPO / "src" / "repoproof" / "ui").rglob("*.py"):
        ui_src += p.read_text(encoding="utf-8")
    for banned in ("write_text(", "write_bytes(", "shutil.copy", "os.remove", ".unlink(",
                   "XIANGMU/localflow", "import localflow", "REPOPROOF_API_KEY",
                   "litellm", "provider_gate", "recomputed ="):
        assert banned not in ui_src, f"UI source must not contain {banned!r}"


# ---- AppTest:三个页面 ----


@needs_streamlit
def test_home_page_renders_chinese_cases_no_secrets() -> None:
    at = AppTest.from_file(str(PAGES / "home.py"), default_timeout=30)
    at.run()
    assert not at.exception
    text = _tree_text(at)
    for expected in ("RepoProof Studio", "中文工作台", "Front Matter 正向案例",
                     "Chonkie 负向案例", "rank_bm25 负向案例", "适配后通过",
                     "能力边界", "不是单变量提升实验" if "不是单变量提升实验" in text else "corrected-spec"):
        assert expected in text, expected
    for marker in KEY_MARKERS:
        assert marker not in text, marker


@needs_streamlit
def test_case_view_positive_default() -> None:
    at = AppTest.from_file(str(PAGES / "case_view.py"), default_timeout=30)
    at.run()
    assert not at.exception
    labels = {m.label: m.value for m in at.metric}
    assert labels["最终 Verdict"] == "适配后通过"
    assert labels["Capability"] == "18/18" and labels["宿主回归"] == "3/3"
    assert labels["重放"] == "干净采用重放"
    text = _tree_text(at)
    assert "Agent 结束原因" in text and "从不参与判定" in text
    assert "Agent 主动提交" in text  # Submitted 的中文
    for marker in KEY_MARKERS:
        assert marker not in text, marker


@needs_streamlit
def test_case_view_negative_via_session_state() -> None:
    at = AppTest.from_file(str(PAGES / "case_view.py"), default_timeout=30)
    at.session_state["case"] = "chonkie-agent-fail"
    at.run()
    assert not at.exception
    labels = {m.label: m.value for m in at.metric}
    assert labels["最终 Verdict"] == "未满足采用合同"
    assert labels["Capability"] == "31/33"
    text = _tree_text(at)
    assert "失败复现重放" in text or "负向案例无干净重放" in text


@needs_streamlit
def test_case_view_verify_button_recomputes_gate() -> None:
    at = AppTest.from_file(str(PAGES / "case_view.py"), default_timeout=60)
    at.session_state["case"] = "chonkie-agent-fail"
    at.run()
    btn = next(b for b in at.button if "验证 Bundle" in b.label)
    btn.click().run()
    assert not at.exception
    text = _tree_text(at)
    assert "与记录一致:是" in text and "模型调用:0" in text


@needs_streamlit
def test_case_view_downloads_present() -> None:
    """AppTest 对 download_button 无专属 accessor:渲染必须无异常
    (数据 bytes 在渲染时即被读取),源码必须提供单文件 + Bundle ZIP。"""
    at = AppTest.from_file(str(PAGES / "case_view.py"), default_timeout=30)
    at.run()
    assert not at.exception
    src = (PAGES / "case_view.py").read_text(encoding="utf-8")
    assert src.count("st.download_button") >= 2  # 单文件下载 + Bundle ZIP
    assert "bundle_zip_bytes" in src and "application/zip" in src


@needs_streamlit
def test_history_page_filters_and_no_inference() -> None:
    at = AppTest.from_file(str(PAGES / "history.py"), default_timeout=30)
    at.run()
    assert not at.exception
    text = _tree_text(at)
    assert "12 次记录运行" in text and "1 次 PASS_ADAPTED" in text
    assert "不做成功率归因" in text
    for marker in KEY_MARKERS:
        assert marker not in text, marker
