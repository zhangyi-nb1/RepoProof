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


def test_prompt_discloses_token_allowance_under_total_semantics(tmp_path: Path) -> None:
    """D3 修复钉死(2026-08-11):total 语义下 token 额度同样必须向 agent
    如实披露——此前 total 分支静默省略 in/out 额度,agent 无从预算。"""
    mod = tmp_path / "c.yaml"
    mod.write_text(
        T1_CONTRACT.read_text(encoding="utf-8").replace(
            "semantics: per_round", "semantics: total"),
        encoding="utf-8")
    c, _sha = HostContract.load(mod)
    assert not c.budgets.per_round
    prompt = build_host_prompt(c, wheel_note="w")
    assert "WHOLE RUN (single pool, no per-round reset)" in prompt
    assert "PER ROUND" not in prompt
    assert (f"{c.budgets.max_input_tokens_total}/"
            f"{c.budgets.max_output_tokens_total}") in prompt


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


# ---------------- 增强①postflight 清扫 / 增强③嵌套计量落盘(2026-08-11) ----------------

def _runner_src() -> str:
    return (Path(__file__).resolve().parents[1] / "src" / "repoproof" / "runner"
            / "host_guided.py").read_text(encoding="utf-8")


def test_collect_nested_meter_aggregates_by_tag(tmp_path) -> None:
    """增强③:按 tag 聚合;无数据必须 None(入账 UNKNOWN,绝不写 0)。"""
    import json as _json

    from repoproof.runner.host_guided import collect_nested_meter

    assert collect_nested_meter(tmp_path) is None, "无目录 → None"
    d = tmp_path / "nested_meter"
    d.mkdir()
    assert collect_nested_meter(tmp_path) is None, "空目录 → None"
    (d / "a.json").write_text(_json.dumps(
        {"tag": "public_round1", "requests": 5}), encoding="utf-8")
    (d / "b.json").write_text(_json.dumps(
        {"tag": "public_round1", "requests": 2}), encoding="utf-8")
    (d / "c.json").write_text(_json.dumps(
        {"tag": "oracle_capability", "requests": 7}), encoding="utf-8")
    (d / "junk.json").write_text("not-json", encoding="utf-8")
    out = collect_nested_meter(tmp_path)
    assert out == {"total_requests": 14,
                   "by_phase": {"public_round1": 7, "oracle_capability": 7}}


def test_meter_env_injected_only_by_harness_calls() -> None:
    """增强③接线:harness 自己发起的公开面/oracle/replay 注入 RP_METER_DIR;
    agent 环境(RepoProofEnvironment)绝不注入——自跑套件不计入。"""
    src = _runner_src()
    assert "def _meter_env" in src and "RP_METER_DIR" in src
    assert 'meter_tag=f"public_round{idx}"' in src, "每轮公开面必须带轮次 tag"
    assert 'meter_tag="oracle_replay"' in src, "replay oracle 必须与首验分列"
    assert '"oracle_capability"' in src
    env_src = (Path(__file__).resolve().parents[1] / "src" / "repoproof" / "agents"
               / "repoproof_env.py").read_text(encoding="utf-8")
    assert "RP_METER_DIR" not in env_src, "agent 命令通道不得注入计量环境"


def test_postflight_sweep_wired_after_measurement(monkeypatch) -> None:
    """增强①接线:快照在 run 起点,清扫在 _finish(会话销毁后、测量全毕);
    keep_session 不清扫;记录进 report 与 runs.jsonl 摘要。"""
    src = _runner_src()
    assert "postflight.browser_pids()" in src, "run 起点必须拍浏览器 PID 快照"
    finish_part = src.split("def _finish", 1)[1]
    assert "postflight.sweep(" in finish_part, "清扫必须在 _finish 收尾阶段"
    run_part = src.split("def run(", 1)[1].split("def _clean_replay", 1)[0]
    assert "postflight.sweep(" not in run_part, "run 主流程(测量期)禁止清扫"
    assert "not keep_session and postflight.enabled()" in finish_part
    assert '"postflight_sweep"' in src and '"runtime_browser_agent"' in src


def test_every_task_contract_declares_budget_semantics() -> None:
    """T3 实证(2026-08-11):`semantics` 缺省落回 total 是**静默**的——
    T3 v1 漏写一行,六发的第 2/3 轮各只剩 1 次调用(全 run 单一额度在
    R1 烧尽),修复循环结构性死亡且与预注册文字相悖,四发跑完才被发现。
    默认值本身保留(冻结的历史契约不可改写),但新任务包必须显式声明。"""
    # 已知历史例外:t3_browser_use(v1)冻结时确实漏写,其四发**已在
    # total 语义下测量并入账**——改写它等于篡改已发生的测量条件,故
    # 如实保留为例外,不得再增。
    frozen_exceptions = {"t3_browser_use"}
    tasks = (Path(__file__).resolve().parents[1] / "benchmarks" / "v2" / "tasks")
    missing = [c.parent.name for c in sorted(tasks.glob("*/contract.yaml"))
               if c.parent.name not in frozen_exceptions
               and "semantics:" not in c.read_text(encoding="utf-8")]
    assert not missing, (
        f"任务契约未显式声明预算语义(静默落回 total,修复轮会被架空):{missing}")


def test_postflight_record_unknown_when_no_data() -> None:
    """§9 纪律:清扫未执行/计量无数据 → 显式 UNKNOWN,绝不冒充 0
    (normalise 只兜底必需字段,额外字段的 UNKNOWN 由 runner 显式写)。"""
    src = _runner_src()
    assert src.count('nested_meter or "UNKNOWN"') >= 2, "report 与 record 都要兜底"
    assert '"UNKNOWN" if sweep_report is None' in src
    from repoproof.persistence.bench_records import normalise_record
    rec = normalise_record({"run_id": "x", "runtime_browser_agent": "UNKNOWN"})
    assert rec["runtime_browser_agent"] == "UNKNOWN", "额外字段必须如实入行"
