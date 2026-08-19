#!/usr/bin/env python3
"""S2′ 处理暴露的**零模型**离线重放(2026-08-14,用户 Q1-B 的处方)。

为什么要有这个脚本
------------------
批 14 的 gpt-5.6 实验臂 **零激活** —— 处理分配了但一次都没送达。根因是
`_cmd_of` 只取 assistant 动作里的第一条命令,而 gpt-5.6 惯用
`pwd && git status && pytest …` 这种链式写法,于是链上的读取命令被算成了
别的命令,窗口折叠永远命不中。

修 `_cmd_of` 属于**量具修复**,不是执行语义改良。所以按用户处方:修完先
**不调模型**,拿历史 trace 离线重放,看修前/修后的触发覆盖率差多少,人工
抽样确认没有假阳/假阴,再决定要不要花模型额度重跑消融。

口径与在线一致
--------------
在线:`TokenBudgetedModel.query()` 每次调用先投影,`manifest` 里
`folded_messages` 非空就发一条 `projection.applied`。
离线:轨迹里每条 assistant 消息对应一次模型调用,其入参是它**之前**的
消息前缀。逐前缀重放 `project_window`,`folded_messages` 非空即计一次激活。
所以"激活次数"两边同义,可直接对账。

自证
----
与 `exec_metrics.py` 同纪律:脚本先在合成用例上证明自己**看得见**该看见
的、**看不见**不该看见的,否则拒绝出数(退出码 3)。一个量具不先自证,
它报出来的 0 到底是"真没有"还是"我瞎了",没人分得清。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from repoproof.agents.context_projector import (  # noqa: E402
    WINDOW_READS,
    _is_foldable_read,
    _norm_cmd,
    project_window,
)

# ------------------------------------------------------------------ 修前量具
# 修前的 `_cmd_of`:只取 assistant 动作里的**第一条**命令,且遇到前一条
# tool 就断。链式多命令下,tool[k] 会被错配成 actions[0]。
# 原文取自 0cbde37;这里原样保留,只为算"修前覆盖率"。


def _cmd_of_legacy(msgs: list[dict], tool_index: int) -> str:
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


def _project_window_legacy(messages: list[dict], *, window: int = WINDOW_READS):
    """用修前量具跑同一套窗口规则 —— 只换 `_cmd_of`,规则一字不动。"""
    reads = [i for i, m in enumerate(messages)
             if m.get("role") == "tool" and _is_foldable_read(_cmd_of_legacy(messages, i))]
    keep = set(reads[-window:]) if window > 0 else set()
    victims = [i for i in reads if i not in keep]
    return {"folded_messages": len(victims)}


# ------------------------------------------------------------------ 重放
def _model_call_prefixes(messages: list[dict]) -> list[list[dict]]:
    """每条 assistant 消息 = 一次模型调用,其入参是它之前的前缀。"""
    return [messages[:i] for i, m in enumerate(messages)
            if m.get("role") == "assistant"]


def replay_run(run_dir: Path) -> dict:
    """一发的激活统计(修前 / 修后各一份)。"""
    rounds, new_hits, old_hits, calls = 0, 0, 0, 0
    folded_total_new = folded_total_old = 0
    for f in sorted(run_dir.glob("trajectory_round*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        msgs = t.get("messages", t) if isinstance(t, dict) else t
        if not isinstance(msgs, list):
            continue
        rounds += 1
        for prefix in _model_call_prefixes(msgs):
            calls += 1
            _, mf = project_window(prefix)
            n_new = int(mf.get("folded_messages") or 0)
            n_old = _project_window_legacy(prefix)["folded_messages"]
            if n_new:
                new_hits += 1
                folded_total_new += n_new
            if n_old:
                old_hits += 1
                folded_total_old += n_old
    return {"run_id": run_dir.name, "rounds": rounds, "model_calls": calls,
            "activations_new": new_hits, "activations_old": old_hits,
            "folded_msgs_new": folded_total_new, "folded_msgs_old": folded_total_old}


# ------------------------------------------------------------------ 自证
def _msg(role: str, **extra) -> dict:
    return {"role": role, "content": "x" * 400, "extra": extra}


def selfcheck() -> list[str]:
    """合成用例:该看见的看得见,不该看见的看不见。任一条不成立就拒绝出数。"""
    bad: list[str] = []

    # (1) 链式命令 —— 修后必须命中,修前必须漏。这正是批 14 零激活的形状。
    # 分隔样本用 `mkdir -p x`(非读取):v1.1 起 `pwd` 已入读取集
    # (2026-08-20),错配到它也可折,合成用例就失去区分力。
    chain = []
    for _ in range(WINDOW_READS + 3):
        chain.append(_msg("assistant", actions=[{"command": "mkdir -p x"},
                                                {"command": "sed -n '1,50p' a.py"}]))
        chain.append(_msg("tool"))          # ← mkdir 的结果
        chain.append(_msg("tool"))          # ← sed 的结果(修前会被错配成 mkdir)
    _, mf = project_window(chain)
    if not mf.get("folded_messages"):
        bad.append("自证(1):链式命令下修后量具仍未命中 —— 折叠规则或 _cmd_of 有问题")
    if _project_window_legacy(chain)["folded_messages"]:
        bad.append("自证(1'):修前量具竟然命中了 —— 那本脚本算不出修复的差值")

    # (2) 只有执行型命令 —— 两边都必须**不**折叠(假阳侧)
    execs = []
    for _ in range(WINDOW_READS + 3):
        execs.append(_msg("assistant", actions=[{"command": "pytest -q"}]))
        execs.append(_msg("tool"))
    _, mf2 = project_window(execs)
    if mf2.get("folded_messages"):
        bad.append("自证(2):纯执行命令被折叠了 —— 假阳,窗口在吃不该吃的东西")

    # (3) 读取数量在窗口内 —— 不该折叠(边界)
    few = []
    for _ in range(WINDOW_READS):
        few.append(_msg("assistant", actions=[{"command": "cat b.py"}]))
        few.append(_msg("tool"))
    _, mf3 = project_window(few)
    if mf3.get("folded_messages"):
        bad.append("自证(3):窗口内的读取被折叠了 —— 窗口边界算错")

    # (4) 入参不可被改(D1:历史是证据)
    before = json.dumps(chain, ensure_ascii=False, sort_keys=True)
    project_window(chain)
    if json.dumps(chain, ensure_ascii=False, sort_keys=True) != before:
        bad.append("自证(4):重放改了入参 —— 轨迹是证据,量具不得原地修改")
    return bad


# ------------------------------------------------------------------ 抽样
def sample_mappings(run_dir: Path, limit: int = 8) -> list[dict]:
    """人工抽样材料:修前/修后把同一条 tool 结果映射到了哪条命令。

    只列**两者不一致**的,那才是修复真正改变的部分 —— 一致的部分再多也
    说明不了什么。"""
    out: list[dict] = []
    for f in sorted(run_dir.glob("trajectory_round*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        msgs = t.get("messages", t) if isinstance(t, dict) else t
        if not isinstance(msgs, list):
            continue
        from repoproof.agents.context_projector import _cmd_of
        for i, m in enumerate(msgs):
            if m.get("role") != "tool":
                continue
            new, old = _cmd_of(msgs, i), _cmd_of_legacy(msgs, i)
            if new != old:
                out.append({"round": f.name, "msg_index": i,
                            "cmd_old": old[:70], "cmd_new": new[:70],
                            "foldable_old": _is_foldable_read(old),
                            "foldable_new": _is_foldable_read(new)})
            if len(out) >= limit:
                return out
    return out


def alignment_audit(run_dirs: list[Path]) -> dict:
    """假阳/假阴的**唯一系统性风险**:偏移错位。

    修后的 `_cmd_of` 靠"这条 tool 是该 assistant 之后第几条"来选动作。
    只要某个 assistant 的动作数与其后紧邻的 tool 结果数对不上,这个偏移
    就不可靠 —— 会把 A 命令的结果算到 B 命令头上(假阳),或把该折的判成
    不该折(假阴)。所以逐块点数,不靠猜。

    注意 `(n=1, m=0)` 不算风险:那是每轮最后一条提交动作,没有结果记录,
    偏移逻辑根本不经过它。"""
    blocks = aligned = risky = 0
    examples: list[dict] = []
    for d in run_dirs:
        for f in sorted(d.glob("trajectory_round*.json")):
            try:
                msgs = json.loads(f.read_text(encoding="utf-8")).get("messages", [])
            except Exception:
                continue
            i = 0
            while i < len(msgs):
                if msgs[i].get("role") != "assistant":
                    i += 1
                    continue
                n = len(((msgs[i].get("extra") or {}).get("actions")) or [])
                j = i + 1
                while j < len(msgs) and msgs[j].get("role") == "tool":
                    j += 1
                m = j - i - 1
                if n or m:
                    blocks += 1
                    if n == m:
                        aligned += 1
                    elif m > 0:            # 有结果却对不上 → 真风险
                        risky += 1
                        if len(examples) < 8:
                            examples.append({"run": d.name[-6:], "round": f.name,
                                             "msg_index": i, "actions": n, "tools": m})
                i = j
    return {"blocks": blocks, "aligned": aligned,
            "trailing_submit_no_result": blocks - aligned - risky,
            "risky_misalignments": risky, "examples": examples,
            "verdict": "偏移映射可靠(零处可能错位)" if risky == 0
                       else f"有 {risky} 处可能错位 —— 结论不可用"}


# ------------------------------------------------------------------ 主流程
def _arm_of(run_id: str, classifications: dict) -> str:
    c = classifications.get(run_id) or {}
    if not c.get("treatment_assigned"):
        return "A(对照/投影关)"
    return "B(处理/投影开)"


def _model_of(run_id: str, runs: dict) -> str:
    return (runs.get(run_id) or {}).get("model", "?")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/evidence/projection_exposure/replay-E1-S2prime.json")
    ap.add_argument("--test-mode", default="E1", help="只重放该测试模式的发次")
    args = ap.parse_args()

    bad = selfcheck()
    if bad:
        print("自证不过,拒绝出数:", file=sys.stderr)
        for b in bad:
            print("  -", b, file=sys.stderr)
        return 3
    print(f"自证通过(4 条);窗口 = {WINDOW_READS} 条读取")

    cls = {}
    p = REPO / "benchmarks/v2/run_classifications.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            cls[r["run_id"]] = r
    runs = {}
    for line in (REPO / "benchmarks/v2/runs.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            runs[r["run_id"]] = r

    targets = [rid for rid, c in cls.items() if c.get("test_mode") == args.test_mode]
    if not targets:
        print(f"没有 test_mode={args.test_mode} 的发次", file=sys.stderr)
        return 2

    rows = []
    for rid in sorted(targets):
        d = REPO / "runs" / rid
        if not d.is_dir():
            rows.append({"run_id": rid, "error": "证据目录不在"})
            continue
        r = replay_run(d)
        r["arm"] = _arm_of(rid, cls)
        r["model"] = _model_of(rid, runs)
        r["recorded_activated"] = cls[rid].get("treatment_activated")
        rows.append(r)

    # 门槛:只对**处理臂**算(对照臂本就不该有激活)
    treated = [r for r in rows if r.get("arm", "").startswith("B") and "error" not in r]
    nonzero = [r for r in treated if r["activations_new"] > 0]
    cov_new = len(nonzero) / len(treated) if treated else 0.0
    cov_old = (len([r for r in treated if r["activations_old"] > 0]) / len(treated)
               if treated else 0.0)
    by_model: dict[str, dict] = {}
    for r in treated:
        b = by_model.setdefault(r["model"], {"n": 0, "nonzero_new": 0, "nonzero_old": 0})
        b["n"] += 1
        b["nonzero_new"] += 1 if r["activations_new"] > 0 else 0
        b["nonzero_old"] += 1 if r["activations_old"] > 0 else 0

    # 对照臂必须零激活 —— 它们跑的时候投影是关的,离线重放却是"若开会怎样"。
    # 所以这里不是断言,是**记录**:对照臂的离线激活数说明"处理若送达会有多少"。
    control = [r for r in rows if r.get("arm", "").startswith("A") and "error" not in r]

    gate = {
        "threshold_coverage": 0.5,
        "threshold_every_cell_nonzero": True,
        "coverage_new": round(cov_new, 4),
        "coverage_old": round(cov_old, 4),
        "coverage_passes": cov_new >= 0.5,
        "every_model_cell_nonzero": all(v["nonzero_new"] > 0 for v in by_model.values()),
    }
    gate["all_pass"] = bool(gate["coverage_passes"] and gate["every_model_cell_nonzero"])

    samples = {}
    for r in treated:
        s = sample_mappings(REPO / "runs" / r["run_id"], limit=4)
        if s:
            samples[r["run_id"]] = s

    align = alignment_audit([REPO / "runs" / r["run_id"] for r in rows if "error" not in r])
    gate["offset_mapping_reliable"] = align["risky_misalignments"] == 0
    gate["all_pass"] = bool(gate["all_pass"] and gate["offset_mapping_reliable"])

    doc = {
        "_what": "S2′ 处理暴露的零模型离线重放;口径与在线 projection.applied 同义",
        "alignment_audit": align,
        "_selfcheck": "4 条合成用例通过(链式命中/纯执行不折/窗口内不折/入参不改)",
        "window_reads": WINDOW_READS,
        "test_mode": args.test_mode,
        "runs": rows,
        "by_model_treated": by_model,
        "control_arm_offline_activation": [
            {"run_id": r["run_id"], "model": r["model"],
             "activations_if_treated": r["activations_new"]} for r in control],
        "gate": gate,
        "manual_sampling": samples,
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n处理臂 {len(treated)} 发:")
    for r in sorted(treated, key=lambda x: x["run_id"]):
        print(f"  {r['run_id'][-6:]}  {r['model']:9} 调用 {r['model_calls']:3}  "
              f"激活 修前 {r['activations_old']:3} → 修后 {r['activations_new']:3}"
              f"   台账记的 activated={r['recorded_activated']}")
    print(f"\n非零覆盖率:修前 {cov_old:.0%} → 修后 {cov_new:.0%}(门槛 ≥50%)")
    for m, v in sorted(by_model.items()):
        print(f"  {m:10} 非零 {v['nonzero_new']}/{v['n']}(修前 {v['nonzero_old']}/{v['n']})")
    print(f"\n偏移对齐审计:{align['blocks']} 块,对齐 {align['aligned']},"
          f"末条提交无结果 {align['trailing_submit_no_result']},"
          f"可能错位 {align['risky_misalignments']} → {align['verdict']}")
    print(f"\n门槛:{'全过' if gate['all_pass'] else '未过'} → "
          f"{'可进入在线模型消融' if gate['all_pass'] else '正式终止 S2′,不再调用模型'}")
    print(f"证据:{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
