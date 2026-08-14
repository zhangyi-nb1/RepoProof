"""Runtime Profile(A1)的钉死 —— 第 7 步。

Sidecar 不是"换个实现细节",是**换了一道题**:

    rt-inprocess-v1   上游在 agent 的 venv 里,"有没有用上游"只能从足迹
                      推断 —— 而足迹上的每一样东西 SUT 都能自己供(#43 坑五)。
    rt-sidecar-*      上游由 harness 持有,agent 只能经 RPC 请它执行 ——
                      "有没有用上游"变成执行拓扑约束。

冻结判据(先写判据与反例;措辞此后不改):

- P1 **缺省是老行为**。没声明 profile 的契约一律 in-process。反例:新增
  能力把既有任务悄悄换成另一道题 → 全部历史发次的题面变了却没人知道。
- P2 **sidecar 必须进执行代际**。反例:两种 profile 的发次在分析时被合池
  —— 那等于把开卷和闭卷的成绩加起来平均。
- P3 **sidecar 拓扑的三条自洽**:必须有 UpstreamSpec、必须有 required_symbols、
  要求的符号必须在能力面里实现。反例(第三条):要求一件上游做不到的事 →
  判据成墙,谁都过不了,而墙拦不住洗白只拦得住诚实实现。
- P4 **profile id 是对外承诺**。同 id 不同内容必须拒绝。反例:就地改语义 →
  台账里同一个 id 底下混着两种行为,回执的 `profile_id` 从此不可信。
- P5 **agent 只拿到端点与令牌**。反例:顺手把台账路径或密钥也注进去 →
  nc8 那种伪造立刻成立,整套拓扑约束白做。
- P6 **符号白名单在执行前拦**。反例:先执行再让 U2 判 → sidecar 替被测方
  执行了契约之外的东西;U2 判的是"已发生的执行对不对",拒绝的是"不该发生
  的执行",两者都要有。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repoproof.agents.profiles import exec_generation
from repoproof.execution.runtime_profiles import (
    IN_PROCESS_V1,
    RuntimeProfile,
    generation_suffix,
    known_profiles,
    profile,
    profile_of_contract,
    register_profile,
)
from repoproof.execution.upstream_sidecar import UpstreamSpec, start_sidecar
from repoproof.receipts.ledger import new_key, new_nonce

REPO = Path(__file__).resolve().parents[1]


def _spec(**over) -> UpstreamSpec:
    d = {"markdown_it.MarkdownIt.render": lambda p: "<p>x</p>\n"}
    return UpstreamSpec(over.get("dist", "markdown-it-py"),
                        over.get("mod", "markdown_it"), over.get("dispatch", d))


# ------------------------------------------------------------------ P1
def test_p1_default_profile_is_in_process():
    """P1:没声明就是老行为。新增能力不得把老题换成另一道题。"""
    class _C:
        pass

    assert profile_of_contract(_C()).id == "rt-inprocess-v1"
    assert IN_PROCESS_V1.topology == "in_process"
    assert IN_PROCESS_V1.lifecycle == "default"


def test_p1b_real_task_contracts_are_all_in_process():
    """P1 的现场版:盘上每个任务包都仍是 in-process。

    这条会在第一个 sidecar 任务落地时变红 —— 那时**必须有人来看一眼**,
    确认那道题确实是有意换的,而不是谁顺手改了个默认值。"""
    import yaml

    tasks = sorted((REPO / "benchmarks" / "v2" / "tasks").glob("*/contract.yaml"))
    assert tasks, "任务包一个都没有?"
    for f in tasks:
        got = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("runtime_profile")
        assert got in (None, "", "rt-inprocess-v1"), (
            f"{f.parent.name} 声明了 {got!r} —— 题面变了,别忘了它与既有发次不可互比")


# ------------------------------------------------------------------ P2
def test_p2_sidecar_shows_up_in_the_execution_generation():
    """P2:sidecar 必须进代际标签,否则两种 profile 会被悄悄合池。"""
    base = exec_generation(context={}, tool={})
    assert base == "E0"
    assert exec_generation(context={}, tool={}, runtime_profile="rt-inprocess-v1") == "E0"

    with_sc = exec_generation(context={}, tool={}, runtime_profile="rt-sidecar-x-v1")
    assert with_sc != base and "rt-sidecar-x-v1" in with_sc

    # 与 S 步叠加时两者都要在
    both = exec_generation(context={"prune_policy": "p"}, tool={},
                           runtime_profile="rt-sidecar-x-v1")
    assert "S2" in both and "rt-sidecar-x-v1" in both


def test_p2b_generation_suffix_is_empty_only_for_in_process():
    assert generation_suffix(IN_PROCESS_V1) == ""
    p = RuntimeProfile(id="rt-sidecar-t-v1", topology="sidecar", lifecycle="experimental",
                       summary="", upstream=_spec(),
                       required_symbols=frozenset({"markdown_it.MarkdownIt.render"}),
                       default_symbol="markdown_it.MarkdownIt.render")
    assert generation_suffix(p) == "+rt-sidecar-t-v1"


# ------------------------------------------------------------------ P3
def test_p3_sidecar_without_upstream_is_rejected():
    with pytest.raises(ValueError, match="UpstreamSpec"):
        RuntimeProfile(id="bad1", topology="sidecar", lifecycle="experimental",
                       summary="", required_symbols=frozenset({"x"}))


def test_p3b_sidecar_without_required_symbols_is_rejected():
    with pytest.raises(ValueError, match="required_symbols"):
        RuntimeProfile(id="bad2", topology="sidecar", lifecycle="experimental",
                       summary="", upstream=_spec())


def test_p3c_requiring_an_unimplemented_symbol_is_rejected():
    """P3 的要害:要求一件上游做不到的事 = 判据成墙。

    墙拦不住洗白,只拦得住诚实实现 —— 这正是 T3v6 的教训(#44)。"""
    with pytest.raises(ValueError, match="没有实现"):
        RuntimeProfile(id="bad3", topology="sidecar", lifecycle="experimental",
                       summary="", upstream=_spec(),
                       required_symbols=frozenset({"markdown_it.Nope.run"}),
                       default_symbol="markdown_it.Nope.run")


def test_p3d_in_process_must_not_carry_an_upstream():
    with pytest.raises(ValueError, match="in_process"):
        RuntimeProfile(id="bad4", topology="in_process", lifecycle="experimental",
                       summary="", upstream=_spec())


# ------------------------------------------------------------------ P4
def test_p4_profile_id_is_a_promise():
    """P4:同 id 不同内容必须拒绝 —— 否则回执的 profile_id 从此不可信。"""
    a = RuntimeProfile(id="rt-sidecar-p4", topology="sidecar", lifecycle="experimental",
                       summary="one", upstream=_spec(),
                       required_symbols=frozenset({"markdown_it.MarkdownIt.render"}),
                       default_symbol="markdown_it.MarkdownIt.render")
    register_profile(a)
    register_profile(a)                      # 同内容重复登记无害
    b = RuntimeProfile(id="rt-sidecar-p4", topology="sidecar", lifecycle="qualified",
                       summary="改了语义", upstream=_spec(),
                       required_symbols=frozenset({"markdown_it.MarkdownIt.render"}),
                       default_symbol="markdown_it.MarkdownIt.render")
    with pytest.raises(ValueError, match="已被占用"):
        register_profile(b)


def test_p4b_unknown_profile_is_refused_not_guessed():
    with pytest.raises(ValueError, match="未登记"):
        profile("rt-does-not-exist")
    assert "rt-inprocess-v1" in known_profiles()


# ------------------------------------------------------------------ P5 / P6
def _live_sidecar(tmp_path, dispatch=None):
    spec = _spec(dispatch=dispatch) if dispatch else _spec()
    return start_sidecar(
        spec=spec, ledger_path=tmp_path / "upstream_receipts.jsonl",
        key=new_key(), run_id="run-p5", run_nonce=new_nonce(), token="tok",
        profile_id="rt-sidecar-test-v1",
        default_symbol="markdown_it.MarkdownIt.render")


def test_p5_agent_env_carries_only_endpoint_and_token(tmp_path):
    """P5:交给 agent 的只有端点与令牌。

    反例:顺手把台账路径或密钥也注进去 → nc8 那种伪造立刻成立。"""
    h = _live_sidecar(tmp_path)
    try:
        env = h.agent_env()
        assert set(env) == {"REPOPROOF_SIDECAR_URL", "REPOPROOF_SIDECAR_TOKEN"}
        blob = json.dumps(env)
        assert str(h.ledger_path) not in blob, "台账路径泄漏给 agent 了"
        assert h.token in blob and "receipt" not in blob.lower()
    finally:
        h.shutdown()


def test_p6_unknown_symbol_is_refused_before_execution(tmp_path):
    """P6:白名单在**执行前**拦。

    反例:先执行再让 U2 判 → sidecar 替被测方执行了契约之外的东西。U2 判
    的是"已发生的执行对不对",拒绝的是"不该发生的执行",两者都要有。"""
    import urllib.error
    import urllib.request

    called = []

    def _spy(payload):
        called.append(payload)
        return "<p>x</p>\n"

    h = _live_sidecar(tmp_path, dispatch={"markdown_it.MarkdownIt.render": _spy})
    try:
        env = h.agent_env()
        req = urllib.request.Request(
            env["REPOPROOF_SIDECAR_URL"] + "/invoke",
            data=json.dumps({"symbol": "markdown_it.MarkdownIt.evil",
                             "input": {"text": "x"}, "request_nonce": "rn"}).encode(),
            headers={"Content-Type": "application/json",
                     "X-Sidecar-Token": env["REPOPROOF_SIDECAR_TOKEN"]})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        assert e.value.code == 400
        body = json.loads(e.value.read().decode("utf-8"))
    finally:
        h.shutdown()

    assert called == [], "白名单外的符号竟然被执行了"
    # **拒绝必须是显式的,不能是"碰巧崩了"**。
    #
    # 变异闸门 M51d 抓到的逃逸:把白名单判断掏掉之后,`fn` 是 None,调用它
    # 抛 TypeError 被兜底捕获,照样返回 400 —— 状态码一模一样,而防护其实
    # 已经没了。碰巧崩了很脆:换个 `dispatch.get(symbol, default)`、或者
    # `fn` 恰好是个可调用对象,这份"保护"就当场消失。
    #
    # 所以钉的是**它说不说得出理由**,而不是它有没有失败。
    assert "未支持的符号" in body.get("error", ""), (
        f"拒绝了,但说不出是因为符号不在白名单里 —— 那是碰巧崩了,"
        f"不是白名单在拦:{body}")
    from repoproof.receipts.ledger import read_ledger

    assert read_ledger(h.ledger_path) == [], "被拒的调用不该留下回执"


def test_p6b_bad_token_is_refused(tmp_path):
    """P6 的另一半:令牌不对一律拒 —— 端点不是公开的。"""
    import urllib.error
    import urllib.request

    h = _live_sidecar(tmp_path)
    try:
        req = urllib.request.Request(
            h.base_url + "/invoke",
            data=json.dumps({"input": {"text": "x"}}).encode(),
            headers={"Content-Type": "application/json",
                     "X-Sidecar-Token": "wrong"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        assert e.value.code == 403
    finally:
        h.shutdown()


def test_sidecar_lives_on_the_executor_face_not_the_verifier_face():
    """分面归属:sidecar 改变 agent 能做什么 → executor_semantics。

    回执三件套只负责验 → verifier。把它们混成一面,"改了验证器"和"换了
    被测系统"就再也分不开,跨代可比性判定当场失真。"""
    from repoproof.agents.profiles import face_of

    assert face_of("execution/upstream_sidecar.py") == "executor_semantics"
    assert face_of("execution/runtime_profiles.py") == "executor_semantics"
    assert face_of("receipts/verify.py") == "verifier"
    assert face_of("receipts/ledger.py") == "verifier"
