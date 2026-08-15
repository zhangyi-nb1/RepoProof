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
        HostGuidedRunner(c, tmp_path)   # 项目根用 tmp:不得污染真实证据树


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
        HostGuidedRunner(c, tmp_path)   # 项目根用 tmp:不得污染真实证据树



def test_failed_construction_leaves_no_run_dir(tmp_path: Path) -> None:
    """LESSONS #35 · F3:先核验后建店。走**静态资源核验**失败路径——
    受保护目录那道护栏原本就排在建店之前,拿它当反例的钉死在未修复的
    树上也绿(红绿工具首咬,已实证)。"""
    host_copy = tmp_path / "host_copy"
    host_copy.mkdir()
    contract_dir = tmp_path / "task"
    (contract_dir / "oracle").mkdir(parents=True)
    (contract_dir / "public_tests").mkdir()
    c = contract_dir / "contract.yaml"
    c.write_text(T1_CONTRACT.read_text(encoding="utf-8").replace(
        "copy_path: ~/RepoProofBench/offerclaw-t1-fastapi-mcp",
        f"copy_path: {host_copy}"), encoding="utf-8")
    with pytest.raises(HostRunError, match="上游固定快照缺失"):
        HostGuidedRunner(c, tmp_path)
    assert not (tmp_path / "runs").exists(), "核验失败后仍建了证据目录"

# ---------------------------------------------------------------- 指纹对账集
def test_integrity_scope_excludes_repoproof_itself(tmp_path: Path, monkeypatch) -> None:
    """语义:传入的 RepoProof 根不进对账集(run 合法写自己的 runs/),
    其余保护目录一个不少。

    2026-08-12 改写为位置无关:旧版用 `__file__` 找"自己",在 git worktree
    副本里(变异闸门的隔离环境)"自己"不再是保护目录,断言崩——钉死不得
    假设自己住在真仓库里。语义本身用注入的保护目录验证,真实配置的覆盖
    由 test_default_protected_covers_real_dev_dirs 把守。
    """
    import os

    a = tmp_path / "fake_repoproof"
    b = tmp_path / "fake_offerclaw"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("REPOPROOF_PROTECTED_DIRS", f"{a}:{b}")
    scope = integrity_scope(a)
    norm_a = os.path.realpath(str(a)).lower().rstrip("/")
    norm_b = os.path.realpath(str(b)).lower().rstrip("/")
    assert norm_a not in scope, "自身必须被排除(对自己拍指纹必然自误报)"
    assert norm_b in scope, "其余保护目录一个不能少"
    # 传入非保护路径时,保护集完整保留(worktree 场景)
    assert norm_b in integrity_scope(tmp_path / "elsewhere")


# ---------------------------------------------------------------- 冒烟脚本
def test_fake_scripts_shape() -> None:
    """冒烟脚本形状 —— **考行为不考实现**。

    2026-08-14 改:原断言写死 `sdk_mcp.py` / `mcp<2.0`,即 T1 的实现细节。
    那正是缺陷本身 —— `_fake_script` 当年也写死了同一批常量,于是 T2/T3
    的 positive 冒烟直接 FileNotFoundError,两个任务的 F0 失去正控意义。
    现在断言的是**每个任务都能生成、且落地的是它自己的正控**。"""
    runner = _RunnerStub()
    noop = _fake_script("noop", runner)
    assert "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in noop[0]["actions"][0]["command"]
    pos = _fake_script("positive", runner)
    joined = "\n".join(a["command"] for step in pos for a in step["actions"])
    assert "sdk_mcp.py" in joined and "mount_sdk_mcp" in joined, (
        "T1 的正控冒烟必须落地 T1 自己的控制组与挂载符号")
    assert joined.strip().endswith("COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT")
    with pytest.raises(ValueError):
        _fake_script("nonsense", runner)


