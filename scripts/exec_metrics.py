"""执行器效率量化(S0 基线;模式 E0)—— 只测量,不改任何行为。

回答的问题:**当前执行器(E0)到底浪费在哪、浪费多少**。没有这份基线,
S2 上线后看到 token 下降也证明不了是新机制带来的(EXECUTOR-UPGRADE-PLAN §3-S0)。

取数点全部在 run bundle 内,可逐条指回消息序号(判据 M2):

    trajectory_round<N>.json
      messages[i].role == "assistant"
        .extra.response.usage.prompt_tokens      ← 该次调用的真实输入(provider 报的)
        .extra.response.usage.completion_tokens
        .extra.response.usage.prompt_tokens_details.cached_tokens  ← 前缀缓存命中
        .extra.actions[].command                 ← 该次调用发出的命令
      messages[i].role == "tool"
        .content                                 ← 模型**实际看到**的(可能已被 clip)
        .extra.raw_output                        ← 注意:**也是截断后的**,见下

**两个假设我都踩过,记在这里免得再踩**(2026-08-14 实录):

1. **clip 只能按标记解析,不能按长度比**。`content` 外面包着
   `<returncode>…</returncode><output>…</output>`,实测 raw 7758 字符对应
   seen 7803 —— 看着"变长了",按长度比会判"没截断"。
2. **`extra.raw_output` 不是未截断原文**。实测某条标记称原文 35,289 字符、
   丢 27,689,而同条 `raw_output` 只有 7,758(= obs_cap 后的大小)。原文只在
   run artifact 里。**故"整文件读"的大小必须从标记的 `of M chars` 取**,
   用 `len(raw_output)` 判会因永远够不到阈值而恒报 0。

两处都是自证用例抓出来的 —— 三项指标首跑全零时,我差点把"没测出来"当成
"没发生"(与 batch_criteria / mutation_gate 的自证同源纪律)。

**重复输入怎么算(本脚本的核心定义,冻结)**:
E0 每轮重发完整历史,故第 k 次调用的输入 ⊇ 第 k-1 次的输入。已实测两发
`prompt_tokens` 严格单调递增(telescoping 成立),于是:

    unique_input   = max(prompt_tokens)      # 最后一次调用即含全部唯一内容
    repeated_input = sum(prompt_tokens) - unique_input
    repeated_ratio = repeated_input / sum(prompt_tokens)

若某发**不单调**(出现回落,说明有裁剪/丢弃),`monotonic` 标 false,
`unique_input` 退化为 max 仍成立但会**低估**唯一量、**高估**重复率 ——
此时结论只能说"重复率至多 X",脚本会在输出里标注,不得当成精确值。

用法:
    .venv/bin/python scripts/exec_metrics.py runs/t2-*v5-2026* runs/t3-*v6-*
    .venv/bin/python scripts/exec_metrics.py --all --out docs/evidence/exec_metrics/baseline-E0.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 单条工具输出超过这个字符数,记一次"整文件读"形态。20k 字符 ≈ 5k token,
# 是"目标化读取(sed -n)"与"整文件 cat"的经验分界;阈值随输出一起记录,
# 换阈值必须重跑全部对象,不得只对新发次换。
WHOLE_FILE_CHARS = 20_000

# 同一规范化命令出现 ≥ 这个次数,计入"重复命令"。与 S3 的治理阈值(3/5/8)
# 对齐,便于 S3 上线后直接对比。
REPEAT_MIN = 3

# clip_observation 插入的截断标记(src/repoproof/agents/repoproof_env.py)。
# 改那边就要改这里 —— 自证用例 `selfcheck` 会先证明本正则确实能命中。
_CLIP_RE = re.compile(r"\[\.\.\.RepoProof obs-cap: (\d+) of (\d+) chars omitted\.")


def _norm_cmd(cmd: str) -> str:
    """命令规范化:压空白、去尾分号。不做语义归一 —— 宁可少算不可多算。"""
    return re.sub(r"\s+", " ", (cmd or "").strip()).rstrip(";").strip()


def _usage(msg: dict) -> dict:
    return (((msg.get("extra") or {}).get("response") or {}).get("usage") or {})


def round_metrics(traj: dict) -> dict:
    """单轮(一次 agent 会话)的指标。所有列表项都带 msg_index,可复核。"""
    msgs = traj.get("messages") or []
    calls: list[dict] = []
    tools: list[dict] = []

    for i, m in enumerate(msgs):
        role = m.get("role")
        if role == "assistant":
            u = _usage(m)
            if not u.get("prompt_tokens"):
                continue
            det = u.get("prompt_tokens_details") or {}
            cmds = [a.get("command", "") for a in ((m.get("extra") or {}).get("actions") or [])]
            calls.append({
                "msg_index": i,
                "prompt_tokens": u["prompt_tokens"],
                "completion_tokens": u.get("completion_tokens") or 0,
                "cached_tokens": (det.get("cached_tokens") or 0) if isinstance(det, dict) else 0,
                "commands": cmds,
            })
        elif role == "tool":
            raw = (m.get("extra") or {}).get("raw_output")
            seen = m.get("content") or ""
            hit = _CLIP_RE.search(seen)
            stored = len(raw) if isinstance(raw, str) else len(seen)
            tools.append({
                "msg_index": i,
                # 原文大小:截断了就信标记的 `of M chars`,没截断才用落盘长度
                "orig_chars": int(hit.group(2)) if hit else stored,
                "stored_chars": stored,
                "clipped_chars": int(hit.group(1)) if hit else 0,
            })

    pt = [c["prompt_tokens"] for c in calls]
    if not pt:
        return {"calls": 0, "note": "本轮无带 usage 的调用 —— 无法计量"}

    monotonic = all(pt[i] <= pt[i + 1] for i in range(len(pt) - 1))
    total_in = sum(pt)
    unique_in = max(pt)
    repeated = total_in - unique_in

    # 整文件读 + 被 clip 丢弃(且**不可回读**,这正是 E0 的缺陷)
    big = [t for t in tools if t["orig_chars"] >= WHOLE_FILE_CHARS]
    clipped = [t for t in tools if t["clipped_chars"] > 0]
    dropped_chars = sum(t["clipped_chars"] for t in clipped)

    # 重复命令
    freq: dict[str, list[int]] = {}
    for c in calls:
        for cmd in c["commands"]:
            freq.setdefault(_norm_cmd(cmd), []).append(c["msg_index"])
    repeats = {k: v for k, v in freq.items() if len(v) >= REPEAT_MIN and k}

    return {
        "calls": len(calls),
        "monotonic": monotonic,
        "input_tokens_total": total_in,
        "input_tokens_unique": unique_in,
        "input_tokens_repeated": repeated,
        "repeated_ratio": round(repeated / total_in, 4),
        "repeated_ratio_is_upper_bound": not monotonic,
        "per_call_input": {
            "median": int(statistics.median(pt)),
            "p95": int(sorted(pt)[max(0, int(len(pt) * 0.95) - 1)]),
            "max": max(pt), "min": min(pt),
        },
        "output_tokens_total": sum(c["completion_tokens"] for c in calls),
        "cached_tokens_total": sum(c["cached_tokens"] for c in calls),
        "cache_hit_ratio": round(sum(c["cached_tokens"] for c in calls) / total_in, 4),
        "tool_results": len(tools),
        "whole_file_reads": {
            "count": len(big),
            "threshold_chars": WHOLE_FILE_CHARS,
            "msg_indices": [t["msg_index"] for t in big],
            "note": "大小取自 clip 标记的原文值,不是落盘长度(raw_output 已被截断)",
        },
        "clip_loss": {
            "clipped_results": len(clipped),
            "dropped_chars": dropped_chars,
            "note": "E0 下被丢弃的中段**不可回读**;S2 的 spill 应把它降到 0",
        },
        "repeated_commands": {
            "distinct": len(repeats),
            "total_extra_calls": sum(len(v) - 1 for v in repeats.values()),
            "top": sorted(({"command": k, "times": len(v), "msg_indices": v}
                           for k, v in repeats.items()),
                          key=lambda d: -d["times"])[:5],
        },
    }


# ---------------------------------------------------------------- 靶子扫描
# S3/S4/S5 是**条件立项**:指导文档明写"只有在对应失败形态仍存在时再做,
# 不一次性全部堆上"。S2 的教训就是我先造机制、后验前提 —— 三条折叠规则
# 全部以"命令重复"为前提,而 S0 早已报了"重复命令全 0"。
#
# 故每一步动手前先在真实轨迹上量它的靶子。下面每个计数器都对应文档里
# 那一步声称要治的失败形态;计数为 0 = 该步在当前证据下无靶子。

# S3:持久 shell 要治"状态不连续" —— 表现为反复重建 cwd/环境
_S3_CD = re.compile(r"(^|[;&|]\s*)cd\s", re.M)
_S3_PATH_ERR = re.compile(r"No such file or directory|not a directory", re.I)

# S4:结构化编辑器要治"用 bash 改文件很脆" —— 表现为写文件命令失败/整文件重写
_SRC_EXT = r"(py|txt|toml|cfg|yaml|yml|json|md)"
_S4_EDIT = re.compile(
    r"<<\s*'?[A-Z_]+'?"          # heredoc(cat > f <<EOF 型)
    r"|sed -i|tee\s"             # 原地改 / 写入
    rf"|>>?\s*\S+\.{_SRC_EXT}"  # 重定向写源码文件
)
_S4_WHOLE_WRITE = re.compile(r"cat\s*>\s*\S+\s*<<")

# S5:契约胶囊/需求状态板要治"需求遗漏"与"语义替代" —— 前者看提交时公开
# 测试是否仍红,后者看裁定表(AR 模式的产物,不是本扫描能判的,单独列)
_S5_PUBLIC_RUN = re.compile(r"pytest|public_tests")


def scan_targets(traj: dict) -> dict:
    """单轮的 S3/S4/S5 靶子计数。每项都能指回消息序号。"""
    msgs = traj.get("messages") or []
    cds = path_errs = edits = edit_fails = whole_writes = public_runs = 0
    last_public_run_at = -1
    cwds: set[str] = set()
    for i, m in enumerate(msgs):
        if m.get("role") == "assistant":
            for a in ((m.get("extra") or {}).get("actions") or []):
                cmd = a.get("command", "") or ""
                if _S3_CD.search(cmd):
                    cds += 1
                if _S4_EDIT.search(cmd):
                    edits += 1
                if _S4_WHOLE_WRITE.search(cmd):
                    whole_writes += 1
                if _S5_PUBLIC_RUN.search(cmd):
                    public_runs += 1
                    last_public_run_at = i
        elif m.get("role") == "tool":
            extra = m.get("extra") or {}
            rc = extra.get("returncode")
            body = m.get("content") or ""
            if extra.get("cwd"):
                cwds.add(str(extra["cwd"]))
            if _S3_PATH_ERR.search(body):
                path_errs += 1
            if rc not in (0, None):
                # 这条工具结果对应的命令是不是编辑型?回看前一条 assistant
                for j in range(i - 1, -1, -1):
                    if msgs[j].get("role") == "assistant":
                        cmds = " ".join(a.get("command", "") for a
                                        in ((msgs[j].get("extra") or {}).get("actions") or []))
                        if _S4_EDIT.search(cmds):
                            edit_fails += 1
                        break
    return {
        "s3_cd_commands": cds,
        "s3_path_errors": path_errs,
        "s3_distinct_cwds": len(cwds),
        "s4_edit_commands": edits,
        "s4_edit_failures": edit_fails,
        "s4_whole_file_writes": whole_writes,
        "s5_public_test_runs": public_runs,
        "s5_last_public_run_msg": last_public_run_at,
        "s5_messages": len(msgs),
    }


def selfcheck() -> list[str]:
    """自证:喂一份**每个指标都该报警**的合成轨迹,报不出来就没资格发零。

    动机(2026-08-14 实录):首次跑真实 bundle,整文件读/丢弃字符/重复命令
    三项**全零**。其中两项是真的(输出最大 7.8k、命令确实无重复),第三项
    是 bug —— 我用 `raw > seen` 判截断,而 content 外面包了 returncode/output
    标记,长度比根本不成立。**零值必须先由自证背书**,否则分不清"没发生"
    和"没测出来"(与 batch_criteria.py / mutation_gate 的自证同源)。"""
    omitted = 12345
    traj = {"messages": [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
        # 调用 1:小输入
        {"role": "assistant", "extra": {
            "response": {"usage": {"prompt_tokens": 100, "completion_tokens": 5}},
            "actions": [{"command": "ls -la"}]}},
        {"role": "tool", "content": "ok", "extra": {"raw_output": "ok"}},
        # 调用 2:输入涨(制造重复)+ 整文件读 + 被 clip
        {"role": "assistant", "extra": {
            "response": {"usage": {"prompt_tokens": 300, "completion_tokens": 5,
                                   "prompt_tokens_details": {"cached_tokens": 80}}},
            "actions": [{"command": "ls  -la ;"}]}},          # 规范化后与上同
        # 真实形状:原文 99999 字符,clip 后落盘只剩 short —— 整文件读必须
        # 从标记的 99999 判出来,用 len(raw_output) 判会漏(实录缺陷)
        {"role": "tool",
         "content": f"head[...RepoProof obs-cap: {omitted} of 99999 chars omitted. x]tail",
         "extra": {"raw_output": "S" * 7758}},
        # 调用 3:同命令第三次 → 触发 REPEAT_MIN
        {"role": "assistant", "extra": {
            "response": {"usage": {"prompt_tokens": 600, "completion_tokens": 5}},
            "actions": [{"command": "ls -la"}]}},
        {"role": "tool", "content": "ok", "extra": {"raw_output": "ok"}},
    ]}
    r = round_metrics(traj)
    problems = []
    if r["calls"] != 3:
        problems.append(f"调用数应为 3,实得 {r['calls']}")
    if not r["monotonic"]:
        problems.append("合成数据是单调的,却判成非单调")
    # 总 1000,unique 600 → 重复 400
    if r["input_tokens_repeated"] != 400:
        problems.append(f"重复输入应为 400,实得 {r['input_tokens_repeated']}")
    if r["whole_file_reads"]["count"] != 1:
        problems.append(f"整文件读应为 1,实得 {r['whole_file_reads']['count']} "
                        "—— 原文大小取错了:clip 后 raw_output 只剩 7758 字符,"
                        "必须从标记的 `of 99999 chars` 判")
    if r["clip_loss"]["dropped_chars"] != omitted:
        problems.append(f"丢弃字符应为 {omitted},实得 {r['clip_loss']['dropped_chars']} "
                        "—— clip 标记正则与 repoproof_env.py 脱节")
    if r["repeated_commands"]["distinct"] != 1:
        problems.append("`ls -la` / `ls  -la ;` / `ls -la` 应归并为 1 条重复命令 "
                        f"—— 实得 {r['repeated_commands']['distinct']} 条")
    if r["cached_tokens_total"] != 80:
        problems.append(f"缓存 token 应为 80,实得 {r['cached_tokens_total']}")
    return problems


def run_metrics(bundle: Path) -> dict:
    """一发的指标 = 各轮之和 + 与台账对账(判据 M1)。"""
    rounds = sorted(bundle.glob("trajectory_round*.json"),
                    key=lambda p: int(re.search(r"(\d+)", p.name).group(1)))
    per_round = []
    for p in rounds:
        try:
            traj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            per_round.append({"file": p.name, "error": str(exc)})
            continue
        r = round_metrics(traj)
        r["file"] = p.name
        per_round.append(r)

    ok = [r for r in per_round if r.get("calls")]
    agg = {
        "rounds": len(per_round),
        "calls": sum(r["calls"] for r in ok),
        "input_tokens_total": sum(r["input_tokens_total"] for r in ok),
        "input_tokens_repeated": sum(r["input_tokens_repeated"] for r in ok),
        "output_tokens_total": sum(r["output_tokens_total"] for r in ok),
        "cached_tokens_total": sum(r["cached_tokens_total"] for r in ok),
        "whole_file_reads": sum(r["whole_file_reads"]["count"] for r in ok),
        "clip_dropped_chars": sum(r["clip_loss"]["dropped_chars"] for r in ok),
        "repeated_command_extra_calls": sum(
            r["repeated_commands"]["total_extra_calls"] for r in ok),
    }
    if agg["input_tokens_total"]:
        agg["repeated_ratio"] = round(
            agg["input_tokens_repeated"] / agg["input_tokens_total"], 4)
        agg["cache_hit_ratio"] = round(
            agg["cached_tokens_total"] / agg["input_tokens_total"], 4)
    return {"bundle": bundle.name, "per_round": per_round, "aggregate": agg}


def reconcile(results: list[dict], ledger: Path) -> list[dict]:
    """判据 M1:重构的累计输入必须与台账 input_tokens 对得上(≤10%)。

    对不上就是取数点错了 —— 宁可报红也不能拿错数当基线。"""
    by_run = {}
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                by_run[r.get("run_id")] = r
    out = []
    for res in results:
        led = by_run.get(res["bundle"])
        got = res["aggregate"].get("input_tokens_total", 0)
        want = led.get("input_tokens") if led else None
        entry = {"bundle": res["bundle"], "computed": got, "ledger": want}
        if isinstance(want, int) and want > 0:
            dev = abs(got - want) / want
            entry["deviation_pct"] = round(dev * 100, 2)
            entry["m1_pass"] = dev <= 0.10
        else:
            entry["m1_pass"] = None
            entry["note"] = "台账无该发或无 input_tokens —— 无法对账"
        out.append(entry)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundles", nargs="*", type=Path, help="run bundle 目录")
    ap.add_argument("--all", action="store_true", help="扫 runs/ 下全部 bundle")
    ap.add_argument("--out", type=Path, default=None, help="结果 JSON 落盘位置")
    ap.add_argument("--ledger", type=Path,
                    default=REPO / "benchmarks" / "v2" / "runs.jsonl")
    args = ap.parse_args(argv)

    targets = list(args.bundles)
    if args.all:
        targets = sorted(p for p in (REPO / "runs").iterdir()
                         if p.is_dir() and list(p.glob("trajectory_round*.json")))
    # 自证先行:量具证明自己查得出,才有资格对真实数据发零
    problems = selfcheck()
    if problems:
        print("自证失败 —— 量具本身坏了,拒绝出基线:", file=sys.stderr)
        for p in problems:
            print(f"  ✗ {p}", file=sys.stderr)
        return 3
    print("自证通过(四项指标在合成缺陷上全部报警)\n")

    targets = [p for p in targets if p.is_dir()]
    if not targets:
        print("没有可计量的 bundle(需含 trajectory_round*.json)", file=sys.stderr)
        return 2

    results = [run_metrics(p) for p in targets]
    checks = reconcile(results, args.ledger)

    print(f"{'bundle':<46}{'调用':>5}{'累计输入':>11}{'重复率':>8}"
          f"{'缓存率':>8}{'整文件':>7}{'丢弃字符':>10}{'重复命令':>9}")
    for res in results:
        a = res["aggregate"]
        print(f"{res['bundle'][:45]:<46}{a['calls']:>5}{a['input_tokens_total']:>11,}"
              f"{a.get('repeated_ratio', 0):>8.1%}{a.get('cache_hit_ratio', 0):>8.1%}"
              f"{a['whole_file_reads']:>7}{a['clip_dropped_chars']:>10,}"
              f"{a['repeated_command_extra_calls']:>9}")

    print(f"\n{'M1 对账(重构 vs 台账)':<46}{'重构':>11}{'台账':>11}{'偏差':>8}")
    bad = []
    for c in checks:
        mark = "✓" if c["m1_pass"] else ("—" if c["m1_pass"] is None else "✗")
        dev = f"{c.get('deviation_pct', 0):.2f}%" if "deviation_pct" in c else "n/a"
        led = f"{c['ledger']:,}" if isinstance(c["ledger"], int) else "无"
        print(f"{mark} {c['bundle'][:44]:<44}{c['computed']:>11,}{led:>11}{dev:>8}")
        if c["m1_pass"] is False:
            bad.append(c["bundle"])

    nonmono = [r["file"] for res in results for r in res["per_round"]
               if r.get("calls") and not r.get("monotonic")]
    if nonmono:
        print(f"\n注意:{len(nonmono)} 轮非单调 —— 这些轮的重复率是**上界**不是精确值")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(
            {"exec_generation": "E0", "whole_file_threshold_chars": WHOLE_FILE_CHARS,
             "repeat_min": REPEAT_MIN, "runs": results, "m1_reconciliation": checks},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n结果 → {args.out}")

    if bad:
        print(f"\nM1 未通过:{', '.join(bad)} —— 取数点有误,不得当基线用")
        return 1
    print("\nM1 全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
