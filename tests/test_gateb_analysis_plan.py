"""Gate B(RFC-008)— 宿主模式/八策略/Human Gate 扩展/CLI JSON 的钉死测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repoproof.adoption.admission.admission_report import decide
from repoproof.adoption.analysis.host_analyzer import (
    BLANK_PROJECT,
    GIT_PROJECT,
    INVALID_PATH,
    PLAIN_PROJECT,
    Finding,
    analyze_host_project,
    detect_host_mode,
)
from repoproof.adoption.analysis.repository_analyzer import RepositoryReport
from repoproof.adoption.delivery.intent_store import load_frozen_intents, save_frozen_intent
from repoproof.adoption.intent.intent_parser import parse_intent
from repoproof.adoption.planning.adoption_plan import build_plan
from repoproof.adoption.planning.human_gate import (
    ACK_TEXT,
    HumanGateError,
    confirm_plan,
    require_confirmed,
)
from repoproof.adoption.planning.strategy_selector import (
    CLONE_AS_BASE,
    HTTP_SIDECAR,
    PYTHON_ADAPTER,
    WRAPPER_FACADE,
    select_strategies,
)

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable


def _repo_report(**kw) -> RepositoryReport:
    base = dict(
        repository="https://github.com/x/demo-lib",
        is_public=Finding.fact(True, "test"),
        commit=Finding.fact("a" * 40, "test"),
        license=Finding.fact("MIT", "LICENSE"),
        python_version=Finding.fact(">=3.10", "pyproject"),
        install_method=Finding.fact("pip", "pyproject"),
    )
    base.update(kw)
    return RepositoryReport(**base)


# ---------- 宿主模式四态(§14.1 Host Mode) ----------

def test_blank_mode_truly_empty_and_writable(tmp_path: Path) -> None:
    assert detect_host_mode(tmp_path).value == BLANK_PROJECT


def test_blank_mode_rejects_hidden_business_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("KEY=1", encoding="utf-8")
    assert detect_host_mode(tmp_path).value == PLAIN_PROJECT


def test_blank_mode_rejects_nested_hidden_file(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / ".hidden").write_text("x", encoding="utf-8")
    assert detect_host_mode(tmp_path).value == PLAIN_PROJECT


def test_blank_mode_rejects_symlink(tmp_path: Path) -> None:
    (tmp_path / "link").symlink_to(REPO / "README.md")
    assert detect_host_mode(tmp_path).value == PLAIN_PROJECT


def test_blank_mode_ignores_ds_store_only(tmp_path: Path) -> None:
    (tmp_path / ".DS_Store").write_bytes(b"junk")
    assert detect_host_mode(tmp_path).value == BLANK_PROJECT


def test_unexplained_git_dir_is_not_blank(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    mode = detect_host_mode(tmp_path)
    assert mode.value in (GIT_PROJECT, PLAIN_PROJECT)
    assert mode.value != BLANK_PROJECT


def test_invalid_path_mode() -> None:
    assert detect_host_mode("/nonexistent/definitely-missing-xyz").value == INVALID_PATH


def test_git_project_facts_on_repoproof_itself() -> None:
    rep = analyze_host_project(REPO)
    assert rep.host_mode.value == GIT_PROJECT
    assert rep.git_commit.provenance == "FACT" and len(str(rep.git_commit.value)) == 40
    assert rep.tree_fingerprint.provenance in ("FACT", "UNKNOWN")


def test_blank_report_declares_regression_na(tmp_path: Path) -> None:
    rep = analyze_host_project(tmp_path)
    assert rep.host_mode.value == BLANK_PROJECT
    assert "N/A" in rep.test_command.evidence


# ---------- 八策略选择器(§7.2) ----------

def test_python_adapter_recommended_when_public_api(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
    host = analyze_host_project(tmp_path)
    repo = _repo_report(public_api=[Finding.fact("demo.run", "src")])
    strategies, rec, _, choice = select_strategies(host, repo)
    assert not choice and "PYTHON_ADAPTER" in rec
    kinds = {s.kind for s in strategies}
    assert PYTHON_ADAPTER in kinds and WRAPPER_FACADE in kinds


def test_cli_subprocess_recommended_when_only_cli(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
    host = analyze_host_project(tmp_path)
    repo = _repo_report(cli_entry_points=[Finding.fact("demo-cli", "console_scripts")])
    _, rec, _, _ = select_strategies(host, repo)
    assert "CLI_SUBPROCESS" in rec


def test_http_sidecar_recommended_for_service_repo(tmp_path: Path) -> None:
    (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
    host = analyze_host_project(tmp_path)
    repo = _repo_report(dependencies=["fastapi", "uvicorn"])
    strategies, rec, _, _ = select_strategies(host, repo)
    assert "HTTP_SIDECAR" in rec
    assert any(s.kind == HTTP_SIDECAR for s in strategies)


def test_no_default_adapter_for_everything(tmp_path: Path) -> None:
    """禁止所有任务默认 adapter:无 API/CLI/服务 → 推荐 wrapper 而非 adapter。"""
    (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
    host = analyze_host_project(tmp_path)
    repo = _repo_report()
    strategies, rec, _, _ = select_strategies(host, repo)
    assert "WRAPPER_FACADE" in rec
    assert not any(s.kind == PYTHON_ADAPTER for s in strategies)


def test_blank_host_gives_three_plans_requiring_choice(tmp_path: Path) -> None:
    host = analyze_host_project(tmp_path)
    repo = _repo_report(public_api=[Finding.fact("demo.run", "src")])
    strategies, rec, _, choice = select_strategies(host, repo)
    assert choice is True and rec == ""
    assert [s.kind for s in strategies] == [CLONE_AS_BASE, WRAPPER_FACADE, PYTHON_ADAPTER]


# ---------- 空白项目准入(§4.2) ----------

def test_blank_admission_does_not_demand_host_tests(tmp_path: Path) -> None:
    host = analyze_host_project(tmp_path)
    repo = _repo_report(public_api=[Finding.fact("demo.run", "src")],
                        gpu=Finding.fact(False, "deps"))
    adm = decide(host, repo)
    assert all("测试命令" not in q for q in adm.questions)
    assert any("空白项目模式" in f for f in adm.confirmed_facts)


def test_invalid_host_path_blocks(tmp_path: Path) -> None:
    host = analyze_host_project(tmp_path / "missing")
    repo = _repo_report()
    adm = decide(host, repo)
    assert adm.status == "UNSUPPORTED"
    assert any("路径无效" in b for b in adm.blockers)


# ---------- Human Gate 扩展(§7.3) ----------

def _ready_pair(tmp_path: Path, blank: bool = False):
    if blank:
        host = analyze_host_project(tmp_path)
    else:
        (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "h"\nrequires-python = ">=3.10"\ndependencies = []\n',
            encoding="utf-8")
        (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        host = analyze_host_project(tmp_path)
    repo = _repo_report(public_api=[Finding.fact("demo.run", "src")],
                        gpu=Finding.fact(False, "deps"),
                        tests=Finding.fact("tests/", "layout"))
    adm = decide(host, repo)
    intent = parse_intent("把 demo-lib 的解析能力接入我的项目,输出结构化结果")
    plan = build_plan(intent, host, repo, adm,
                      accepted_risks=list(adm.risks) or None)
    return intent, plan, adm


def test_blank_confirm_requires_strategy_choice(tmp_path: Path) -> None:
    intent, plan, adm = _ready_pair(tmp_path, blank=True)
    assert plan.requires_user_choice
    kw = dict(answers=dict.fromkeys(plan.questions, "无"), user_ack=ACK_TEXT,
              confirmed_at="2026-08-08T00:00:00Z",
              accepted_risks=list(adm.risks) or None, intent_dict=intent.to_dict())
    with pytest.raises(HumanGateError, match="选定一种建站计划"):
        confirm_plan(plan, adm, **kw)
    frozen = confirm_plan(plan, adm, chosen_strategy=plan.strategies[0].name, **kw)
    assert frozen.strategy == plan.strategies[0].name
    assert frozen.intent_sha256 and frozen.success_criteria_sha256


def test_intent_sha_binding_and_tamper_invalidation(tmp_path: Path) -> None:
    intent, plan, adm = _ready_pair(tmp_path)
    frozen = confirm_plan(
        plan, adm, answers=dict.fromkeys(plan.questions, "无"), user_ack=ACK_TEXT,
        confirmed_at="2026-08-08T00:00:00Z", accepted_risks=list(adm.risks) or None,
        intent_dict=intent.to_dict(), chosen_strategy=plan.recommended)
    require_confirmed(frozen, plan, adm, intent_dict=intent.to_dict())
    tampered = intent.to_dict() | {"goal": "改掉目标"}
    with pytest.raises(HumanGateError, match="意图草稿"):
        require_confirmed(frozen, plan, adm, intent_dict=tampered)


def test_wrong_strategy_name_rejected(tmp_path: Path) -> None:
    intent, plan, adm = _ready_pair(tmp_path)
    with pytest.raises(HumanGateError, match="不在计划候选中"):
        confirm_plan(plan, adm, answers=dict.fromkeys(plan.questions, "无"),
                     user_ack=ACK_TEXT, confirmed_at="t",
                     accepted_risks=list(adm.risks) or None,
                     chosen_strategy="不存在的方案")


def test_intent_store_idempotent(tmp_path: Path) -> None:
    p1 = save_frozen_intent(tmp_path, {"a": 1})
    p2 = save_frozen_intent(tmp_path, {"a": 1})
    assert p1 == p2 and len(load_frozen_intents(tmp_path)) == 1


# ---------- Plan 阶段零副作用(§7.1) ----------

def test_plan_stage_writes_nothing(tmp_path: Path) -> None:
    """分析 + 准入 + 计划全链路后,宿主目录文件集与 mtime 不变。"""
    (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
    snap = {str(p): p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    host = analyze_host_project(tmp_path)
    repo = _repo_report(public_api=[Finding.fact("demo.run", "src")])
    adm = decide(host, repo)
    if adm.status in ("READY", "RISK_REVIEW"):
        build_plan(parse_intent("接入 demo 能力"), host, repo, adm,
                   accepted_risks=list(adm.risks) or None)
    assert snap == {str(p): p.stat().st_mtime_ns for p in tmp_path.rglob("*")}


# ---------- CLI 稳定 JSON(§5.1) ----------

def _run_cli(*args: str) -> dict:
    proc = subprocess.run(
        [PY, "-m", "repoproof.cli", *args],
        capture_output=True, text=True, timeout=120, check=False,
        cwd=str(REPO), env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )
    assert proc.returncode == 0, proc.stderr[-500:]
    return json.loads(proc.stdout)


def test_cli_analyze_host_json_envelope(tmp_path: Path) -> None:
    out = _run_cli("analyze-host", "--path", str(tmp_path), "--json")
    assert out["schema_version"] == 1 and out["kind"] == "host_project_report"
    assert out["report"]["host_mode"]["value"] == BLANK_PROJECT


def test_cli_analyze_source_local_json(tmp_path: Path) -> None:
    (tmp_path / "LICENSE").write_text("MIT License", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = []\n', encoding="utf-8")
    out = _run_cli("analyze-source", "--local-path", str(tmp_path), "--json")
    assert out["kind"] == "repository_report"
    assert out["report"]["license"]["value"] == "MIT"


def test_cli_admission_json_pipeline(tmp_path: Path) -> None:
    host_json = tmp_path / "host.json"
    src_json = tmp_path / "src.json"
    blank_dir = tmp_path / "blank"
    blank_dir.mkdir()
    host_json.write_text(json.dumps(
        _run_cli("analyze-host", "--path", str(blank_dir), "--json")), encoding="utf-8")
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "LICENSE").write_text("MIT License", encoding="utf-8")
    (repo_dir / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nrequires-python = ">=3.10"\ndependencies = []\n',
        encoding="utf-8")
    src_json.write_text(json.dumps(
        _run_cli("analyze-source", "--local-path", str(repo_dir), "--json")), encoding="utf-8")
    out = _run_cli("admission", "--host-report", str(host_json),
                   "--source-report", str(src_json), "--json")
    assert out["kind"] == "admission_report"
    assert out["report"]["status"] in ("READY", "NEED_INFORMATION", "RISK_REVIEW", "UNSUPPORTED")