def test_fake_positive_works_for_every_task_not_just_t1() -> None:
    """缺陷修复的正面:每个任务各落各的控制组,**不再有人被写死的常量卡住**。

    反例(2026-08-14 之前的实现):写死 T1 的 `sdk_mcp.py`,T2/T3 直接
    FileNotFoundError —— 它们的 F0 因此只能降级用 `--fake noop`,而 noop
    什么都不验。

    2026-08-14 晚修订:T3 现在会**拒跑**,但那是完全不同的一件事 —— 拒跑
    来自任务包里显式写下的 `#!BLOCKED:`(真上游在钉版环境不可导入),而
    不是 harness 写死了别的任务的文件名。两者必须区分开钉:
      - 允许的失败 = ValueError,且带得出任务包给的诊断;
      - 不允许的失败 = FileNotFoundError / KeyError 这类"实现漏了这个任务"。
    """
    repo = Path(__file__).resolve().parents[1]
    want = {"t1_fastapi_mcp": "mount_sdk_mcp",
            "t2_open_deep_research_v5": "mount_research_api",
            "t3_browser_use_v6": "mount_apply_assist"}
    for task, mount in want.items():
        task_dir = repo / "benchmarks" / "v2" / "tasks" / task
        if not (task_dir / "contract.yaml").exists():
            continue
        try:
            steps = _fake_script("positive", _stub_for(task_dir))
        except ValueError as e:
            assert "不可满足" in str(e), (
                f"{task} 拒跑了,但理由不是任务包声明的阻断:{e}")
            continue
        except Exception as e:  # noqa: BLE001 —— 正是要抓"实现漏了这个任务"
            raise AssertionError(
                f"{task} 以 {type(e).__name__} 崩了 —— 这是写死常量的病征,"
                f"不是任务包声明的阻断:{e}") from e
        joined = "\n".join(a["command"] for step in steps for a in step["actions"])
        assert mount in joined, f"{task} 的冒烟没落地它自己的挂载符号 {mount}"


def test_missing_controls_fails_loudly_not_silently(tmp_path) -> None:
    """控制组缺失必须显式失败,**不得静默退回 noop**。

    静默退回会让冒烟"通过"而其实什么都没验 —— 与 batch_criteria 的
    "空跑不算通过"、validate_controls 的 V3 同源。"""
    import shutil

    repo = Path(__file__).resolve().parents[1]
    src = repo / "benchmarks" / "v2" / "tasks" / "t2_open_deep_research_v5"
    if not src.exists():
        return
    dst = tmp_path / "task"
    shutil.copytree(src, dst)
    shutil.rmtree(dst / "controls" / "positive")

    with pytest.raises(ValueError, match="控制组"):
        _fake_script("positive", _stub_for(dst))


# ------------------------------------------------ 正控环境清单(smoke_setup)
# 2026-08-14。为什么要有这层:`--fake positive` 是**假阳侧正控** —— 它回答
# "这套 oracle 在钉版环境里到底能不能被满足"。要回答得准,冒烟就得走真实
# 发次的完整路径(装依赖 → 落控制组 → 接线 → 干净重放)。
#
# 而"依赖怎么装"是**每任务的偶然事实**,不存在通用装法(逐条实测):
#   - `pip install -e ../upstream` 三任务全灭 —— wheelhouse 无 `hatchling`;
#   - `pip install <distribution>` 只有 T1 成 —— 另两个上游各 0 个轮子。
# 写死在 harness 代码里就是原缺陷的翻版(它写死了 T1 的 `sdk_mcp.py` /
# `mcp<2.0`,于是 T2/T3 的 F0 直接 FileNotFoundError)。所以钉在任务包里。
#
# 冻结判据(先写判据与反例;措辞此后不改):
#
# - N1 **缺清单显式失败**。反例:静默跳过依赖步骤 → 冒烟"跑完了"却因
#   ModuleNotFound 全红,读的人会以为是实现不对,其实是环境没备好。
# - N2 **`#!BLOCKED:` 带诊断拒跑**,理由原样带出。反例:让它照常跑出一发
#   FAIL → 台账里留下一条与"模型失败"同型的记录,而它其实是**环境不可
#   满足**,两者含义相反(前者说模型不行,后者说这道题没有正确答案)。
# - N3 **多行块整块下发**。反例:按行拆成多条命令 → heredoc 被腰斩,垫片
#   文件写出半截,而每条命令各自 rc=0,失败要到 oracle 才现形。
# - N4 **注释不进命令**。反例:把 `# ...` 也当命令发下去。
# - N5 **落地控制组的全部 .py**,与 `build_control_tree.build()` 一致。
#   反例:只落挂载模块 → 带辅助模块的正控在冒烟里缺件,而在控制树验证里
#   是齐的:同一个正控,两条路径看到的东西不一样,冒烟不再是控制树的现场
#   复现。


