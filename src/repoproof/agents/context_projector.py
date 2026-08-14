"""完整事件 → 模型视图的投影(E1-S2;EXECUTOR-UPGRADE-PLAN §3-S2)。

**它解决的是 S0 量出来的头号浪费**(六发实测,`docs/evidence/exec_metrics/`):

    重复输入占累计输入 89.9%–94.6%   ← 全历史重发,每轮把旧内容重付一遍

**S2 只做 prune,不做 artifact spill** —— 这是核实后的收窄,理由两条:

1. **前提不成立**:我最初把 clip 掉的中段写成"不可回读"。逐条查了触发
   截断的命令,八条里七条是 `sed -n` 文件读、一条是 pytest,**全都重跑
   即可拿回**。真实代价是"再花一次命令预算",不是信息丢失。
2. **那条路走不通**:完整正文确实落在 `runs/<id>/artifacts/`,但策略拒读
   名单含 `xiangmu/repoproof` —— agent 根本读不到;真让它读还会挨着同目录
   下的 `oracle_snapshot/`。

故:**回读路径 = 重跑命令**,存根里给出原命令即可,不需要任何新文件、
不碰策略、不引入泄漏面。

- **prune**:对**历史**消息做确定性折叠,只改模型视图,不动 agent 历史,
  更不动 trace 与 artifact(C4)。零模型参与、零随机 —— 折叠规则全是可
  逐条复核的机械判断。

**折叠三规则**(C2 只许这三型,且每条折叠都必须留可回读路径):

    (a) 成功且零输出的重复命令  → 只留最后一次
    (b) 同一命令的**大**结果被后来的同命令结果覆盖 → 更早的折叠
    (c) (命令, 输出) 完全相同    → 更早的折叠

(b) 刻意只折大结果:token 都在大结果上,小结果折了省不下什么、却平白扩大
改动面 —— 第一刀要可归因。

**为什么折叠是安全的**:每个存根都带着被折叠消息的序号与**原命令**,模型
需要时照着重跑即可。规则 (a)(c) 折的是重复内容,重跑必然一致;规则 (b) 折的
是已被更新结果覆盖的旧状态,重跑拿到的是**当前**状态 —— 而那正是它需要的。
"""

from __future__ import annotations

import re

# (b) 只折这个尺寸以上的被覆盖结果。低于它省不下什么。
SUPERSEDE_MIN_CHARS = 2000

# 折叠存根的尺寸上限(它自己也不能变成新的噪声源)。
_STUB_MAX = 400


def _norm_cmd(cmd: str) -> str:
    return re.sub(r"\s+", " ", (cmd or "").strip()).rstrip(";").strip()


_RULE_WHY = {
    "a": "同一命令的更早一次,零输出",
    "b": "同一命令的更早一次,已被后来的结果覆盖",
    "c": "同一命令的更早一次,输出与后来完全相同",
}


def _fold_stub(rule: str, msg_index: int, size: int, cmd: str) -> str:
    """折叠存根。必须让模型知道:折了哪一条、为什么、怎么拿回来。"""
    return (f"[RepoProof projection: 消息 #{msg_index} 的 {size} 字符正文已折叠"
            f"({_RULE_WHY.get(rule, rule)})。完整正文仍在证据链中;"
            f"需要时重跑该命令即可取回:`{cmd}`]")[:_STUB_MAX]


def _cmd_of(msgs: list[dict], tool_index: int) -> str:
    """工具结果对应的命令:优先自带,否则回看前一条 assistant 的 action。"""
    extra = msgs[tool_index].get("extra") or {}
    if extra.get("command"):
        return _norm_cmd(extra["command"])
    for j in range(tool_index - 1, -1, -1):
        if msgs[j].get("role") == "assistant":
            acts = (msgs[j].get("extra") or {}).get("actions") or []
            return _norm_cmd(acts[0].get("command", "")) if acts else ""
        if msgs[j].get("role") == "tool":
            break
    return ""


def project(messages: list[dict]) -> tuple[list[dict], dict]:
    """完整历史 → 模型视图。返回 (新消息列表, manifest)。

    **绝不原地修改入参**(D1):agent 的历史与轨迹是证据,投影只是给这一次
    请求用的视图。"""
    tools: list[tuple[int, str, str]] = []      # (index, norm_cmd, content)
    for i, m in enumerate(messages):
        if m.get("role") == "tool":
            tools.append((i, _cmd_of(messages, i), m.get("content") or ""))

    # 每条规则都只折"更早的那些";最近一次永远保留(D3)。
    fold: dict[int, str] = {}
    last_by_cmd: dict[str, int] = {}
    last_by_cmd_out: dict[tuple[str, str], int] = {}
    for idx, cmd, body in tools:
        if cmd:
            last_by_cmd[cmd] = idx
        last_by_cmd_out[(cmd, body)] = idx

    for idx, cmd, body in tools:
        if not cmd:
            continue
        newest_same = last_by_cmd.get(cmd)
        if newest_same == idx:
            continue                                     # D3:最近一次不折
        if not body.strip():                             # (a) 零输出重复命令
            fold[idx] = "a"
        elif last_by_cmd_out.get((cmd, body), idx) != idx:   # (c) 命令+输出全同
            fold[idx] = "c"
        elif len(body) >= SUPERSEDE_MIN_CHARS:           # (b) 大结果被覆盖
            fold[idx] = "b"

    out: list[dict] = []
    folded_items: list[dict] = []
    saved = 0
    for i, m in enumerate(messages):
        rule = fold.get(i)
        if rule is None:
            out.append(m)
            continue
        extra = m.get("extra") or {}
        body = m.get("content") or ""
        cmd = _cmd_of(messages, i)
        stub = _fold_stub(rule, i, len(body), cmd)
        out.append({**m, "content": stub,
                    "extra": {**extra, "projection": "folded", "projection_rule": rule}})
        saved += max(0, len(body) - len(stub))
        folded_items.append({"msg_index": i, "rule": rule,
                             "chars": len(body), "command": cmd})

    return out, {"policy": "selective-v1",
                 "messages_in": len(messages),
                 "folded_messages": len(folded_items),
                 "saved_chars": saved,
                 "folded": folded_items}
