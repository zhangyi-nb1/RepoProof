"""Sidecar Conformance 的 Runtime Profile 与上游能力面。

`rt-sidecar-canary-v1` —— A1 的第一个使用者。它**不是 benchmark**:测的是
harness 自己那条链走不走得通(F0 自检),不计任何模型能力。

上游是 harness 独占的 fixture(`benchmarks/v2/upstream_fixtures/`),
agent 的 venv 里 import 不着。这一点是整套主张的地基,由
`topology.py` 逐条现场核验,不靠约定。
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO / "benchmarks" / "v2" / "upstream_fixtures" / "canary_upstream_v1"
sys.path.insert(0, str(REPO / "src"))

from repoproof.execution.runtime_profiles import RuntimeProfile, register_profile  # noqa: E402
from repoproof.execution.upstream_sidecar import UpstreamSpec  # noqa: E402

DISTRIBUTION = "repoproof-canary-upstream"
IMPORT_MODULE = "canary_upstream"
SYMBOL = "canary_upstream.transform.normalize"
OTHER_SYMBOL = "canary_upstream.transform.fingerprint"
PROFILE_ID = "rt-sidecar-canary-v1"


def load_upstream():
    """**只有 harness 侧**做这一步:把 fixture 挂进本进程的搜索路径。

    agent 侧永远不做这件事 —— 它连 fixture 的路径都拿不到(`agent_env()`
    只给端点与令牌)。上游能被谁 import,就是这套拓扑的全部内容。
    """
    p = str(FIXTURE_ROOT)
    if p not in sys.path:
        sys.path.insert(0, p)
    import canary_upstream
    import canary_upstream.transform  # noqa: F401

    return canary_upstream


def _text(payload) -> str:
    return payload.get("text", "") if isinstance(payload, dict) else str(payload)


def _normalize(payload) -> str:
    return load_upstream().transform.normalize(_text(payload))


def _fingerprint(payload) -> str:
    return load_upstream().transform.fingerprint(_text(payload))


SPEC = UpstreamSpec(DISTRIBUTION, IMPORT_MODULE,
                    {SYMBOL: _normalize, OTHER_SYMBOL: _fingerprint},
                    loader=load_upstream)

# lifecycle:**candidate**(2026-08-14 晋级,判据 G1–G5 全过,留痕见
# `docs/evidence/profile_lifecycle/promotions.jsonl`)。
#
# 到此为止的含义:**机制自己站得住** —— 拓扑成立、诚实实现不被误杀、八条
# 攻击各红各位、变异全捕。**不含**"真模型跑得动"这件事:我们的 adapter 是
# 照着判据写的,那叫出题人自己会做。要往 qualified 走,得有 ≥2 个模型
# profile 的真实发次且至少一发诚实通过 —— 那要等 T3-SIDECAR v1。
PROFILE = register_profile(RuntimeProfile(
    id=PROFILE_ID, topology="sidecar", lifecycle="candidate",
    summary="Conformance canary:harness 独占 fixture,agent 只能经 RPC 请它 normalize",
    upstream=SPEC, required_symbols=frozenset({SYMBOL}), default_symbol=SYMBOL))