def _stub_for(task_dir: Path):
    """只带 task_dir 的 stub —— `_fake_script` 用到的就只有它。

    不构造真 `HostGuidedRunner`:那会核验 `upstream-cache/`,而该目录
    gitignore,变异闸门的隔离 worktree 里根本没有。钉死要考的是脚本
    生成逻辑,不是上游快照在不在。"""
    return type("_S", (), {"task_dir": task_dir})()


def _pos_cmds(task: str) -> list[str]:
    repo = Path(__file__).resolve().parents[1]
    runner = _stub_for(repo / "benchmarks" / "v2" / "tasks" / task)
    return [a["command"] for step in _fake_script("positive", runner)
            for a in step["actions"]]


def test_missing_setup_manifest_fails_loudly(tmp_path) -> None:
    """N1:缺环境清单显式失败,不静默跳过依赖步骤。"""
    import shutil

    repo = Path(__file__).resolve().parents[1]
    src = repo / "benchmarks" / "v2" / "tasks" / "t1_fastapi_mcp"
    dst = tmp_path / "task"
    shutil.copytree(src, dst)
    (dst / "controls" / "positive" / "smoke_setup.txt").unlink()

    with pytest.raises(ValueError, match="环境清单"):
        _fake_script("positive", _stub_for(dst))


def test_blocked_directive_refuses_with_the_reason(tmp_path) -> None:
    """N2:`#!BLOCKED:` 拒跑,且把理由原样带出来。"""
    import shutil

    repo = Path(__file__).resolve().parents[1]
    src = repo / "benchmarks" / "v2" / "tasks" / "t1_fastapi_mcp"
    dst = tmp_path / "task"
    shutil.copytree(src, dst)
    (dst / "controls" / "positive" / "smoke_setup.txt").write_text(
        "# 说明\n#!BLOCKED: 上游在钉版环境不可导入,缺 bubus\n"
        ".venv/bin/pip install -q foo\n", encoding="utf-8")

    with pytest.raises(ValueError, match="缺 bubus"):
        _fake_script("positive", _stub_for(dst))


def test_multiline_block_is_delivered_whole(tmp_path) -> None:
    """N3:heredoc 整块下发,不被按行拆碎。

    反例(按行拆):每条命令各自 rc=0,垫片文件却只写出半截,
    失败要到 oracle 才现形。"""
    import shutil

    repo = Path(__file__).resolve().parents[1]
    src = repo / "benchmarks" / "v2" / "tasks" / "t1_fastapi_mcp"
    dst = tmp_path / "task"
    shutil.copytree(src, dst)
    (dst / "controls" / "positive" / "smoke_setup.txt").write_text(
        "# 注释不进命令\n"
        "cat > shim.py <<'EOF'\nline1\n\nline3\nEOF\n"
        "---\n"
        "echo second\n", encoding="utf-8")

    cmds = [a["command"]
            for step in _fake_script("positive", _stub_for(dst))
            for a in step["actions"]]
    whole = [c for c in cmds if c.startswith("cat > shim.py")]
    assert len(whole) == 1, f"heredoc 被拆碎了:{cmds[:3]}"
    assert whole[0] == "cat > shim.py <<'EOF'\nline1\n\nline3\nEOF", (
        "块内换行(含空行)必须原样保留 —— 空行分块会腰斩 heredoc")
    assert "echo second" in cmds
    assert not any(c.lstrip().startswith("#") for c in cmds), "N4:注释不得成为命令"


def test_smoke_lands_every_control_py_not_just_the_mount_module(tmp_path) -> None:
    """N5:落地控制组全部 .py —— 与 build_control_tree.build() 同口径。"""
    import shutil

    repo = Path(__file__).resolve().parents[1]
    src = repo / "benchmarks" / "v2" / "tasks" / "t1_fastapi_mcp"
    dst = tmp_path / "task"
    shutil.copytree(src, dst)
    (dst / "controls" / "positive" / "helper_side.py").write_text(
        "SIDE = 1\n", encoding="utf-8")

    cmds = [a["command"]
            for step in _fake_script("positive", _stub_for(dst))
            for a in step["actions"]]
    joined = "\n".join(cmds)
    assert "cat > helper_side.py" in joined, (
        "辅助模块没被落地 —— 冒烟看到的正控与控制树看到的不是同一个")
    assert "cat > sdk_mcp.py" in joined


