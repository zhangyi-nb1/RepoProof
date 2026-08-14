"""S2 上下文治理的钉死:spill + 确定性 prune(EXECUTOR-UPGRADE-PLAN §3-S2)。

**冻结判据**(计划里已冻结的 C1–C4,这里逐条落成可执行断言;措辞不改):

- C1 **正确性**:fake-scripted 正控在 E1 下公开+隐藏全绿;T2v5 正控树五物
  验证结论与 E0 完全一致。(这条由 F0 冒烟与控制组实跑执法,不在本文件。)
- C2 **无信息害**:prune 只许折叠 (a)(b)(c) 三型,且**折叠必须留可回读路径**。

  > **回读路径是"重跑命令",不是 artifact 引用**(2026-08-14 核实后定):
  > 我最初以为 clip 掉的中段不可回读,逐条查了触发截断的命令 —— 八条里
  > 七条是 `sed -n` 文件读、一条是 pytest,**全都重跑即可拿回**。而
  > artifact 那条路走不通:策略拒读名单含 `xiangmu/repoproof`,agent 读不到
  > `runs/` 下的 artifact(真让它读还会挨着 `oracle_snapshot/`)。
  > 故存根给的是**命令**,模型照着重跑就行。
- C3 **有效性**:S0 基线上重复输入占比显著下降。(方向性判据,具体数出脚本;
  不预设百分比,防事后挪门槛。由消融批执法,不在本文件。)
- C4 **证据完整**:重放/审计用的 trace 与 artifact 全量不减;
  `projection.applied` 可逐条对回。

本文件执法 **C2 与 C4 的可单测部分**,外加投影器自身的确定性:

- D1 **只动模型视图,不动历史**:`project()` 必须返回新列表,入参列表逐字节
  不变。反例:原地改 messages —— agent 的历史被投影污染,轨迹与证据一起失真,
  C4 直接破。
- D2 **确定性**:同样的输入投影两次结果完全相同,不含随机/时间/字典序。
- D3 **最后一次永不折叠**:任何折叠规则都只折叠**更早**的那些,最近状态必须
  原样保留。反例:把最新的 `git diff` 折叠掉 —— 模型看不到当前状态了。
- D4 **折叠存根必须带回读坐标**:存根里要有被折叠消息的序号**与原命令**,
  模型照命令重跑即可拿回内容。没有命令的存根等于"丢了还不告诉你怎么找回"。
"""

from __future__ import annotations

import copy

from repoproof.agents.context_projector import project


def _tool(content: str, *, artifact: str = "", cmd: str = "") -> dict:
    return {"role": "tool", "content": content,
            "extra": {"raw_output": content, "artifact_ref": artifact, "command": cmd}}


def _asst(cmd: str) -> dict:
    return {"role": "assistant", "content": None,
            "extra": {"actions": [{"command": cmd}]}}


def _history(*pairs: tuple[str, str, str]) -> list[dict]:
    """pairs = (command, output, artifact_ref)"""
    msgs: list[dict] = [{"role": "system", "content": "sys"},
                        {"role": "user", "content": "task"}]
    for cmd, out, art in pairs:
        msgs.append(_asst(cmd))
        msgs.append(_tool(out, artifact=art, cmd=cmd))
    return msgs


# ---------------------------------------------------------------- clip 不动
# S2 **不改** clip_observation:核实后确认它截掉的中段可由重跑命令拿回,
# 而 artifact 回读那条路被策略拒读名单挡死。改它没有收益、只有风险。
# 这里钉死"没改",防止后来者以为 S2 应该动它。

def test_s2_does_not_touch_clip_observation():
    """S2 的范围声明:观察截断沿用 E0 原样,本步只做历史折叠。"""
    from repoproof.agents.repoproof_env import clip_observation

    body = "first\n" + "x" * 5000
    seen = clip_observation(body, 1000)

    assert seen.startswith("first"), "首行红线不得变"
    assert "obs-cap" in seen and "sed -n" in seen, "E0 的截断标记与定向读取提示应原样保留"


