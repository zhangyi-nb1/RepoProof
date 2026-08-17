"""Agent backend 轴的钉死(DSH 阶段 2,ADR-DSH-MINIMAL-AGENT-BACKEND §3)。

**冻结判据**(先写判据与反例,再写实现;措辞此后不改):

- B1 **缺省即现状**:不传 backend、或显式传 DEFAULT_BACKEND,标签与哈希
  逐字节等于改动前 —— E0/E0-H0/E1-… 一个字符不许动。反例:加参数时顺手
  "规整"了主族标签 —— 全部历史发次跨代失配,而被测系统一字未变。
- B2 **外来 backend 自成代际族,不派生 E0/E1**:S2-S5 的推导规则读的是
  mini-swe 的配置面,对外来 backend 全部失真 —— DSH minimal 带
  str_replace_editor,照推会得 "S4",但那不是"我们给执行器加了 editor",
  是另一个被测系统本来就长那样。反例:让 DSH 发次标成 "E1-S3+S4" ——
  它会与真正的 S4 消融发次合池互比,单变量归因当场作废。
- B3 **后缀语义跨族不变**:-H0(引导面被摘)与 +runtime_profile(交付
  拓扑)对 B 族同样成立、同样拼法。反例:B 族不拼 -H0 —— 桥接批里 DSH
  臂与 mini-swe H0 臂在"是否摘引导"这个轴上失去可对读性。
- B4 **backend 不进三面内容哈希,单列成列**:tool/context/budget 三面
  hash 对 backend 不敏感;分池隔离由代际族 + backend_id 列承担。反例:
  把 backend 拌进 tool 面 —— 同一份工具配置在两个 backend 下 hash 不同,
  跨 backend 对读"工具面是否相同"变成不可能。

判据只管标签与列;DSH 进程、事件、预算的行为由后续阶段各自的钉死执法。
"""

from __future__ import annotations

from repoproof.agents.profiles import DEFAULT_BACKEND, exec_generation, profile_hashes

# E0 形状(与 test_wh_harness_modes 的钉同源):全历史重发、单 bash。
_E0_CTX = {"policy": "full-history-resend", "obs_char_cap": 8000}
_E0_TOOL = {"action_protocol": "bash-block", "tools": ["bash"]}
# DSH minimal 组合的工具面形状:持久 bash + editor —— 正是 B2 反例里
# 会被误推成 "S3+S4" 的那种脸。
_DSH_TOOL = {"action_protocol": "dsh-jsonrpc", "tools": ["bash", "str_replace_editor"],
             "persistent_shell": True}
_BUDGET = {"max_rounds": 1, "max_model_calls": 30}


def test_b1_default_backend_labels_unchanged() -> None:
    """B1:缺省与显式 DEFAULT_BACKEND 逐字节复现改动前的主族标签。"""
    assert DEFAULT_BACKEND == "mini-swe"
    assert exec_generation(context=_E0_CTX, tool=_E0_TOOL) == "E0"
    assert exec_generation(context=_E0_CTX, tool=_E0_TOOL,
                           backend=DEFAULT_BACKEND) == "E0"
    assert exec_generation(context={**_E0_CTX, "guidance": "none"},
                           tool=_E0_TOOL) == "E0-H0"
    assert exec_generation(context={"prune_policy": "window-v1", "guidance": "none"},
                           tool=_E0_TOOL) == "E1-S2-H0"
    assert exec_generation(context={"prune_policy": "window-v1", "guidance": "none"},
                           tool=_E0_TOOL, backend=DEFAULT_BACKEND) == "E1-S2-H0"


def test_b2_foreign_backend_own_family_never_e_family() -> None:
    """B2:DSH 形状的工具面在 B 族下不得推出 E0/E1/S4。"""
    gen = exec_generation(context=_E0_CTX, tool=_DSH_TOOL, backend="dsh-minimal")
    assert gen == "B-dsh-minimal"
    # 反例面:哪怕上下文面也长得"像 S2",照样不许进 E 族
    gen2 = exec_generation(context={"policy": "dsh-native"}, tool=_DSH_TOOL,
                           backend="dsh-minimal")
    assert gen2 == "B-dsh-minimal"
    for g in (gen, gen2):
        assert not g.startswith(("E0", "E1"))
        assert "S4" not in g and "S3" not in g and "S2" not in g


def test_b3_suffixes_compose_identically_for_b_family() -> None:
    """B3:-H0 与 +runtime_profile 对 B 族同样成立、同样拼法。"""
    assert exec_generation(context={**_E0_CTX, "guidance": "none"}, tool=_DSH_TOOL,
                           backend="dsh-minimal") == "B-dsh-minimal-H0"
    assert exec_generation(
        context={**_E0_CTX, "guidance": "none"}, tool=_DSH_TOOL,
        runtime_profile="rt-dsh-minimal-0.1.0rc6-v1", backend="dsh-minimal",
    ) == "B-dsh-minimal-H0+rt-dsh-minimal-0.1.0rc6-v1"
    # in-process 缺省 runtime 不拼后缀 —— 与主族同规则
    assert exec_generation(context=_E0_CTX, tool=_DSH_TOOL, backend="dsh-minimal",
                           runtime_profile="rt-inprocess-v1") == "B-dsh-minimal"


def test_b4_backend_id_column_and_hash_invariance() -> None:
    """B4:三面 hash 对 backend 不敏感;backend_id 单列承担分池。"""
    base = profile_hashes(tool=_DSH_TOOL, context=_E0_CTX, budget=_BUDGET)
    dsh = profile_hashes(tool=_DSH_TOOL, context=_E0_CTX, budget=_BUDGET,
                         backend="dsh-minimal")
    for face in ("tool_profile_hash", "context_profile_hash", "budget_profile_hash"):
        assert base[face] == dsh[face], face
    assert base["backend_id"] == "mini-swe"
    assert dsh["backend_id"] == "dsh-minimal"
    assert dsh["exec_generation"] == "B-dsh-minimal"
    # 缺省路径的代际不因新列而变(B1 在 hash 出口的再执法)
    assert base["exec_generation"] == "E1-S3+S4"
