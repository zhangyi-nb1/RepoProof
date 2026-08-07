"""UI 动作层 — 全部直接调用 RepoProof Core 的既有函数。

Gate 9A 铁律:UI 绝不复制 Completion Gate / verifier 逻辑;
`verify_case` 与 `replay_case` 只是 `repoproof demo …` 的进程内等价
调用,结果原样展示。零 LLM。
"""

from __future__ import annotations

from repoproof.runner.demo import demo_replay, demo_verify
from repoproof.ui.services.facts import repo_root


def verify_case(case: str) -> dict:
    """= `repoproof demo verify --case <case>`(复算 gate 决策表)。"""
    return demo_verify(repo_root(), case)


def replay_case(case: str) -> dict:
    """= `repoproof demo replay --case <case>`(全新容器,零模型调用)。"""
    return demo_replay(repo_root(), case)