# ---------------------------------------------------------------- prune(C2/D*)

def test_project_does_not_mutate_the_input_history():
    """D1:只动模型视图,不动历史 —— 否则轨迹与证据一起失真(C4 破)。"""
    msgs = _history(("ls", "", "a1"), ("ls", "", "a2"), ("ls", "", "a3"))
    before = copy.deepcopy(msgs)

    project(msgs)

    assert msgs == before, "project() 原地改了入参 —— agent 历史被投影污染"


def test_projection_is_deterministic():
    """D2:同输入投两次,结果完全相同。"""
    msgs = _history(("ls", "out", "a1"), ("pwd", "/x", "a2"), ("ls", "out", "a3"))

    a, _ = project(msgs)
    b, _ = project(msgs)

    assert a == b


def test_rule_a_folds_repeated_zero_output_commands():
    """折叠规则 (a):成功且零输出的重复命令,只留最后一次。"""
    msgs = _history(("touch f", "", "a1"), ("touch f", "", "a2"), ("touch f", "", "a3"))

    out, manifest = project(msgs)

    folded = [m for m in out if m.get("extra", {}).get("projection") == "folded"]
    assert len(folded) == 2, f"应折叠前两次,实折 {len(folded)}"
    assert manifest["folded_messages"] == 2


def test_rule_c_folds_identical_command_and_output():
    """折叠规则 (c):(命令, 输出) 完全相同的更早那些。"""
    msgs = _history(("cat x", "SAME", "a1"), ("ls", "other", "a2"), ("cat x", "SAME", "a3"))

    out, _ = project(msgs)
    bodies = [m["content"] for m in out if m["role"] == "tool"]

    assert bodies[-1] == "SAME", "最近一次必须保留正文"
    assert "SAME" not in bodies[0], "更早的同命令同输出没被折叠"


def test_rule_b_folds_superseded_large_results_only():
    """折叠规则 (b):同命令的**大**结果被后来的覆盖才折叠。

    只折大结果是刻意的:token 都在大结果上,而小结果折了省不下什么、
    却扩大了改动面。第一刀要可归因。"""
    big_old, big_new = "X" * 9000, "Y" * 9000
    msgs = _history(("cat big", big_old, "a1"), ("cat big", big_new, "a2"))

    out, _ = project(msgs)
    bodies = [m["content"] for m in out if m["role"] == "tool"]

    assert bodies[-1] == big_new, "最近一次必须原样保留"
    assert len(bodies[0]) < 500, "被覆盖的大结果没折叠"


def test_small_superseded_results_are_left_alone():
    """(b) 的边界:小结果不折 —— 省不下 token,却平白扩大改动面。"""
    msgs = _history(("ls", "a\nb", "a1"), ("ls", "a\nc", "a2"))

    out, _ = project(msgs)
    bodies = [m["content"] for m in out if m["role"] == "tool"]

    assert bodies[0] == "a\nb", "小的被覆盖结果不该动"


def test_last_occurrence_is_never_folded():
    """D3:任何规则都只折更早的,最近状态原样保留。"""
    msgs = _history(("git diff", "", "a1"), ("git diff", "", "a2"))

    out, _ = project(msgs)
    tools = [m for m in out if m["role"] == "tool"]

    assert tools[-1].get("extra", {}).get("projection") != "folded", (
        "最新一条被折叠 —— 模型看不到当前状态了")


def test_fold_stub_carries_reread_coordinates():
    """D4:存根必须给出被折叠消息的序号**与原命令** —— 照命令重跑即可拿回。"""
    msgs = _history(("cat big", "X" * 9000, "aa11"), ("cat big", "Y" * 9000, "bb22"))

    out, _ = project(msgs)
    stub = [m for m in out if m.get("extra", {}).get("projection") == "folded"][0]
    idx = [i for i, m in enumerate(out)
           if m.get("extra", {}).get("projection") == "folded"][0]

    assert f"#{idx}" in stub["content"], "存根缺被折叠消息的序号"
    assert "cat big" in stub["content"], "存根缺原命令 —— 模型不知道重跑什么"


