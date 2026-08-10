"""宿主级 guided 驱动的钉死测试(TESTPLAN-V2 Phase 1 接线件)。

零模型零会话:只钉契约解析、提示投影纯净性、护栏拒绝、指纹对账集、
冒烟脚本形状与预算映射——全链行为由 fake-model 冒烟(host-run --fake)
在真实副本上验证,不进本套件(耗时数分钟)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from repoproof.harness.host_guard import HostGuardError
from repoproof.runner.host_guided import (
    HostContract,
    HostGuidedRunner,
    HostRunError,
    _expected_regression_passed,
    _fake_script,
    build_host_prompt,
    integrity_scope,
)

T1_CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "benchmarks" / "v2" / "tasks" / "t1_fastapi_mcp" / "contract.yaml"
)


def _t1() -> HostContract:
    contract, _sha = HostContract.load(T1_CONTRACT)
    return contract


# ---------------------------------------------------------------- 契约解析
def test_frozen_t1_contract_parses_with_v2_budgets() -> None:
    """v2 重冻结(2026-08-09 用户决定):每轮语义 30/80/500k/50k。"""
    c = _t1()
    assert c.task_id == "t1-offerclaw-fastapi-mcp-v1"
    assert c.kind == "host_integrated"
    b = c.budgets
    assert b.semantics == "per_round" and b.per_round
    assert (b.max_rounds, b.max_model_calls, b.max_commands) == (3, 30, 80)
    assert (b.max_patch_files, b.max_patch_lines) == (10, 800)
    assert (b.max_input_tokens_total, b.max_output_tokens_total) == (500_000, 50_000)
    mapped = b.as_budgets()
    assert mapped.max_agent_steps == 30
    assert mapped.max_patch_lines == 800


def test_contract_rejects_non_host_kind(tmp_path: Path) -> None:
    bad = tmp_path / "c.yaml"
    bad.write_text(
        T1_CONTRACT.read_text(encoding="utf-8").replace(
            "kind: host_integrated", "kind: sample_seam"),
        encoding="utf-8")
    with pytest.raises(ValueError, match="host_integrated"):
        HostContract.load(bad)


def test_regression_baseline_parser() -> None:
    assert _expected_regression_passed("591 passed, 7 skipped, 0 failed") == 591
    assert _expected_regression_passed("") == 0


# ---------------------------------------------------------------- 提示纯净性
def test_prompt_contains_requirements_and_budgets_never_oracle() -> None:
    c = _t1()
    prompt = build_host_prompt(c, wheel_note="wheelhouse test")
    for rid in ("R1-feature-flag", "R4-allowlist", "R8-real-upstream"):
        assert rid in prompt
    # v2 每轮语义必须向 agent 如实披露(公平性)
    assert "PER ROUND" in prompt and "800 lines" in prompt
    low = prompt.lower()
    # 隐藏验收的**存在性**可以说(冻结契约 forbidden 条款自带"oracle"
    # 一词,属公开纪律);但 oracle 的路径/用例名/内部常量绝不进入提示
    for leak in ("oracle/", "oracle_snapshot", "test_h1", "test_h5",
                 "hidden_oracle_command",
                 "LEGACY_MCP_TOOLS_FROZEN".lower(), "forbidden_tools"):
        assert leak not in low, f"提示泄漏隐藏验收线索:{leak}"
    assert "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in prompt


def test_prompt_discloses_replay_dependency_semantics() -> None:
    """重放从声明重建环境是公平性关键披露——agent 必须被告知。"""
    prompt = build_host_prompt(_t1(), wheel_note="w")
    assert "requirements.txt" in prompt
    assert "CLEAN environment" in prompt


# ---------------------------------------------------------------- 护栏
def test_runner_rejects_protected_host_copy(tmp_path: Path, monkeypatch) -> None:
    fake_main = tmp_path / "fake_offerclaw_main"
    fake_main.mkdir()
    monkeypatch.setenv("REPOPROOF_PROTECTED_DIRS", str(fake_main))
    contract_dir = tmp_path / "task"
    (contract_dir / "oracle").mkdir(parents=True)
    (contract_dir / "public_tests").mkdir()
    text = T1_CONTRACT.read_text(encoding="utf-8").replace(
        "copy_path: ~/RepoProofBench/offerclaw-t1-fastapi-mcp",
        f"copy_path: {fake_main}")
    c = contract_dir / "contract.yaml"
    c.write_text(text, encoding="utf-8")
    with pytest.raises(HostGuardError):
        HostGuidedRunner(c, Path(__file__).resolve().parents[1])


def test_runner_requires_upstream_and_wheelhouse(tmp_path: Path) -> None:
    host_copy = tmp_path / "host_copy"
    host_copy.mkdir()
    contract_dir = tmp_path / "task"
    (contract_dir / "oracle").mkdir(parents=True)
    (contract_dir / "public_tests").mkdir()
    text = T1_CONTRACT.read_text(encoding="utf-8").replace(
        "copy_path: ~/RepoProofBench/offerclaw-t1-fastapi-mcp",
        f"copy_path: {host_copy}").replace(
        "resolved_commit: e5cad13cabfc725bbcb047e526816d887d96da62",
        "resolved_commit: abcdef0000000000000000000000000000000000")
    c = contract_dir / "contract.yaml"
    c.write_text(text, encoding="utf-8")
    with pytest.raises(HostRunError, match="上游固定快照缺失"):
        HostGuidedRunner(c, Path(__file__).resolve().parents[1])


# ---------------------------------------------------------------- 指纹对账集
def test_integrity_scope_excludes_repoproof_itself() -> None:
    root = Path(__file__).resolve().parents[1]
    scope = integrity_scope(root)
    import os

    norm = os.path.realpath(str(root)).lower().rstrip("/")
    assert norm not in scope
    assert all("offerclaw" in d or "localflow" in d or "repoproof" not in d
               for d in scope)


# ---------------------------------------------------------------- 冒烟脚本
def test_fake_scripts_shape() -> None:
    runner = _RunnerStub()
    noop = _fake_script("noop", runner)
    assert "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in noop[0]["actions"][0]["command"]
    pos = _fake_script("positive", runner)
    joined = "\n".join(a["command"] for step in pos for a in step["actions"])
    assert "pip install" in joined and "mcp<2.0" in joined
    assert "sdk_mcp.py" in joined
    assert "requirements.txt" in joined, "正控冒烟必须声明依赖(重放语义)"
    assert joined.strip().endswith("COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT")
    with pytest.raises(ValueError):
        _fake_script("nonsense", runner)


class _RunnerStub:
    task_dir = T1_CONTRACT.parent


def test_enforcement_input_cap_inward_for_per_round_only() -> None:
    """v2 修订(用户决策):per_round 输入执法线内移 50k,政策线不变。"""
    from repoproof.runner.host_guided import TOKEN_STOP_MARGIN, enforcement_input_cap

    c = _t1()
    assert c.budgets.per_round
    assert enforcement_input_cap(c.budgets) == 500_000 - TOKEN_STOP_MARGIN
    total_style = c.budgets.model_copy(update={"semantics": "total"})
    assert enforcement_input_cap(total_style) == 500_000


def test_host_score_has_no_diff_term() -> None:
    """v2 修订(用户决策,run -211400 实证):宿主评分不含 diff 项——
    同分脚手架是平行探索不是退步,不得因"改动更大"被回滚。"""
    from repoproof.adoption.repair.repair_loop import RoundResult
    from repoproof.runner.host_guided import hard_signals, host_score

    small = RoundResult(adapter_snapshot="a", passed=5, diff_lines=0)
    big = RoundResult(adapter_snapshot="b", passed=5, diff_lines=999)
    assert host_score(small) == host_score(big), "diff 大小不得影响排序分"
    better = RoundResult(adapter_snapshot="c", passed=6, diff_lines=999)
    assert host_score(better) > host_score(big)
    # 硬信号:通过数下降/回归破坏/策略违规才算真退步
    h_base = hard_signals(collected_ok=True, policy_violations=0,
                          regression_failed=0, passed=5)
    h_tie = hard_signals(collected_ok=True, policy_violations=0,
                         regression_failed=0, passed=5)
    h_regress = hard_signals(collected_ok=True, policy_violations=0,
                             regression_failed=2, passed=5)
    assert not (h_tie < h_base) and (h_regress < h_base)


def test_replay_eligibility_ignores_budget_marker() -> None:
    """v2 修订③:三绿必须尝试 replay,额度标记不阻断(源 §3-14)。"""
    from repoproof.domain.models import VerificationResult
    from repoproof.runner.host_guided import replay_eligible

    ok = VerificationResult(verifier="x", passed=True, detail="")
    bad = VerificationResult(verifier="x", passed=False, detail="")
    assert replay_eligible(ok, ok, ok)
    assert not replay_eligible(ok, bad, ok)
    assert not replay_eligible(None, ok, ok)


def test_obs_cap_clips_but_preserves_first_line(monkeypatch) -> None:
    """修订④:观察限流——首行(submit 标记)永不截断,提示定向读取,
    trace 侧完整产物不受影响(限流只作用于给模型的观察)。"""
    from repoproof.agents.repoproof_env import MARKER, clip_observation
    from repoproof.runner.host_guided import obs_cap

    long_out = MARKER + "\n" + ("x" * 50_000)
    clipped = clip_observation(long_out, 8000)
    assert clipped.splitlines()[0] == MARKER, "首行必须原样保留"
    assert "obs-cap" in clipped and "sed -n" in clipped
    assert len(clipped) < 12_000
    assert clip_observation("short", 8000) == "short"
    assert clip_observation(long_out, None) == long_out, "None=关闭(样例管线默认)"
    # 默认 8000;REPOPROOF_OBS_CAP 可调参/关闭(消融开关)
    monkeypatch.delenv("REPOPROOF_OBS_CAP", raising=False)
    assert obs_cap() == 8000
    monkeypatch.setenv("REPOPROOF_OBS_CAP", "0")
    assert obs_cap() is None
    monkeypatch.setenv("REPOPROOF_OBS_CAP", "20000")
    assert obs_cap() == 20000


def test_prompt_discloses_obs_cap() -> None:
    """限流必须向 agent 如实披露(公平性:规则可见才可优化)。"""
    prompt = build_host_prompt(_t1(), wheel_note="w")
    assert "TRUNCATED" in prompt and "sed -n" in prompt


# ---------------- 修订⑤单调用超时 / 修订⑥oracle stdout 归档 ----------------

def test_call_timeout_default_and_overrides(monkeypatch) -> None:
    from repoproof.runner.host_guided import call_timeout_s
    monkeypatch.delenv("REPOPROOF_CALL_TIMEOUT_S", raising=False)
    assert call_timeout_s() == 300.0
    monkeypatch.setenv("REPOPROOF_CALL_TIMEOUT_S", "45")
    assert call_timeout_s() == 45.0
    monkeypatch.setenv("REPOPROOF_CALL_TIMEOUT_S", "0")
    assert call_timeout_s() is None


def test_append_oracle_log_accumulates(tmp_path) -> None:
    from repoproof.runner.host_guided import append_oracle_log
    append_oracle_log(tmp_path, "first run output", 1)
    append_oracle_log(tmp_path, "replay output", 0)
    text = (tmp_path / "oracle_stdout.log").read_text(encoding="utf-8")
    assert "first run output" in text and "replay output" in text
    assert text.count("===== oracle run @") == 2
    assert "exit=1" in text and "exit=0" in text


def test_task_fixtures_injected_into_session_host(tmp_path, monkeypatch):
    """T3 批 1 实证教训:fixtures 与 public_tests 必须一同进会话。"""
    import shutil
    task = tmp_path / "taskpkg"
    (task / "fixtures").mkdir(parents=True)
    (task / "fixtures" / "fake_agent_llm.py").write_text("X = 1", encoding="utf-8")
    (task / "public_tests").mkdir()
    root = tmp_path / "session_root"
    (root / "host").mkdir(parents=True)
    # 复刻 _assemble 的注入逻辑(同源片段,防回归锚点)
    shutil.copytree(task / "public_tests", root / "host" / "public_tests",
                    ignore=shutil.ignore_patterns("__pycache__"))
    fixtures_src = task / "fixtures"
    if fixtures_src.is_dir():
        shutil.copytree(fixtures_src, root / "host" / "fixtures",
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    assert (root / "host" / "fixtures" / "fake_agent_llm.py").read_text(
        encoding="utf-8") == "X = 1"
    src = (Path(__file__).resolve().parents[1] / "src" / "repoproof" / "runner"
           / "host_guided.py").read_text(encoding="utf-8")
    assert 'root / "host" / "fixtures"' in src, "装配代码丢失 fixtures 注入"