def test_real_task_manifests_are_present_and_say_what_they_should() -> None:
    """接线检查:三个真任务的清单现状(防清单被误删或被悄悄改成 noop)。

    T1/T2 应当能生成可跑脚本;T3 应当拒跑 —— 真 `browser_use.Agent` 在钉版
    离线环境不可导入(导入闭包缺 bubus/cdp_use/uuid_extensions/pyotp)。
    这条一旦变绿,说明要么 wheelhouse 重建了,要么有人把阻断悄悄删了 ——
    两种情况都必须有人来看一眼。"""
    for task in ("t1_fastapi_mcp", "t2_open_deep_research_v5"):
        cmds = _pos_cmds(task)
        assert any("pip install" in c for c in cmds), f"{task} 清单里没有装依赖的步骤"
        assert cmds[-1].strip().endswith("COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT")

    with pytest.raises(ValueError, match="不可满足"):
        _pos_cmds("t3_browser_use_v6")


class _RunnerStub:
    task_dir = T1_CONTRACT.parent


def test_enforcement_input_cap_is_the_contract_value_not_an_inset() -> None:
    """LESSONS #39:执法线**不再内移**,不越线由调用前投影保证。

    2026-08-09 的用户决策内移 50k,意图是"别让越线取决于边界运气";
    order-63 证明拍常数做不到这件事(内移 50,000,单次最大调用 51,067)。
    投影更严格地满足了同一个意图,于是不再收这 50k 的税——agent 拿到的
    恰是契约承诺的额度。这条钉死看住的是"别有人再偷偷把线往里挪"。"""
    from repoproof.runner.host_guided import enforcement_input_cap

    c = _t1()
    assert c.budgets.per_round
    assert enforcement_input_cap(c.budgets) == 500_000
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


# ---------------- 依赖可复现性归因(2026-08-12,LESSONS #31) ----------------
#
# 实录:两发 T3(030156/054108)公开面与 oracle 全绿,只挂在干净重放——
# 适配把 `browser-use==0.13.7` / `openai==2.16.0` 写进 requirements.txt,而
# 冻结轮仓里没有这两个分发。台账把它记成
# `replay infrastructure failure: 宿主依赖安装失败(wheelhouse 不全?)`,
# failure_types 分别是 UNKNOWN 和 SCHEMA_ERROR/TEST_FAILURE——**都没说中死因,
# 而且方向反了**:harness 替模型认领了错。

# run t3-...-054108 的 pip 输出原文(逐字,含两种措辞)
_REAL_PIP_TAIL = (
    "ERROR: Could not find a version that satisfies the requirement "
    "browser-use==0.13.7 (from versions: none)\n"
    "ERROR: No matching distribution found for browser-use==0.13.7\n"
)


def test_unresolved_dist_regex_matches_real_pip_output() -> None:
    from repoproof.runner.host_guided import added_unresolvable_dists

    assert added_unresolvable_dists(_REAL_PIP_TAIL, frozenset()) == ["browser-use"]
    # 同一段报错,若该分发本来就在基线里 → 轮仓不全,不得记到 agent 头上
    assert added_unresolvable_dists(_REAL_PIP_TAIL, frozenset({"browser-use"})) == []
    # 无解析失败的普通报错(编译挂了之类)→ 不是这一类
    assert added_unresolvable_dists("error: command 'clang' failed", frozenset()) == []


def test_dist_names_are_pep503_normalised() -> None:
    """`Browser_Use` 与 `browser-use` 是同一个分发——否则基线比对形同虚设。"""
    from repoproof.runner.host_guided import added_unresolvable_dists, parse_requirement_dists

    base = parse_requirement_dists(
        "# comment\nFastAPI>=0.110\nRuamel.YAML==0.18\n-e .\n-r dev.txt\n\nBrowser_Use==0.13.7\n")
    assert base == frozenset({"fastapi", "ruamel-yaml", "browser-use"})
    assert added_unresolvable_dists(_REAL_PIP_TAIL, base) == []