def test_manifest_is_auditable():
    """C4:manifest 要能逐条对回 —— 折了哪几条、省了多少、按哪条规则。"""
    msgs = _history(("touch f", "", "a1"), ("touch f", "", "a2"),
                    ("cat big", "X" * 9000, "a3"), ("cat big", "Y" * 9000, "a4"))

    _, manifest = project(msgs)

    assert manifest["folded_messages"] >= 2
    assert manifest["saved_chars"] > 0
    for item in manifest["folded"]:
        assert "msg_index" in item and "rule" in item and "command" in item


def test_system_and_user_messages_are_never_touched():
    """固定前缀不动:system 与首条 user(任务契约)必须原样。

    反例:把任务描述也折了 —— 模型失去目标约束,这是最不能省的部分。"""
    msgs = _history(("ls", "", "a1"), ("ls", "", "a2"))

    out, _ = project(msgs)

    assert out[0] == msgs[0] and out[1] == msgs[1]


# ------------------------------------------------- S2 判别力实测(Null Result)
# 2026-08-14:把三条折叠规则跑在**真实 E0 轨迹**上,结论分两层:
#
#   S0 基线那 6 发(order 64-69,消融要比的正是它们):折叠 **0** 条
#   更早的 17 条轨迹(T1v1/T2v4/T3v1-v5 早期):规则 (b) 偶尔命中,共 23 次,
#                                              每次省 2.6k-15k 字符
#
# 根因与 S0 的"重复命令全 0"同源:三条规则**全部以命令重复为前提**,而
# 当前模型(gpt-5.5/5.6)在基线发次里从不重复同一条命令。计划里的 S2 设计
# 照搬了报告 §33.5 的 model-free pruning 清单(重复零输出命令 / 重复 pwd·ls /
# 被覆盖的旧 git diff / 重复的 public test PASS / 完全相同的调用与结果)——
# **那份清单的前提在本仓的基线数据上不存在**。我照抄了通用建议,没先验证
# 它的前提是否成立。
#
# 量级上也不够:即使在命中的旧轨迹里,省下的也只是工具正文的个位数百分比,
# 而重复输入占比是 89.9%-94.6%。那 90% 不是"重复项",是**全历史重发本身**
# ——每轮把所有(各不相同的)历史消息再发一遍。折叠重复项治不了它。
#
# 按 §17 停止规则:机制无效则保持基线,不硬上。S2 记 Null Result。

def test_fold_rules_have_no_target_in_the_e0_baseline():
    """S2 三规则在**基线六发**上判别力为 0 —— Null Result,不是 bug。

    规则本身正确(上面 11 条单测全绿),是靶子不存在。若此用例转红,说明
    基线数据里出现了重复命令,S2 的收益需要重新评估。"""
    import json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    baseline = repo / "docs" / "evidence" / "exec_metrics" / "baseline-E0.json"
    if not baseline.is_file():
        return                                     # 基线未生成时不做断言

    bundles = [r["bundle"] for r in json.loads(baseline.read_text(encoding="utf-8"))["runs"]]
    folded_total = 0
    checked = 0
    for name in bundles:
        for traj in sorted((repo / "runs" / name).glob("trajectory_round*.json")):
            msgs = json.loads(traj.read_text(encoding="utf-8")).get("messages") or []
            if len(msgs) < 6:
                continue
            checked += 1
            folded_total += project(msgs)[1]["folded_messages"]

    assert checked, "基线 bundle 里没有可检查的轨迹"
    assert folded_total == 0, (
        f"基线六发里出现了 {folded_total} 条可折叠项 —— S2 的靶子出现了,"
        "重新评估折叠规则的收益(2026-08-14 实测为 0)")
