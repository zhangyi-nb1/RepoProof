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