def test_baseline_read_from_pristine_host_copy_not_session(tmp_path: Path) -> None:
    """基准必须取**未适配**的宿主副本;取会话里那份 = 让被测者自定义基准。"""
    from repoproof.runner.host_guided import HostGuidedRunner

    class _Stub:
        host_copy = tmp_path
        _baseline_dists_cache = None
        _baseline_dists = HostGuidedRunner._baseline_dists

    (tmp_path / "requirements.txt").write_text("fastapi>=0.110\n", encoding="utf-8")
    assert _Stub()._baseline_dists() == frozenset({"fastapi"})
    src = _runner_src()
    assert 'req = self.host_copy / "requirements.txt"' in src, "基准不得取会话内副本"


def test_dependency_failure_attributed_to_agent_not_harness() -> None:
    """接线钉死:两条分支必须分开归因,且判据读 pip **全文**不读截断尾巴。"""
    src = _runner_src()
    assert "added_problem_dists(full, self._baseline_dists())" in src  # #38 改名(两种死法合一);语义不变:重放侧按基线归因
    assert "raise DependencyNotReproducible(" in src
    assert '"attribution": "agent"' in src and '"attribution": "harness"' in src
    # DependencyNotReproducible 的 except 必须排在**同一 try 的**兜底之前,
    # 否则永远轮不到它(Python 按书写顺序匹配)。
    specific = src.index("except DependencyNotReproducible")
    fallback = src.index("except Exception", specific)
    assert src[specific:fallback].count("try:") == 0, "两个 except 必须属于同一个 try"
    assert '"attribution": "agent"' in src[specific:fallback], "专用分支必须归因 agent"


def test_verifier_attribution_reaches_failure_types() -> None:
    """归因只写进 report 不写进 failure_types = 台账里仍然查不到死因。"""
    from repoproof.domain.models import VerificationResult
    from repoproof.runner.host_guided import DEPENDENCY_NOT_REPRODUCIBLE

    src = _runner_src()
    finish = src.split("def _finish", 1)[1]
    assert "vr.extra.get(\"failure_type\")" in finish
    assert "for vr in (capability_vr, regression_vr, policy_vr, replay_vr)" in finish
    # 复刻并集语义(同源片段,防回归锚点)
    rep = VerificationResult(
        verifier="ReplayVerifier", passed=False, detail="x",
        extra={"failure_type": DEPENDENCY_NOT_REPRODUCIBLE, "attribution": "agent"})
    plain = VerificationResult(verifier="PolicyVerifier", passed=True, detail="")
    types = sorted({"TEST_FAILURE"} | {v.extra["failure_type"] for v in (rep, plain)
                                       if v.extra.get("failure_type")})
    assert types == [DEPENDENCY_NOT_REPRODUCIBLE, "TEST_FAILURE"]


def test_dependency_error_is_still_a_hostrunerror() -> None:
    """新异常必须是 HostRunError 子类——否则上游各处兜底捕获会漏。"""
    from repoproof.runner.host_guided import DependencyNotReproducible

    exc = DependencyNotReproducible(["browser-use"], "detail")
    assert isinstance(exc, HostRunError) and exc.dists == ["browser-use"]


def test_postflight_record_unknown_when_no_data() -> None:
    """§9 纪律:清扫未执行/计量无数据 → 显式 UNKNOWN,绝不冒充 0
    (normalise 只兜底必需字段,额外字段的 UNKNOWN 由 runner 显式写)。"""
    src = _runner_src()
    assert src.count('nested_meter or "UNKNOWN"') >= 2, "report 与 record 都要兜底"
    assert '"UNKNOWN" if sweep_report is None' in src
    from repoproof.persistence.bench_records import normalise_record
    rec = normalise_record({"run_id": "x", "runtime_browser_agent": "UNKNOWN"})
    assert rec["runtime_browser_agent"] == "UNKNOWN", "额外字段必须如实入行"


_REPO = Path(__file__).resolve().parents[1]


# ==================================================== C 轨:宿主耦合拆开(2026-08-15)
# 勘察查出五处把第一宿主(OfferClaw)的布局当常量。第二宿主不是"跑起来不准",
# 是**跑不起来**:没有 requirements.txt / rag_ingest.py 直接 HostRunError,
# 三个健康检查脚本不存在 → exec 127 → 每发零预算 BLOCKED 且无旁路。
#
# 泛化的意义是让第二宿主能声明自己的形状,**不是趁机改第一宿主的判据**——
# 所以头一条钉死就是"现有契约的行为一个字节都不许变"。

