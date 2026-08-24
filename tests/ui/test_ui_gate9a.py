"""UI 底层测试:文案映射 / 只读事实源 / 隔离铁律(零 LLM)。
页面级简单/技术模式测试见 test_ui_simple_mode.py。"""

from __future__ import annotations

from pathlib import Path

from repoproof.ui.presenters import glossary, zh
from repoproof.ui.services import facts
from repoproof.ui.services.wizard import check_wizard_inputs

REPO = Path(__file__).resolve().parents[2]


# ---- 术语与文案映射 ----


def test_verdict_mappings_simple_and_technical() -> None:
    assert zh.verdict_zh("PASS_ADAPTED") == "适配后通过"
    assert glossary.verdict_simple("PASS_ADAPTED") == "适配后可使用"
    assert glossary.verdict_simple("FAIL") == "当前条件下不建议采用"
    assert glossary.verdict_simple("BLOCKED") == "缺少条件,暂时无法继续"
    assert glossary.verdict_simple("INVALID_TASK_SPEC") == "成功标准还不够清楚"
    assert glossary.verdict_simple(None) == "—"
    assert glossary.verdict_simple("SOMETHING_NEW") == "SOMETHING_NEW"  # 未知值透传,不猜


def test_unified_term_table_covers_required_entries() -> None:
    required = {
        "host_project": "你的项目", "upstream_repository": "目标仓库",
        "task_contract": "成功标准", "requirement_spec": "功能要求",
        "contract_adequacy_gate": "开始前检查", "admission": "适用性检查",
        "agent": "AI 开发助手", "harness": "运行保障机制",
        "oracle": "最终验收测试", "held_out_tests": "未向 AI 展示的独立测试",
        "adapter": "适配代码", "artifact": "结果文件", "trace": "执行记录",
        "completion_gate": "最终判定", "clean_replay": "换一个干净环境再验证",
        "policy": "操作规则检查", "host_regression": "原项目是否受影响",
        "capability_verification": "目标功能是否可用",
        "adoption_bundle": "可复核结果包", "patch_budget": "修改范围上限",
        "token_budget": "AI 使用额度", "provider_admission": "模型连接检查",
    }
    for key, val in required.items():
        assert glossary.TERM[key] == val, key


def test_error_text_three_parts() -> None:
    for code in ("INVALID_TASK_SPEC", "PROVIDER_UNAVAILABLE", "CAPABILITY_MISMATCH",
                 "BUDGET_EXHAUSTED", "POLICY_VIOLATION"):
        what, why, nxt = glossary.error_text(code)
        assert what and why and nxt, code
    what, why, nxt = glossary.error_text("UNKNOWN_CODE")
    assert "技术详情" in nxt


def test_agent_exit_simple_never_reads_as_success() -> None:
    assert glossary.agent_exit_simple("Submitted") == "AI 助手已提交"
    assert "成功" not in glossary.agent_exit_simple("Submitted")
    assert glossary.failed_node_hint("test_upstream_errors_wrapped[none]").startswith("遇到异常输入")


# ---- 向导四态(纯输入校验) ----


def test_wizard_need_info_lists_missing() -> None:
    r = check_wizard_inputs(goal="", project_path="", repo_url="", revision="",
                            needs_gpu=False, risk_confirmed=False)
    assert r.state == "NEED_INFO" and len(r.missing) == 4 and r.next_step


def test_wizard_unsupported_gpu_and_non_github() -> None:
    base = dict(goal="把 frontmatter 能力接入我的摄取模块", project_path="/p",
                revision="v1.0.0", risk_confirmed=False)
    assert check_wizard_inputs(repo_url="https://github.com/a/b", needs_gpu=True, **base).state == "UNSUPPORTED"
    r = check_wizard_inputs(repo_url="https://gitlab.com/a/b", needs_gpu=False, **base)
    assert r.state == "UNSUPPORTED" and not r.executes_third_party_code


def test_wizard_risk_review_then_ready() -> None:
    base = dict(goal="把 frontmatter 能力接入我的摄取模块", project_path="/p",
                repo_url="https://github.com/a/b", revision="v1.0.0", needs_gpu=False)
    r1 = check_wizard_inputs(risk_confirmed=False, **base)
    assert r1.state == "RISK_REVIEW" and r1.executes_third_party_code
    r2 = check_wizard_inputs(risk_confirmed=True, **base)
    assert r2.state == "READY" and r2.confirmed_facts and r2.next_step


# ---- 事实源只读 ----


def test_facts_read_the_committed_sources() -> None:
    assert facts.repo_root() == REPO
    assert facts.load_summary()["totals"]["runs_recorded"] == 12
    assert facts.load_report("frontmatter-v2-pass")["final_verdict"] == "PASS_ADAPTED"
    src = facts.adapter_source("frontmatter-v2-pass")
    assert src and "ingest_documents" in src


def test_bundle_zip_contains_evidence_only() -> None:
    import io
    import zipfile

    names = zipfile.ZipFile(io.BytesIO(facts.bundle_zip_bytes("chonkie-agent-fail"))).namelist()
    assert all(n.startswith("gate3c-real-run/") for n in names)


def test_trace_preview_parses_events() -> None:
    rows = facts.trace_preview("frontmatter-v2-pass", limit=10)
    assert rows and {"seq", "actor", "event", "摘要"} <= set(rows[0].keys())


# ---- 隔离铁律 ----


def test_ui_modules_are_read_only_and_isolated() -> None:
    """只读、不访问 LocalFlow、不读 API Key、不复制最终判定逻辑。"""
    ui_src = ""
    for p in (REPO / "src" / "repoproof" / "ui").rglob("*.py"):
        if p.name in {"live_run.py", "product_jobs.py"}:
            continue  # 两套独立执行入口各有专属 argv/边界测试
        ui_src += p.read_text(encoding="utf-8")
    for banned in ("write_text(", "write_bytes(", "shutil.copy", "os.remove", ".unlink(",
                   "XIANGMU/localflow", "import localflow", "REPOPROOF_API_KEY",
                   "litellm", "provider_gate", "recomputed ="):
        assert banned not in ui_src, f"UI source must not contain {banned!r}"


def test_no_page_hardcodes_verdict_wording() -> None:
    """§四:术语集中在 glossary/zh,页面不得各自硬编码 Verdict 文案。"""
    for p in (REPO / "src" / "repoproof" / "ui" / "pages").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        assert "适配后可使用" not in text, p.name
        assert "未满足采用合同" not in text, p.name
