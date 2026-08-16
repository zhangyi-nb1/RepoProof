"""deepseek-native 适配器钉(P-D §6)。

钉五条卫生规则(R1-R5)、哈希纪律(§55 消融单变量可比)、env 分流与
TokenBudgetedModel 同步记账形状。全部用**真 litellm 对象**过内核路径
(ModelResponse/Message),只在网络边界(litellm.completion /
stream_chunk_builder)打桩 —— 桩返回真类型,不是 MagicMock 空壳。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import litellm
import pytest

from repoproof.agents.deepseek_native import (
    DS_PROFILES,
    FORBIDDEN_MODEL_KWARGS,
    DeepSeekNativeModel,
    DeepSeekProviderConfig,
    build_deepseek_provider,
    build_model_kwargs,
)
from repoproof.agents.provider_gate import ProviderConfig


def _provider(profile: str = "DS-NATIVE-HIGH-DET") -> DeepSeekProviderConfig:
    return build_deepseek_provider(
        profile=profile,
        api_base="https://api.example-ds.com/v1",
        api_key="sk-test-never-logged",
        model_name="deepseek-v4-pro",
    )


# ---------------------------------------------------------------- 哈希纪律


def test_two_ablation_profiles_hash_differently_single_variable_comparable():
    a = _provider("DS-NATIVE-HIGH-DET")
    b = _provider("DS-NATIVE-MAX-OFFICIAL-LIKE")
    assert a.config_sha256 != b.config_sha256
    na, nb = a.normalized(), b.normalized()
    # 全部行为旋钮必须都在哈希输入里 —— 消融的可比性由哈希层背书
    for knob in ("top_p", "reasoning_effort", "reasoning_passback", "temperature_policy"):
        assert knob in na and knob in nb
    diff = {k for k in na if na[k] != nb[k]}
    assert diff == {"top_p", "reasoning_effort", "temperature_policy"}


def test_provider_type_separates_deepseek_from_openai_compatible_hash():
    ds = _provider()
    oa = ProviderConfig(
        provider="openai-compatible",
        model_name=ds.model_name,
        api_base=ds.api_base,
        api_key=ds.api_key,
        temperature_policy=ds.temperature_policy,
        action_protocol=ds.action_protocol,
    )
    assert ds.normalized()["provider_type"] == "deepseek-native"
    assert ds.config_sha256 != oa.config_sha256


def test_api_key_never_in_normalized_or_hash_input():
    n = json.dumps(_provider().normalized())
    assert "sk-test-never-logged" not in n
    assert "api.example-ds.com" not in n  # base 只以指纹形式出现


def test_unknown_profile_rejected_and_action_protocol_frozen_native():
    with pytest.raises(ValueError, match="unknown deepseek profile"):
        build_deepseek_provider(
            profile="DS-MADE-UP", api_base="https://x", api_key="k", model_name="m"
        )
    assert _provider().action_protocol == "native"


# ---------------------------------------------------------------- 旋钮→kwargs


def test_build_model_kwargs_high_det():
    kw = build_model_kwargs(_provider("DS-NATIVE-HIGH-DET"), call_timeout_s=120.0)
    assert kw == {"temperature": 0.0, "reasoning_effort": "high", "timeout": 120.0}


def test_build_model_kwargs_max_official_like_and_provider_default():
    kw = build_model_kwargs(_provider("DS-NATIVE-MAX-OFFICIAL-LIKE"), call_timeout_s=None)
    assert kw == {"temperature": 1.0, "top_p": 0.95, "reasoning_effort": "max"}
    pd = DeepSeekProviderConfig(
        provider="deepseek-native", model_name="m", api_base="b", api_key="k",
        temperature_policy="provider_default",
    )
    assert "temperature" not in build_model_kwargs(pd, None)


# ---------------------------------------------------------------- env 分流


def test_provider_from_env_deepseek_branch(monkeypatch):
    from repoproof.runner.agent_run import provider_from_env

    monkeypatch.setenv("REPOPROOF_PROVIDER", "deepseek-native")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_BASE", "https://api.example-ds.com/")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_KEY", "sk-env")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_DEFAULT", "deepseek-v4-pro")
    monkeypatch.delenv("REPOPROOF_MODEL", raising=False)
    monkeypatch.setenv("REPOPROOF_DS_PROFILE", "DS-NATIVE-HIGH-DET")
    p = provider_from_env()
    assert isinstance(p, DeepSeekProviderConfig)
    assert p.model_name == "deepseek-v4-pro"
    assert p.api_base == "https://api.example-ds.com"  # 尾斜杠已剥
    assert p.reasoning_effort == "high"


def test_provider_from_env_deepseek_requires_explicit_profile(monkeypatch):
    from repoproof.runner.agent_run import provider_from_env

    monkeypatch.setenv("REPOPROOF_PROVIDER", "deepseek-native")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_BASE", "https://api.example-ds.com")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_KEY", "sk-env")
    monkeypatch.setenv("REPOPROOF_DEEPSEEK_DEFAULT", "deepseek-v4-pro")
    monkeypatch.delenv("REPOPROOF_DS_PROFILE", raising=False)
    with pytest.raises(RuntimeError, match="REPOPROOF_DS_PROFILE"):
        provider_from_env()


def test_provider_from_env_openai_path_unchanged(monkeypatch):
    from repoproof.runner.agent_run import provider_from_env

    monkeypatch.delenv("REPOPROOF_PROVIDER", raising=False)
    monkeypatch.setenv("REPOPROOF_API_BASE", "https://oa.example.com/v1")
    monkeypatch.setenv("REPOPROOF_API_KEY", "sk-oa")
    monkeypatch.setenv("REPOPROOF_MODEL", "gpt-5.5")
    p = provider_from_env()
    assert type(p) is ProviderConfig and p.provider == "openai-compatible"


# ---------------------------------------------------------------- 构造期防线


def _model(**over) -> DeepSeekNativeModel:
    kw = dict(model_name="deepseek/deepseek-v4-pro",
              model_kwargs={"temperature": 0.0},
              cost_tracking="ignore_errors")
    kw.update(over)
    return DeepSeekNativeModel(**kw)


def test_forbidden_model_kwargs_rejected_at_construction():
    for bad in FORBIDDEN_MODEL_KWARGS:
        with pytest.raises(ValueError, match="deepseek-native owns"):
            _model(model_kwargs={bad: "x"})


def test_model_name_must_use_deepseek_route():
    with pytest.raises(ValueError, match="deepseek/"):
        _model(model_name="openai/deepseek-v4-pro")


def test_query_time_forbidden_kwargs_refused_before_wire(monkeypatch):
    m = _model()
    monkeypatch.setattr(litellm, "completion",
                        lambda **kw: pytest.fail("must refuse before hitting the wire"))
    with pytest.raises(ValueError, match="refusing to send"):
        m._query([{"role": "user", "content": "hi"}], tool_choice="auto")


# ---------------------------------------------------------------- 消息卫生 R1/R2/R5


def _assistant_from_dump(**over) -> dict:
    """带 model_dump 全部脏字段的 assistant 消息(真实回环形状)。"""
    msg = {
        "role": "assistant", "content": None, "function_call": None,
        "provider_specific_fields": {"x": 1}, "reasoning_content": "THOUGHTS",
        "tool_calls": [{"id": "call_1", "type": "function", "index": 0,
                        "function": {"name": "bash", "arguments": "{\"command\": \"ls\"}"}}],
        "extra": {"actions": [], "response": {}, "cost": 0.0},
    }
    msg.update(over)
    return msg


def test_prepare_tool_loop_keeps_reasoning_only_with_tool_calls():
    m = _model()
    loop_msg, final_msg = _assistant_from_dump(), _assistant_from_dump(tool_calls=None)
    out = m._prepare_messages_for_api([loop_msg, final_msg])
    # 工具轮:reasoning 保留、content 非 null、index/脏字段全剥
    assert out[0] == {
        "role": "assistant", "content": "", "reasoning_content": "THOUGHTS",
        "tool_calls": [{"id": "call_1", "type": "function",
                        "function": {"name": "bash", "arguments": "{\"command\": \"ls\"}"}}],
    }
    # 非工具轮:reasoning 剥除
    assert out[1] == {"role": "assistant", "content": ""}


def test_prepare_strip_mode_never_passes_reasoning_back():
    m = _model(reasoning_passback="strip")
    out = m._prepare_messages_for_api([_assistant_from_dump()])
    assert "reasoning_content" not in out[0]
    assert out[0]["content"] == ""  # R1 仍然成立


def test_prepare_tool_message_whitelist_and_extra_stripped():
    m = _model()
    out = m._prepare_messages_for_api([
        {"role": "tool", "content": None, "tool_call_id": "call_1",
         "name": "bash", "junk_field": 1, "extra": {"z": 1}},
        {"role": "user", "content": "hi", "extra": {"z": 1}},
        {"role": "system", "content": "sys"},
    ])
    assert out[0] == {"role": "tool", "content": "", "tool_call_id": "call_1", "name": "bash"}
    assert out[1] == {"role": "user", "content": "hi"}
    assert out[2] == {"role": "system", "content": "sys"}


# ---------------------------------------------------------------- 流式 query 全链


def _fake_stream_env(monkeypatch, *, builder_reasoning: str | None,
                     delta_reasoning: tuple[str, ...] = ()):
    """打桩网络边界:completion 返回可迭代 chunk,builder 返回真 ModelResponse。"""
    seen: dict = {}
    chunks = [SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(reasoning_content=rc))]) for rc in delta_reasoning]
    chunks.append(SimpleNamespace(choices=[]))  # usage 尾包(无 choices)形状

    def fake_completion(**kw):
        seen.update(kw)
        return iter(chunks)

    message = {"role": "assistant", "content": None,
               "tool_calls": [{"id": "call_9", "type": "function",
                               "function": {"name": "bash",
                                            "arguments": json.dumps({"command": "echo ok"})}}]}
    resp = litellm.ModelResponse(
        choices=[{"index": 0, "finish_reason": "tool_calls", "message": message}],
        usage={"prompt_tokens": 321, "completion_tokens": 45},
    )
    if builder_reasoning is not None:
        resp.choices[0].message.reasoning_content = builder_reasoning

    def fake_builder(got_chunks, messages=None):
        seen["builder_chunks"] = list(got_chunks)
        return resp

    monkeypatch.setattr(litellm, "completion", fake_completion)
    monkeypatch.setattr(litellm, "stream_chunk_builder", fake_builder)
    return seen


def test_query_streams_with_usage_and_owned_call_surface(monkeypatch):
    m = _model()
    seen = _fake_stream_env(monkeypatch, builder_reasoning="B-THOUGHTS")
    out = m.query([{"role": "user", "content": "go"}])
    # R4:流式 + include_usage;调用面由适配器 own
    assert seen["stream"] is True
    assert seen["stream_options"] == {"include_usage": True}
    assert "tool_choice" not in seen
    assert [t["function"]["name"] for t in seen["tools"]] == ["bash"]
    assert seen["model"] == "deepseek/deepseek-v4-pro"
    # 动作解析走基类 parse_toolcall_actions
    assert [a["command"] for a in out["extra"]["actions"]] == ["echo ok"]
    # builder 给的 reasoning 原样在消息 dict 里(DefaultAgent 会原样存档)
    assert out["reasoning_content"] == "B-THOUGHTS"


def test_query_response_shape_feeds_token_budget_sync_accounting(monkeypatch):
    from repoproof.agents.token_budget import TokenBudgetedModel

    m = _model()
    _fake_stream_env(monkeypatch, builder_reasoning=None)
    totals = {"in": 0, "out": 0, "seen": False}
    budget = TokenBudgetedModel(inner=m, totals=totals,
                                max_input_tokens=10_000, max_output_tokens=10_000)
    budget.query([{"role": "user", "content": "go"}])
    # **同步**记账(执法权威,不等异步钩子)必须从 extra.response.usage
    # 读到真数 —— 不是 0,不是缺席(LESSONS #39 H7-a)
    assert budget.sync_seen is True
    assert (budget.sync_in, budget.sync_out) == (321, 45)
    assert (budget.used_in, budget.used_out) == (321, 45)


def test_reasoning_salvage_when_builder_drops_it(monkeypatch):
    m = _model()
    _fake_stream_env(monkeypatch, builder_reasoning=None,
                     delta_reasoning=("part1 ", "part2"))
    out = m.query([{"role": "user", "content": "go"}])
    assert out["reasoning_content"] == "part1 part2"


def test_empty_stream_raises_for_whole_request_retry(monkeypatch):
    m = _model()
    monkeypatch.setattr(litellm, "completion", lambda **kw: iter([]))
    monkeypatch.setattr(litellm, "stream_chunk_builder", lambda c, messages=None: None)
    with pytest.raises(RuntimeError, match="no usable chunks"):
        m._query([{"role": "user", "content": "go"}])


def test_profiles_registry_matches_prereg_candidates():
    assert set(DS_PROFILES) == {"DS-NATIVE-HIGH-DET", "DS-NATIVE-MAX-OFFICIAL-LIKE"}
    hd, mo = DS_PROFILES["DS-NATIVE-HIGH-DET"], DS_PROFILES["DS-NATIVE-MAX-OFFICIAL-LIKE"]
    assert (hd["temperature_policy"], hd["reasoning_effort"]) == ("0", "high")
    assert (mo["temperature_policy"], mo["top_p"], mo["reasoning_effort"]) == ("1.0", "0.95", "max")


# ---------------------------------------------------------------- 接线钉(AST)

# M72f 教训:文本断言会被注释喂饱;接线钉一律走 AST。


def _host_guided_ast():
    import ast
    from pathlib import Path

    import repoproof.runner.host_guided as hg

    return ast.parse(Path(hg.__file__).read_text())


def _provider_type_ifs(tree, op_type):
    """找出所有 `provider.PROVIDER_TYPE <op> "deepseek-native"` 的 If 节点。"""
    import ast

    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        t = node.test
        if not (isinstance(t.left, ast.Attribute) and t.left.attr == "PROVIDER_TYPE"):
            continue
        if len(t.ops) == 1 and isinstance(t.ops[0], op_type) and (
            len(t.comparators) == 1
            and isinstance(t.comparators[0], ast.Constant)
            and t.comparators[0].value == "deepseek-native"
        ):
            hits.append(node)
    return hits


def _body_calls(if_node, name: str) -> bool:
    import ast

    for sub in ast.walk(ast.Module(body=if_node.body, type_ignores=[])):
        if isinstance(sub, ast.Call):
            f = sub.func
            if (isinstance(f, ast.Name) and f.id == name) or (
                isinstance(f, ast.Attribute) and f.attr == name
            ):
                return True
    return False


def _body_assigns_env(if_node, key: str) -> bool:
    import ast

    for sub in ast.walk(ast.Module(body=if_node.body, type_ignores=[])):
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.slice, ast.Constant)
                        and tgt.slice.value == key):
                    return True
    return False


def test_wiring_deepseek_model_constructed_inside_the_eq_branch():
    """host_guided 的模型构造:DeepSeekNativeModel 与 build_model_kwargs
    必须都在 `PROVIDER_TYPE == "deepseek-native"` 的分支体内 —— 分支
    条件翻转/删除、或构造被挪出守卫,这里必须红。"""
    import ast

    tree = _host_guided_ast()
    hits = _provider_type_ifs(tree, ast.Eq)
    assert any(
        _body_calls(h, "DeepSeekNativeModel") and _body_calls(h, "build_model_kwargs")
        for h in hits
    ), "DeepSeekNativeModel(+build_model_kwargs) 必须由 == 分支守卫"


def test_ledger_provider_label_comes_from_provider_type_not_a_literal():
    """台账通道归属:provider_label 按 PROVIDER_TYPE 出值(fake 冒烟例外);
    _finish 里不许再出现写死的 "openai-compatible" 字面量,且每个
    _finish 调用点都必须经 provider_label 传 provider_type —— deepseek
    发次记成 openai-compatible 就是静默换模的台账端。"""
    import ast

    from repoproof.runner.host_guided import provider_label

    assert provider_label(None) == "fake"
    assert provider_label(_provider()) == "deepseek-native"
    oa = ProviderConfig(provider="openai-compatible", model_name="m",
                        api_base="b", api_key="k")
    assert provider_label(oa) == "openai-compatible"

    tree = _host_guided_ast()
    finish_def = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == "_finish")
    literals = [n for n in ast.walk(finish_def)
                if isinstance(n, ast.Constant) and n.value == "openai-compatible"]
    assert not literals, "_finish 内禁止写死通道字面量"
    call_sites = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "_finish"]
    assert call_sites, "找不到 _finish 调用点"
    for c in call_sites:
        kw = {k.arg: k.value for k in c.keywords}
        v = kw.get("provider_type")
        assert (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                and v.func.id == "provider_label"), "调用点必须经 provider_label"


def test_wiring_openai_env_only_fed_in_the_not_deepseek_branch():
    """OPENAI_API_KEY/BASE 只允许在 `PROVIDER_TYPE != "deepseek-native"`
    分支体内赋值(deepseek 的 key 绝不进错通道变量);deepseek 分支须
    自设 DEEPSEEK_API_KEY。"""
    import ast

    tree = _host_guided_ast()
    ne_ifs = _provider_type_ifs(tree, ast.NotEq)
    assert any(_body_assigns_env(h, "OPENAI_API_KEY") for h in ne_ifs), \
        "OPENAI_API_KEY 赋值必须在 != 分支内"
    # 全文所有 OPENAI_API_KEY 赋值都要被 != 守卫覆盖(不允许守卫外副本)
    guarded = {id(s) for h in ne_ifs for s in ast.walk(
        ast.Module(body=h.body, type_ignores=[]))}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.slice, ast.Constant)
                        and tgt.slice.value == "OPENAI_API_KEY"):
                    assert id(node) in guarded, "发现守卫外的 OPENAI_API_KEY 赋值"
    eq_ifs = _provider_type_ifs(tree, ast.Eq)
    assert any(_body_assigns_env(h, "DEEPSEEK_API_KEY") for h in eq_ifs), \
        "deepseek 分支必须自设 DEEPSEEK_API_KEY"
