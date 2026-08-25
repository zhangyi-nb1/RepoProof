#!/usr/bin/env python
"""DQ:deepseek-native 三条 canary(TESTPLAN §11 DQ 模式;§11.5 停规)。

Provider 资格测试 —— 三条 canary 全部走**真适配器栈**
(DeepSeekNativeModel → litellm deepseek/ 路由 → 官方 API),不是裸
HTTP:DQ 问的是"协议经过我们的栈是否按官方语义跑"。canary 非任务,
不计模型表现;逐 profile × 逐 canary 记格,**未 100% 通过 → 该记
PROVIDER_PROTOCOL_FAILURE,不进入任务 benchmark**。

  C1 单轮工具:一发问一发 tool_call,动作可解析、usage 同步可读
     (TokenBudgetedModel 契约点:extra.response.usage 双向 > 0)
  C2 多轮 reasoning passback:完整工具循环 ≤N 轮,逐轮按 profile 旋钮
     回传 reasoning_content,全部请求被官方接受、循环以非空正文收束;
     逐轮**记录**思考链在场与否(记录,不设门)
  C3 长 observation:一条 8000 字符(= 生产 obs_cap)的工具观察 +
     末尾针语句,最终正文必须逐字复述针值 —— 只"接受"不算数,
     内容必须真的被送达

安全面:canary **零执行面** —— 模型给的命令一律不执行,观察为字面
模拟(echo 前缀取字面,其余固定占位),证据里 simulated=true 自曝。
秘密面:key 只走 env;证据里 api_base 只以 redacted summary 出现。

用法:
  dq_deepseek_canaries.py [--profile P ...] [--smoke] [--out DIR]
                          [--max-rounds 4] [--max-tokens 4000]

--smoke = 预注册冻结前的工程调试(run_kind=ENGINEERING_SMOKE,证据落
/tmp,不算 DQ);不带 --smoke = DQ_RECORD 正式取证。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

NEEDLE_PREFIX = "DQ_C3_NEEDLE_VALUE="
OBS_CAP_CHARS = 8000  # 与生产 obs_cap() 默认一致(修订④)


# ---------------------------------------------------------------- 纯函数(可钉)


def simulate_echo_output(command: str) -> dict:
    """观察模拟:不执行模型命令(canary 无沙箱,执行面必须为零)。
    echo 前缀取字面回显;其余命令给定占位。证据 simulated=true 自曝。"""
    text = (command or "").strip()
    if text.startswith("echo "):
        payload = text[5:].strip()
        if len(payload) >= 2 and payload[0] == payload[-1] and payload[0] in "'\"":
            payload = payload[1:-1]
        out = payload + "\n"
    else:
        out = f"[simulated observation for: {text[:60]}]\n"
    return {"output": out, "returncode": 0, "exception_info": ""}


def build_long_observation(needle_token: str, total_chars: int = OBS_CAP_CHARS) -> str:
    """结构化填充 + 末尾针语句,总长精确 total_chars。"""
    needle_line = f"{NEEDLE_PREFIX}{needle_token}\n"
    filler_line = "log entry: routine subsystem heartbeat, nothing notable here.\n"
    body: list[str] = []
    used = len(needle_line)
    while used + len(filler_line) <= total_chars:
        body.append(filler_line)
        used += len(filler_line)
    pad = total_chars - used
    blob = "".join(body) + ("." * pad if pad else "")
    # 末尾放针(截断攻击面在尾部最敏感)
    return blob[: total_chars - len(needle_line)] + needle_line


def dq_verdict(cells: list[dict], expected_cells: int) -> dict:
    """§11.5:全格 PASS 才 PASS;缺格 = 没考完,同样不算过。"""
    passed = sum(1 for c in cells if c.get("status") == "PASS")
    ok = passed == expected_cells and len(cells) == expected_cells
    return {
        "dq_status": "PASS" if ok else "PROVIDER_PROTOCOL_FAILURE",
        "cells_expected": expected_cells,
        "cells_run": len(cells),
        "cells_passed": passed,
        "failed_cells": [
            {"profile": c.get("profile"), "canary": c.get("canary"),
             "reason": c.get("reason", "")}
            for c in cells if c.get("status") != "PASS"
        ],
    }


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _digest_text(text: str | None, head: int = 400) -> dict:
    t = text or ""
    return {"head": t[:head], "chars": len(t), "sha256": _sha(t) if t else None}


def digest_message(msg: dict) -> dict:
    """转录摘要:内容头部 + 长度 + sha;思考链在场与否;工具调用形状。
    绝不落 key/base;正文全量不落盘(答案零入库纪律的同族习惯)。"""
    tool_calls = msg.get("tool_calls") or []
    return {
        "role": msg.get("role"),
        "content": _digest_text(msg.get("content")),
        "reasoning_present": bool(msg.get("reasoning_content")),
        "reasoning": _digest_text(msg.get("reasoning_content"), head=200),
        "tool_calls": [
            {"id": tc.get("id"),
             "name": (tc.get("function") or {}).get("name"),
             "arguments_head": ((tc.get("function") or {}).get("arguments") or "")[:200]}
            for tc in tool_calls
        ],
        "finish_hint": msg.get("finish_reason"),
    }


# ---------------------------------------------------------------- canary 本体


def _typed_exc(exc: Exception) -> str:
    """异常 → 证据字符串。FormatError 的 str() 为空(它背的是消息 dict),
    取其首条消息 content 头部,病名才有肉。"""
    detail = str(exc)[:200]
    msgs = getattr(exc, "messages", None)
    if not detail and msgs:
        detail = str((msgs[0] or {}).get("content", ""))[:200]
    return f"{type(exc).__name__}: {detail}"


def _usage_of(message: dict) -> tuple[int, int]:
    usage = ((message.get("extra") or {}).get("response") or {}).get("usage") or {}
    return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


def _actions_of(message: dict) -> list[dict]:
    return (message.get("extra") or {}).get("actions") or []


def _query(model, messages: list[dict], max_tokens: int) -> dict:
    return model.query(messages, max_tokens=max_tokens)


def canary1_single_tool(model, max_tokens: int) -> dict:
    t0 = time.monotonic()
    messages = [
        {"role": "system", "content": "You are a protocol probe. Use the bash tool for any command."},
        {"role": "user", "content": "Run exactly this command: echo DQ_C1_OK"},
    ]
    msg = _query(model, messages, max_tokens)
    tin, tout = _usage_of(msg)
    actions = _actions_of(msg)
    checks = {
        "action_parsed": bool(actions),
        "command_echoes_token": any("DQ_C1_OK" in a.get("command", "") for a in actions),
        "usage_prompt_positive": tin > 0,
        "usage_completion_positive": tout > 0,
    }
    ok = all(checks.values())
    return {
        "canary": "C1-single-tool", "status": "PASS" if ok else "FAIL",
        "reason": "" if ok else f"checks={checks}",
        "checks": checks, "usage": {"in": tin, "out": tout},
        "wall_s": round(time.monotonic() - t0, 1),
        "transcript": [digest_message(msg)],
    }


def canary2_multiturn_passback(model, max_tokens: int, max_rounds: int) -> dict:
    """全工具轮设计:mini 协议里**每轮都必须是 tool_call**(无 tool_call
    即 FormatError,生产同款)。收尾也走工具(`echo DQ_C2_DONE`),
    不与栈协议打架 —— 首轮冒烟实测教训。"""
    t0 = time.monotonic()
    messages = [
        {"role": "system", "content": (
            "You are a protocol probe. You MUST use the bash tool on every "
            "turn. One command per step."
        )},
        {"role": "user", "content": (
            "Step 1: run `echo DQ_C2_STEP1`. After you see its output, "
            "step 2: run `echo DQ_C2_STEP2`. After you see that output, "
            "step 3: run `echo DQ_C2_DONE`."
        )},
    ]
    transcript: list[dict] = []
    rounds = 0
    tool_rounds = 0
    reasoning_rounds = 0
    done_seen = False
    reason = ""
    usage_total = [0, 0]
    try:
        while rounds < max_rounds:
            rounds += 1
            msg = _query(model, messages, max_tokens)
            tin, tout = _usage_of(msg)
            usage_total[0] += tin
            usage_total[1] += tout
            transcript.append(digest_message(msg))
            actions = _actions_of(msg)
            if msg.get("reasoning_content"):
                reasoning_rounds += 1
            messages.append(msg)  # 原样入列(含 extra;上行前适配器剥)
            tool_rounds += 1
            if any("DQ_C2_DONE" in a.get("command", "") for a in actions):
                done_seen = True
                break
            outputs = [simulate_echo_output(a.get("command", "")) for a in actions]
            messages.extend(model.format_observation_messages(msg, outputs, {}))
        else:
            reason = f"DONE step not reached within {max_rounds} rounds"
    except Exception as exc:  # noqa: BLE001 —— 协议被拒即 FAIL,形状入证据
        reason = _typed_exc(exc)
    checks = {
        "multi_round_tool_loop": tool_rounds >= 2,
        "done_step_reached": done_seen,
        "no_protocol_error": reason == "",
    }
    ok = all(checks.values())
    return {
        "canary": "C2-multiturn-reasoning-passback",
        "status": "PASS" if ok else "FAIL",
        "reason": reason or ("" if ok else f"checks={checks}"),
        "checks": checks,
        "rounds": rounds, "tool_rounds": tool_rounds,
        "reasoning_rounds_observed": reasoning_rounds,  # 记录,不设门
        "usage": {"in": usage_total[0], "out": usage_total[1]},
        "wall_s": round(time.monotonic() - t0, 1),
        "transcript": transcript,
    }


def canary3_long_observation(model, max_tokens: int, needle_token: str) -> dict:
    """全工具轮设计(同 C2 教训):第 2 轮以 `echo REPORT:<token>` 工具
    调用复述针值 —— 送达判定看动作参数,不要求裸文本轮。"""
    t0 = time.monotonic()
    messages = [
        {"role": "system", "content": (
            "You are a protocol probe. You MUST use the bash tool on every turn."
        )},
        {"role": "user", "content": (
            "Run `cat service.log` with the bash tool. The output ends with a line "
            f"`{NEEDLE_PREFIX}<token>`. Then report it by running exactly: "
            "`echo REPORT:<token>` (substituting the token you saw)."
        )},
    ]
    transcript: list[dict] = []
    reason = ""
    report_commands: list[str] = []
    obs_meta: dict = {}
    usage_total = [0, 0]
    try:
        msg = _query(model, messages, max_tokens)
        tin, tout = _usage_of(msg)
        usage_total[0] += tin
        usage_total[1] += tout
        transcript.append(digest_message(msg))
        actions = _actions_of(msg)
        if not actions:
            reason = "no tool call in round 1"
        else:
            blob = build_long_observation(needle_token)
            obs_meta = {"chars": len(blob), "sha256": _sha(blob), "simulated": True}
            outputs = [{"output": blob, "returncode": 0, "exception_info": ""}]
            # 只喂第一个动作的观察;多动作时其余给占位(canary 形状固定)
            outputs += [simulate_echo_output(a.get("command", "")) for a in actions[1:]]
            messages.append(msg)
            messages.extend(model.format_observation_messages(msg, outputs, {}))
            msg2 = _query(model, messages, max_tokens)
            tin2, tout2 = _usage_of(msg2)
            usage_total[0] += tin2
            usage_total[1] += tout2
            transcript.append(digest_message(msg2))
            report_commands = [a.get("command", "") for a in _actions_of(msg2)]
    except Exception as exc:  # noqa: BLE001
        reason = _typed_exc(exc)
    checks = {
        "tool_call_round1": reason != "no tool call in round 1" and reason == "",
        "needle_echoed_verbatim": any(needle_token in c for c in report_commands),
    }
    ok = all(checks.values())
    return {
        "canary": "C3-long-observation",
        "status": "PASS" if ok else "FAIL",
        "reason": reason or (
            "" if ok else f"needle missing; round2_commands={report_commands[:2]!r}"),
        "checks": checks, "observation": obs_meta,
        "usage": {"in": usage_total[0], "out": usage_total[1]},
        "wall_s": round(time.monotonic() - t0, 1),
        "transcript": transcript,
    }


# ---------------------------------------------------------------- 编排


def run_profile(profile_name: str, *, base: str, key: str, model_name: str,
                max_tokens: int, max_rounds: int, call_timeout_s: float) -> dict:
    from repoproof.agents.deepseek_native import (
        DeepSeekNativeModel,
        build_deepseek_provider,
        build_model_kwargs,
    )
    from repoproof.agents.provider_gate import run_preflight

    provider = build_deepseek_provider(
        profile=profile_name, api_base=base, api_key=key, model_name=model_name)
    os.environ["DEEPSEEK_API_KEY"] = provider.api_key
    os.environ["DEEPSEEK_API_BASE"] = provider.api_base
    pre = run_preflight(provider)
    out: dict = {
        "profile": profile_name,
        "provider_config_sha256": provider.config_sha256,
        "preflight": pre.summary(),
        "canaries": [],
    }
    if not pre.ready:
        # preflight 不过:三格全 FAIL(带 preflight 的 typed status)
        for cname in ("C1-single-tool", "C2-multiturn-reasoning-passback",
                      "C3-long-observation"):
            out["canaries"].append({
                "canary": cname, "status": "FAIL",
                "reason": f"preflight {pre.status}", "profile": profile_name})
        return out

    model = DeepSeekNativeModel(
        model_name=f"deepseek/{provider.model_name}",
        model_kwargs=build_model_kwargs(provider, call_timeout_s),
        reasoning_passback=provider.reasoning_passback,
        cost_tracking="ignore_errors",
    )
    needle_token = _sha(f"{profile_name}:{model_name}")[:12]
    for fn in (
        lambda: canary1_single_tool(model, max_tokens),
        lambda: canary2_multiturn_passback(model, max_tokens, max_rounds),
        lambda: canary3_long_observation(model, max_tokens, needle_token),
    ):
        cell = fn()
        cell["profile"] = profile_name
        out["canaries"].append(cell)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", action="append", default=None,
                    help="可重复;缺省 = 两条消融 profile 全跑")
    ap.add_argument("--smoke", action="store_true",
                    help="工程冒烟(预注册冻结前调试;不算 DQ,证据落 /tmp)")
    ap.add_argument("--out", default=None, help="证据目录(缺省按 run_kind 定)")
    ap.add_argument("--max-rounds", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=4000)
    ap.add_argument("--call-timeout", type=float, default=240.0)
    args = ap.parse_args()

    from repoproof.agents.deepseek_native import DS_PROFILES, list_models

    base = os.environ.get("REPOPROOF_DEEPSEEK_BASE")
    key = os.environ.get("REPOPROOF_DEEPSEEK_KEY")
    model_name = os.environ.get("REPOPROOF_MODEL") or os.environ.get("REPOPROOF_DEEPSEEK_DEFAULT")
    if not (base and key and model_name):
        print("missing env: REPOPROOF_DEEPSEEK_BASE / REPOPROOF_DEEPSEEK_KEY / "
              "REPOPROOF_MODEL|REPOPROOF_DEEPSEEK_DEFAULT", file=sys.stderr)
        return 2

    profiles = args.profile or sorted(DS_PROFILES)
    run_kind = "ENGINEERING_SMOKE" if args.smoke else "DQ_RECORD"
    out_dir = Path(args.out) if args.out else (
        Path("/tmp/dq_deepseek_smoke") if args.smoke
        else REPO / "docs" / "evidence" / "dq_deepseek")
    out_dir.mkdir(parents=True, exist_ok=True)

    from importlib.metadata import version as _pkg_version

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    adapter_sha = _sha((REPO / "src/repoproof/agents/deepseek_native.py").read_text())

    # alias vs resolved release:GET /models 原样取证(id 全列 + 命中项)
    try:
        models = list_models(base, key)
        model_ids = [m.get("id") for m in models]
        models_evidence = {
            "ids": model_ids,
            "requested": model_name,
            "requested_listed": model_name in model_ids,
            "requested_entry": next((m for m in models if m.get("id") == model_name), None),
        }
    except Exception as exc:  # noqa: BLE001
        models_evidence = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    report: dict = {
        "kind": "DQ_DEEPSEEK_CANARIES",
        "run_kind": run_kind,
        "test_mode": "DQ",
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "harness_commit": head,
        "adapter_sha256": adapter_sha,
        "litellm_version": _pkg_version("litellm"),
        "model_requested": model_name,
        "models_endpoint": models_evidence,
        "obs_cap_chars": OBS_CAP_CHARS,
        "max_tokens": args.max_tokens,
        "max_rounds": args.max_rounds,
        "profiles": [],
    }
    cells: list[dict] = []
    for p in profiles:
        print(f"== profile {p} ==", flush=True)
        res = run_profile(p, base=base, key=key, model_name=model_name,
                          max_tokens=args.max_tokens, max_rounds=args.max_rounds,
                          call_timeout_s=args.call_timeout)
        report["profiles"].append(res)
        cells.extend(res["canaries"])
        for c in res["canaries"]:
            print(f"  {c['canary']:34s} {c['status']}"
                  + (f"  ({c['reason']})" if c.get("reason") else ""), flush=True)

    report["verdict"] = dq_verdict(cells, expected_cells=3 * len(profiles))
    stamp = report["timestamp_utc"].replace(":", "").replace("-", "")
    path = out_dir / f"canaries-{run_kind.lower()}-{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["verdict"], ensure_ascii=False))
    print(f"evidence: {path}")
    return 0 if report["verdict"]["dq_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
