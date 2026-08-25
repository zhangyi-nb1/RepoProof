#!/usr/bin/env python3
"""window-v1.1 读取分类器的**零模型**离线重放(P0,2026-08-20)。

为什么要有这个脚本
------------------
E1-DSH-MINIMAL-BRIDGE-1 代 2 的 E5 机制发现:H0(mini-swe)臂六发全部
贴 in-token 墙飞(1.72-1.76M/1.8M = 96-97.5%),元凶是无状态 chat 端点上
的全历史重发。仓里现成的 S2′ 滑动窗口(`project_window`)正是对症的
send 侧折叠,但把它离线重放到这六发轨迹上发现:**deepseek-v4-flash 两发
零激活**(025342/060627)—— flash 惯用 `cd /绝对路径 && sed …` 逐条带路,
链首段是 cd,v1 读取白名单永不命中。与批 14 gpt-5.6 链式命令零激活同构:
**分类器覆盖缺口,不是折叠规则问题**。

v1.1 只修分类(剥链首 cd 导航段 + `pwd` 入读取集),折叠规则与安全边界
(执行型一票否决作用于整条原始命令、窗口保底、最后一次不折)一字未动。
按批 14 的用户处方:修完先**不调模型**,拿代 2 六发 H0 轨迹离线重放,
v1/v1.1 对照出数;真模型资格发(v1.1 在线)另行请批,不在本脚本范围。

口径与在线一致
--------------
在线:`TokenBudgetedModel.query()` 每次调用先投影再发。离线:轨迹里每条
assistant 消息对应一次调用,入参是它之前的前缀;逐前缀重放,manifest 的
`folded_messages` 非空计一次激活。输入 token 节省用
`token_budget.estimate_prompt_tokens`(在线预算执法同一把尺)在投影前后
各估一次,差值即 send 侧省下的量。

自证
----
与 replay_projection_exposure.py 同纪律:先在合成用例上证明量具看得见
该看见的、看不见不该看见的,否则拒绝出数(退出码 3)。对齐审计复用
该脚本原件(偏移映射可靠性,系统性假阳/假阴的唯一来源)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from replay_projection_exposure import alignment_audit  # noqa: E402

from repoproof.agents import context_projector as cp  # noqa: E402
from repoproof.agents.context_projector import (  # noqa: E402
    WINDOW_POLICY,
    WINDOW_READS,
    _cmd_of,
    project_window,
)
from repoproof.agents.token_budget import estimate_prompt_tokens  # noqa: E402

# ------------------------------------------------------------------ 修前量具
# v1 的读取分类器,原文取自 34c6b20;只为算"修前覆盖率",与 v1.1 的差
# 恰是本次修复(cd 剥离 + pwd)。
_READ_CMD_V1 = re.compile(
    r"^\s*(sed|cat|head|tail|grep|rg|ls|find|wc|nl|awk"
    r"|git\s+(diff|show|log|status))\b")


def _is_foldable_read_v1(cmd: str) -> bool:
    if not cmd or cp._EXEC_CMD.search(cmd):
        return False
    return bool(_READ_CMD_V1.match(cmd.split("&&")[0].strip()))


def _project_window_v1(messages: list[dict], *, window: int = WINDOW_READS):
    """v1 分类器 + 同一套窗口规则:只换 `_is_foldable_read`,规则一字不动。

    存根与真投影**逐字同构**(同一格式、同一 _STUB_MAX 截断)—— 两臂存根
    尺寸不同的话,省额对比量的是存根长短,不是折叠覆盖(首版实测:7 字符
    假存根让 v1 的省额虚高 1-2 个百分点,把对照反号)。"""
    reads = [i for i, m in enumerate(messages)
             if m.get("role") == "tool" and _is_foldable_read_v1(_cmd_of(messages, i))]
    keep = set(reads[-window:]) if window > 0 else set()
    victims = set(reads) - keep
    out = []
    for i, m in enumerate(messages):
        if i not in victims:
            out.append(m)
            continue
        body = m.get("content") or ""
        cmd = _cmd_of(messages, i)
        stub = (f"[RepoProof projection: 消息 #{i} 的 {len(body)} 字符正文已折叠"
                f"(窗口外的旧读取结果)。需要时重跑该命令即可取回:`{cmd}`]"
                )[:cp._STUB_MAX]
        out.append({**m, "content": stub})
    return out, {"folded_messages": len(victims)}


# ------------------------------------------------------------------ 重放
def replay_run(run_dir: Path) -> dict:
    calls = a_v1 = a_v11 = f_v1 = f_v11 = 0
    est_base = est_v1 = est_v11 = 0
    for f in sorted(run_dir.glob("trajectory_round*.json")):
        try:
            msgs = json.loads(f.read_text(encoding="utf-8")).get("messages", [])
        except Exception:
            continue
        for i, m in enumerate(msgs):
            if m.get("role") != "assistant":
                continue
            prefix = msgs[:i]
            calls += 1
            est_base += estimate_prompt_tokens(prefix)
            o1, m1 = _project_window_v1(prefix)
            est_v1 += estimate_prompt_tokens(o1)
            o2, m2 = project_window(prefix)
            est_v11 += estimate_prompt_tokens(o2)
            if m1["folded_messages"]:
                a_v1 += 1
                f_v1 += m1["folded_messages"]
            if m2["folded_messages"]:
                a_v11 += 1
                f_v11 += m2["folded_messages"]

    def pct(saved: int) -> float:
        return round(saved / est_base * 100, 1) if est_base else 0.0

    return {"run_id": run_dir.name, "model_calls": calls,
            "activations_v1": a_v1, "activations_v11": a_v11,
            "folded_msgs_v1": f_v1, "folded_msgs_v11": f_v11,
            "est_input_tokens_base": est_base,
            "est_input_tokens_v1": est_v1,
            "est_input_tokens_v11": est_v11,
            "saved_pct_v1": pct(est_base - est_v1),
            "saved_pct_v11": pct(est_base - est_v11)}


# ------------------------------------------------------------------ 自证
def _msg(role: str, **extra) -> dict:
    return {"role": role, "content": "x" * 3000, "extra": extra}


def _pairs(cmds: list[str]) -> list[dict]:
    out: list[dict] = []
    for c in cmds:
        out.append(_msg("assistant", actions=[{"command": c}]))
        out.append(_msg("tool"))
    return out


def selfcheck() -> list[str]:
    bad: list[str] = []
    ws = "/tmp/_sessions/rp-host-agent-x/host"

    # (1) cd 前缀读取链:v1.1 必中、v1 必漏 —— 这正是 flash 两发零激活的形状。
    chain = _pairs([f"cd {ws} && sed -n '1,50p' f{i}.py"
                    for i in range(WINDOW_READS + 3)])
    if not project_window(chain)[1].get("folded_messages"):
        bad.append("自证(1):cd 前缀读取链 v1.1 未命中 —— 剥离没生效")
    if _project_window_v1(chain)[1]["folded_messages"]:
        bad.append("自证(1'):v1 量具竟然命中 —— 修前/修后差值无从谈起")

    # (2) cd 前缀执行链:两边都必须不折(假阳侧 —— 剥离不许放行执行型)。
    execs = _pairs([f"cd {ws} && .venv/bin/python -m pytest -q"
                    for _ in range(WINDOW_READS + 3)])
    if project_window(execs)[1].get("folded_messages"):
        bad.append("自证(2):cd+pytest 链被 v1.1 折了 —— 执行型否决被剥掉了")
    if _project_window_v1(execs)[1]["folded_messages"]:
        bad.append("自证(2'):cd+pytest 链被 v1 折了 —— 修前量具还原错了")

    # (3) 窗口内不折(边界)。
    few = _pairs([f"cd {ws} && cat b{i}.py" for i in range(WINDOW_READS)])
    if project_window(few)[1].get("folded_messages"):
        bad.append("自证(3):窗口内的读取被折叠 —— 窗口边界算错")

    # (4) 入参不可被改(轨迹是证据)。
    before = json.dumps(chain, ensure_ascii=False, sort_keys=True)
    project_window(chain)
    _project_window_v1(chain)
    if json.dumps(chain, ensure_ascii=False, sort_keys=True) != before:
        bad.append("自证(4):重放改了入参 —— 量具不得原地修改证据")
    return bad


# ------------------------------------------------------------------ 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=("docs/evidence/projection_exposure/"
                                      "replay-E1-DSH-H0-window-v11.json"))
    args = ap.parse_args()

    bad = selfcheck()
    if bad:
        print("自证不过,拒绝出数:", file=sys.stderr)
        for b in bad:
            print("  -", b, file=sys.stderr)
        return 3
    print(f"自证通过(4 条);窗口 = {WINDOW_READS},策略 = {WINDOW_POLICY}")

    # 选发:E1 计分行(代 2)× H0 臂(treatment_assigned=false = mini-swe)。
    # 代 1 三发 counts 全 false(GENERATION_ABORTED),天然排除。
    cls_rows = [json.loads(x) for x in
                (REPO / "benchmarks/v2/run_classifications.jsonl")
                .read_text(encoding="utf-8").splitlines() if x.strip()]
    runs_rows = {}
    for x in (REPO / "benchmarks/v2/runs.jsonl").read_text(encoding="utf-8").splitlines():
        if x.strip():
            r = json.loads(x)
            runs_rows[r["run_id"]] = r
    # batch 列过滤:test_mode=E1 还包括 E 轨 8/14 的 t2-offerclaw 消融发,
    # 本脚本的靶只是 DSH 桥接批的 H0 臂(DeepSeek 轨迹)。
    targets = sorted(c["run_id"] for c in cls_rows
                     if c.get("test_mode") == "E1"
                     and c.get("counts_toward_mechanism_effect")
                     and not c.get("treatment_assigned")
                     and runs_rows.get(c["run_id"], {}).get("batch")
                     == "E1-DSH-MINIMAL-BRIDGE-1")
    if len(targets) != 6:
        print(f"H0 计分发应为 6,实际 {len(targets)}:{targets}", file=sys.stderr)
        return 2

    rows = []
    for rid in targets:
        r = replay_run(REPO / "runs" / rid)
        r["model"] = runs_rows.get(rid, {}).get("model", "?")
        rows.append(r)

    align = alignment_audit([REPO / "runs" / rid for rid in targets])

    tot_base = sum(r["est_input_tokens_base"] for r in rows)
    tot_v1 = sum(r["est_input_tokens_v1"] for r in rows)
    tot_v11 = sum(r["est_input_tokens_v11"] for r in rows)
    gate = {
        "every_run_activates_under_v11": all(r["activations_v11"] > 0 for r in rows),
        "zero_activation_runs_v1": [r["run_id"] for r in rows
                                    if r["activations_v1"] == 0],
        "total_saved_pct_v1": round((tot_base - tot_v1) / tot_base * 100, 1),
        "total_saved_pct_v11": round((tot_base - tot_v11) / tot_base * 100, 1),
        "v11_not_worse_anywhere": all(
            r["est_input_tokens_v11"] <= r["est_input_tokens_v1"] for r in rows),
        "offset_mapping_reliable": align["risky_misalignments"] == 0,
    }
    gate["all_pass"] = bool(gate["every_run_activates_under_v11"]
                            and gate["v11_not_worse_anywhere"]
                            and gate["offset_mapping_reliable"])

    doc = {
        "_what": ("window-v1.1 读取分类器的零模型离线重放:E1-DSH 代 2 六发 "
                  "H0(mini-swe×DeepSeek)轨迹,v1/v1.1 对照;口径与在线 "
                  "TokenBudgetedModel 投影同义,token 估算与在线预算执法同尺"),
        "_selfcheck": "4 条合成用例通过(cd 链修后中修前漏/cd+pytest 两边不折/窗口内不折/入参不改)",
        "window_reads": WINDOW_READS,
        "window_policy": WINDOW_POLICY,
        "runs": rows,
        "totals": {"est_input_tokens_base": tot_base,
                   "est_input_tokens_v1": tot_v1,
                   "est_input_tokens_v11": tot_v11},
        "alignment_audit": align,
        "gate": gate,
        "_boundary": ("离线重放只证明送达与量级(激活覆盖 + send 侧输入节省),"
                      "不证明对判决结果的影响方向;v1.1 在线真模型资格发另行请批"),
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"\nH0 计分 {len(rows)} 发:")
    for r in rows:
        print(f"  {r['run_id'][-6:]}  {r['model']:18} 调用 {r['model_calls']:3}  "
              f"激活 v1 {r['activations_v1']:3} → v1.1 {r['activations_v11']:3}  "
              f"省 v1 {r['saved_pct_v1']:5.1f}% → v1.1 {r['saved_pct_v11']:5.1f}%")
    print(f"\n总输入(估):{tot_base:,} → v1 -{gate['total_saved_pct_v1']}% "
          f"→ v1.1 -{gate['total_saved_pct_v11']}%")
    print(f"v1 零激活:{gate['zero_activation_runs_v1'] or '无'}")
    print(f"偏移对齐:{align['verdict']}")
    print(f"门槛:{'全过' if gate['all_pass'] else '未过'}")
    print(f"证据:{out}")
    return 0 if gate["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
