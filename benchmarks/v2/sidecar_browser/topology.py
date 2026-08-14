"""`rt-sidecar-browser-v1` 的拓扑核验 —— A1 在**真上游**上的地基。

与 canary 的 topology 同构,但守的对象换成了封存 runtime:

    T1  browser-use 及其导入闭包不在任何钉版 wheelhouse 里
    T2  agent 的解释器 import 不到 browser_use
    T3  封存件住在 host_guard 保护目录里(agent 读写都发不出去)
    T4  交给 agent 的环境变量里没有任何指向封存件的线索
    T5  封存件完好(清单在、摘要对得上)—— 真上游那份字节没被动过

T5 是这里多出来的一条:canary 的 fixture 是几十行源码,进 git、随仓走;
封存 runtime 是 1GB 的构建产物,不进 git。**不进 git 的东西必须有别的办法
证明它没变** —— 那就是清单里的内容摘要。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from repoproof.execution.provisioning import verify_sealed  # noqa: E402
from repoproof.harness.host_guard import is_protected  # noqa: E402

RUNTIME_ROOT = Path("~/RepoProofRuntimes/rt-sidecar-browser-v1").expanduser()
IMPORT_MODULE = "browser_use"
# 真上游的导入闭包里,agent 侧本就缺席的那几个(§4.1 的原始发现)
CLOSURE = ("browser_use", "browser-use", "bubus", "cdp_use", "cdp-use",
           "uuid7", "uuid_extensions", "pyotp")


def _wheelhouses() -> list[Path]:
    base = Path("~/RepoProofBench").expanduser()
    return sorted(p for p in base.glob("wheelhouse-offerclaw-*") if p.is_dir())


def check_topology() -> dict:
    findings: list[dict] = []

    hits = []
    for wh in _wheelhouses():
        for f in wh.iterdir():
            n = f.name.lower().replace("_", "-")
            if any(n.startswith(c.lower().replace("_", "-")) for c in CLOSURE):
                hits.append(f"{wh.name}/{f.name}")
    findings.append({"check": "T1.closure_not_in_wheelhouse", "ok": not hits,
                     "detail": (f"扫了 {len(_wheelhouses())} 个 wheelhouse,"
                                f"导入闭包零命中" if not hits else f"竟然有:{hits[:4]}")})

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    probe = subprocess.run(                                    # noqa: S603
        [sys.executable, "-c", f"import {IMPORT_MODULE}"],
        capture_output=True, text=True, cwd=str(REPO), env=env, check=False)
    findings.append({"check": "T2.not_importable_by_agent", "ok": probe.returncode != 0,
                     "detail": ("agent 的解释器 import 不到(应该的):"
                                + (probe.stderr.strip().splitlines() or ["?"])[-1]
                                if probe.returncode != 0 else "竟然 import 到了")})

    prot = is_protected(RUNTIME_ROOT)
    findings.append({"check": "T3.sealed_root_is_protected", "ok": prot,
                     "detail": (f"{RUNTIME_ROOT} 在 host_guard 保护目录内"
                                if prot else f"封存件不受保护:{RUNTIME_ROOT}")})

    from repoproof.execution.upstream_sidecar import SidecarHandle

    fake = SidecarHandle(None, "http://127.0.0.1:1", "tok",   # type: ignore[arg-type]
                         RUNTIME_ROOT / "l.jsonl", "rt-sidecar-browser-v1")
    blob = json.dumps(fake.agent_env())
    leaks = [s for s in ("browser_use", "RepoProofRuntimes", "chromium",
                         str(RUNTIME_ROOT), "ledger") if s in blob]
    findings.append({"check": "T4.no_runtime_hint_in_agent_env", "ok": not leaks,
                     "detail": ("agent 只拿到端点与令牌" if not leaks
                                else f"环境里漏了线索:{leaks}")})

    ok, why = verify_sealed(RUNTIME_ROOT)
    findings.append({"check": "T5.seal_intact", "ok": ok, "detail": why})

    return {"ok": all(f["ok"] for f in findings), "findings": findings}