def _contract(name: str):
    import sys

    sys.path.insert(0, str(_REPO / "src"))
    from repoproof.runner.host_guided import HostContract

    return HostContract.load(
        _REPO / "benchmarks" / "v2" / "tasks" / name / "contract.yaml")[0]


def test_k13_the_first_hosts_shape_is_unchanged_by_the_generalisation():
    """K13:泛化之后,**现有契约解析出的宿主形状与写死时逐字节相同**。

    这是整次改动唯一真正危险的地方:把常量搬进契约,顺手改了默认值,于是
    T1–T3 的基线判据悄悄变了,而所有数字看起来照常。
    """
    from repoproof.runner.host_guided import _OFFERCLAW_HEALTH, _OFFERCLAW_SETUP

    for name in ("t1_fastapi_mcp", "t3_sidecar_v1", "t2_open_deep_research_v5"):
        h = _contract(name).host
        assert h.setup_commands == _OFFERCLAW_SETUP, f"{name} 的建环境步骤变了"
        assert [c.command for c in h.health_checks] == [
            x["command"] for x in _OFFERCLAW_HEALTH], f"{name} 的健康检查变了"
        assert h.host_root_env == "OFFERCLAW_HOST_ROOT"

    # 那三条的**判据**也不许变:verify_pipeline 严判、verify_docs 认那句串、
    # doctor 不作门禁。它们各自是踩出来的,不是设计出来的。
    by = {c.command[-1]: c for c in _contract("t1_fastapi_mcp").host.health_checks}
    assert by["verify_pipeline.py"].gating and not by["verify_pipeline.py"].pass_if_stdout_contains
    assert by["verify_docs.py"].pass_if_stdout_contains == "0 处未围栏"
    assert by["doctor.py"].gating is False, "doctor 变成门禁了 —— 它有已知预期差异"


def test_k14_public_command_comes_from_the_contract_not_a_constant():
    """K14:公开面命令**读契约**,且现有契约与原写死值逐字相同。

    改之前 `_run_public` 写死 `pytest public_tests/`,而
    `acceptance.public_test_command` 一直躺在契约里没人读 ——
    **契约说的和实际跑的不是一回事**,这本身就是判据不可信的一种。
    """
    import sys

    sys.path.insert(0, str(_REPO / "src"))
    from repoproof.runner.host_guided import HostGuidedRunner, HostRunError

    hardcoded = ["-m", "pytest", "public_tests/", "-q", "-p", "no:cacheprovider"]
    for name in ("t1_fastapi_mcp", "t3_sidecar_v1", "t2_open_deep_research_v5"):
        r = HostGuidedRunner.__new__(HostGuidedRunner)
        r.contract = _contract(name)
        assert r._public_argv() == hardcoded, f"{name} 的公开面与原写死值不同了"

    # 声明成别的,就必须跑别的 —— 否则等于没读
    r = HostGuidedRunner.__new__(HostGuidedRunner)
    r.contract = _contract("t1_fastapi_mcp").model_copy(deep=True)
    r.contract.acceptance.public_test_command = ["python", "-m", "pytest", "t/", "-q"]
    assert r._public_argv() == ["-m", "pytest", "t/", "-q"]
    r.contract.acceptance.public_test_command = []
    with pytest.raises(HostRunError, match="不猜"):
        r._public_argv()


def test_k15_regression_no_longer_silently_falls_back():
    """K15:回归命令不再**静默**退回 `pytest tests/`。

    老写法是 `if cmd[0] == "python" else 退回`。于是契约声明了别的命令
    (第二宿主必然如此 —— 它没有 `tests/` 这个目录名的保证)也照跑
    OfferClaw 那条,**而报告里看不出任何差别**。静默退回比报错难查得多。
    """
    src = _runner_src()
    assert '[s.venv_py, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"]' not in src, (
        "静默退回的那条还在")
    assert 'raise HostRunError("契约没声明 host.regression_command' in src


