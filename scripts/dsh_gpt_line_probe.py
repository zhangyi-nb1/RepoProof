#!/usr/bin/env python3
"""GPT×DSH 线协议在线探针(2026-08-20,用户授权的适配测试;不计模型表现)。

链路:封存 DSH runtime → dsh_gpt_shim(127.0.0.1)→ 本地 GPT 端点
(openai-compatible,REPOPROOF_API_BASE/KEY/MODEL 经环境注入)。

两问:
  A 文本回合 —— runtime 全栈干净(attribution ok / trace ok / usage 可对账);
  B 工具回合 —— 模型经 DSH 工具环真执行 bash,观察回传后收终答。

性质:**仪器适配探针**(阶段 6 "LLM 线协议实测"同类),worker 级直驱,
不产生 runs.jsonl 行、不计分;GPT×DSH 组合未经 DQ 资格批,计分批前须
另走资格流程。证据(值级脱敏:上游 base 不落盘,key 永不落任何输出)写
docs/evidence/dsh_gpt_adapter/line-probe-<date>.json。

用法(key 经 shell→进程 env,不进 argv):
    set -a && source .env && set +a && .venv/bin/python scripts/dsh_gpt_line_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from repoproof.agents.dsh_backend import DshBudget, run_dsh_worker  # noqa: E402
from repoproof.agents.dsh_gpt_shim import DshGptShim  # noqa: E402

RT_ROOT = Path.home() / "RepoProofRuntimes" / "rt-dsh-minimal-0.1.0rc6-v1"
SEALED_PY = RT_ROOT / ".venv" / "bin" / "python"
_FAKE_DSH_KEY = "sk-canary-invalid-0000"   # runtime 侧假 key(字面量;真 key 只在 shim→上游)


def probe(name: str, prompt: str, tmp: Path, *, upstream: dict) -> dict:
    ws = tmp / f"ws-{name}"
    ws.mkdir()
    job = {"prompt": prompt, "workspace": str(ws),
           "events_path": str(tmp / f"ev-{name}" / "events.jsonl"),
           "session_root": str(tmp / f"sess-{name}"),
           "cordis": str(RT_ROOT / "config" / "minimal.upstream.0.1.0rc6.cordis.yml"),
           "request_timeout_seconds": 180.0,
           "max_tokens": 4096}
    with DshGptShim(upstream["base"], upstream["key"], upstream["model"],
                    timeout_s=240.0) as shim:
        job["env"] = {"DEEPSEEK_BASE_URL": shim.base_url}
        r = run_dsh_worker(job, worker_python=str(SEALED_PY),
                           budget=DshBudget(max_wall_seconds=600,
                                            max_logical_requests=10),
                           extra_env={"DEEPSEEK_API_KEY": _FAKE_DSH_KEY})
        shapes = list(shim.requests)   # 形状记录:无正文无头(G6 钉)
    out = {
        "probe": name,
        "ok": bool(r.result.get("ok")),
        "finish_reason": r.result.get("finish_reason"),
        "final_response": (r.result.get("final_response") or "")[:300],
        "attribution": r.attribution,
        "killed": r.killed,
        "orphan_count": r.orphan_count,
        "trace_ok": r.trace.ok,
        "trace_problems": r.trace.problems[:5],
        "usage_totals": r.trace.usage_totals,
        "logical_requests": r.trace.counters.get("logical_requests"),
        "shim_requests": shapes,
        "workspace_files": sorted(p.name for p in ws.iterdir()),
    }
    return out


def main() -> int:
    if not SEALED_PY.exists():
        print("封存 runtime 不在本机", file=sys.stderr)
        return 2
    base = os.environ.get("REPOPROOF_API_BASE") or os.environ.get("REPOPROOF_BASE_URL")
    key = os.environ.get("REPOPROOF_API_KEY")
    model = os.environ.get("REPOPROOF_MODEL") or os.environ.get("REPOPROOF_MODEL_NAME")
    if not (base and key and model):
        print("缺 REPOPROOF_API_BASE/KEY/MODEL(先 source .env)", file=sys.stderr)
        return 2
    upstream = {"base": base, "key": key, "model": model}

    date = os.environ.get("RP_PROBE_DATE") or "undated"
    results = []
    with tempfile.TemporaryDirectory(prefix="rp-gpt-line-") as td:
        tmp = Path(td)
        results.append(probe(
            "A-text", "只回复一行,内容恰为:GPT_LINE_OK", tmp, upstream=upstream))
        results.append(probe(
            "B-tool", "用 bash 工具运行这条命令并把它的输出原样告诉我:"
                      "echo RP_GPT_$((6*7))", tmp, upstream=upstream))

    a, b = results
    checks = {
        "A_clean": a["ok"] and a["attribution"] == "ok" and a["trace_ok"]
                   and not a["killed"],
        "A_says_ok": "GPT_LINE_OK" in a["final_response"],
        "A_usage_seen": (a["usage_totals"] or {}).get("input_tokens", 0) > 0,
        "B_clean": b["ok"] and b["attribution"] == "ok" and b["trace_ok"]
                   and not b["killed"],
        "B_tool_loop": (b["logical_requests"] or 0) >= 2,
        "B_real_exec": "RP_GPT_42" in b["final_response"],
    }
    doc = {
        "_what": "GPT×DSH 线协议在线探针:封存 runtime → dsh_gpt_shim → 本地 GPT;"
                 "仪器适配测试,不计模型表现,不产生台账行",
        "date": date,
        "upstream": {"protocol": "openai-compatible",
                     "base": "«REDACTED-LAN-ENDPOINT»", "model": model},
        "runtime": "rt-dsh-minimal-0.1.0rc6-v1",
        "probes": results,
        "checks": checks,
        "all_pass": all(checks.values()),
    }
    out = REPO / "docs" / "evidence" / "dsh_gpt_adapter" / f"line-probe-{date}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    for r in results:
        print(f"[{r['probe']}] ok={r['ok']} finish={r['finish_reason']} "
              f"attr={r['attribution']} trace_ok={r['trace_ok']} "
              f"req={r['logical_requests']} usage={r['usage_totals']}")
        print(f"  final: {r['final_response'][:120]!r}")
    print(f"checks: {checks}")
    print(f"{'全过' if doc['all_pass'] else '未过'};证据:{out}")
    return 0 if doc["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