def test_k16_a_second_hosts_shape_is_actually_honoured():
    """K16(**正控**):第二宿主声明自己的形状,harness 必须照做。

    上面三条都是"别把第一宿主改坏"的负控。可满足性只能靠正控验
    (LESSONS #44)—— 不验的话,泛化可能只是"多了几个没人读的字段"。
    """
    import sys

    sys.path.insert(0, str(_REPO / "src"))
    from repoproof.runner.host_guided import HostGuidedRunner, HostInfo

    h = HostInfo(repo="marshmallow-code/flask-smorest", commit="3451351",
                 copy_path="~/RepoProofBench/host2-flask-smorest/repo",
                 regression_command=["python", "-m", "pytest", "-q"],
                 setup_commands=[["python3", "-m", "venv", ".venv"],
                                 [".venv/bin/pip", "install", "--no-index", "-e", "."]],
                 health_checks=[{"command": ["python", "-c", "import flask_smorest"]}],
                 host_root_env="FLASK_SMOREST_HOST_ROOT")
    assert h.setup_commands[1][1] == "install" and "rag_ingest.py" not in str(h.setup_commands)
    assert [c.command[-1] for c in h.health_checks] == ["import flask_smorest"]
    assert h.host_root_env == "FLASK_SMOREST_HOST_ROOT"

    # oracle 环境里三个名字都要在(多注无害,少注会让 oracle 找不到自己的根)
    src = _runner_src()
    assert "self.contract.host.host_root_env: str(s.root" in src
    assert '"REPOPROOF_HOST_ROOT": str(s.root' in src
    assert '"OFFERCLAW_HOST_ROOT": str(s.root' in src, "第一宿主的名字被删了 —— 它的 oracle 会瞎"

    # 建环境:没有 pip 那步也要能跑完(第二宿主可能用 uv / 预建 venv)
    r = HostGuidedRunner.__new__(HostGuidedRunner)
    assert callable(r._build_env_in_session)


def test_k17_setup_steps_run_in_the_declared_order():
    """K17:建环境的步骤必须**按声明顺序**跑,装依赖那步不许被跳到后面。

    实录(2026-08-15,泛化当天):第一版写成
    `for i, cmd in enumerate(cmds): if i == pip_idx: continue`,
    于是 pip **之后**的步骤被提前执行 —— OfferClaw 的 `rag_ingest.py` 在
    chromadb 装上之前跑,当场 ModuleNotFoundError → 零预算 BLOCKED。

    单测抓不到它(它们不建环境),是零模型端到端冒烟一把抓住的。这条把
    顺序钉在源码上,免得下次重构又把它拆散。
    """
    src = _runner_src()
    assert "head = cmds[:pip_idx] if pip_idx is not None else cmds" in src, (
        "装依赖之前那几步的切片没了 —— 顺序可能又被打乱")
    assert "for i, cmd in enumerate(cmds[pip_idx + 1:], start=pip_idx + 2):" in src, (
        "装依赖之后那几步没跑")
    # 顺序断言:head 循环必须出现在 pip 执行之前,tail 循环必须在它之后
    i_head = src.index("head = cmds[:pip_idx]")
    i_pip = src.index("r2 = s.backend.exec(s.id, cmds[pip_idx]")
    i_tail = src.index("for i, cmd in enumerate(cmds[pip_idx + 1:]")
    assert i_head < i_pip < i_tail, "三段的先后顺序被打乱了"


def test_k18_health_check_gating_flag_is_honoured():
    """K18:`gating=False` 的健康检查**只记录不作门禁**。

    OfferClaw 的 `doctor.py` 就是这种 —— Manifest 里写明的已知预期差异
    (chunks 口径 / 合成密钥 WARN)。不认这个旗标 = 每发零预算 BLOCKED,
    而 BLOCKED 的含义是"不是被测方的错",于是所有发次都作废。
    """
    src = _runner_src()
    assert "if hc.gating:" in src, "gating 旗标没人读了"
    assert "ok = ok and passed" in src
    # 判据不许再回到硬编码中文串
    assert '"0 处未围栏" in rd_out' not in src, "那句中文串又写死回代码里了"
    assert "hc.pass_if_stdout_contains in out" in src

    by = {c.command[-1]: c for c in _contract("t1_fastapi_mcp").host.health_checks}
    assert by["doctor.py"].gating is False
    assert by["verify_pipeline.py"].gating is True
