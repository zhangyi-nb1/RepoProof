"""DSH profile 实体的钉死(DSH 阶段 6 收口件)。

**冻结判据**:

- D1 **登记在册且惰性可达**:`profile("rt-dsh-minimal-0.1.0rc6-v1")` 经
  _LAZY_DEFS 白名单解析成功,id/拓扑逐字。反例:除名 —— promotion 留痕
  悬空,阶段 7 的 G6(按台账 runtime_profile_id 挂靠真实发次)无从谈起,
  而"查无此 profile"长得跟"从没做过"一模一样。
- D2 **划界语在场**:summary 里必须带"不代表真实模型可用" —— 这是报告
  阶段 6 通过条件的一部分:candidate 只证机制站得住(C1-C15 + 变异全捕),
  真模型可用是 qualified(G6/G7)的事。反例:省了这句 —— candidate 被
  读成"DeepSeek 能跑了",两级承诺塌成一级。
- D3 **判据组恰当**:→ candidate 的现算 checks 恰为 {G1.topology,
  G5.mutation},且 G1 走 in_process 不适用分支 —— DSH 不该被误套 sidecar
  的 conformance 矩阵判据(它没有回执面,恒失败 = 墙)。G5 的 ok 不在
  此处断言:变异证据按 HEAD 有效期判,刚提交的 commit 上必然还没有
  (与 test_canary_is_candidate 同一分工:现场复核走 mutation_gate +
  promote_profile 两脚本)。

lifecycle 的声明↔留痕一致性由 test_profile_promotion.py::test_p6 统一钉
(那边经惰性路径把本 profile 拉进 known_profiles 的可见范围)。
"""

from __future__ import annotations

from pathlib import Path

from repoproof.execution.profile_promotion import evaluate_promotion
from repoproof.execution.runtime_profiles import profile

REPO = Path(__file__).resolve().parents[1]
DSH_PROFILE_ID = "rt-dsh-minimal-0.1.0rc6-v1"


def test_d1_dsh_profile_registered_and_lazily_reachable() -> None:
    p = profile(DSH_PROFILE_ID)
    assert p.id == DSH_PROFILE_ID
    assert p.topology == "in_process"
    assert p.lifecycle in ("experimental", "candidate", "qualified"), p.lifecycle


def test_d2_tier_disclaimer_is_in_the_summary() -> None:
    # 每一级都有自己的过度解读,划界语跟级走(阶段 6 报告条件的延续;
    # qualified 依据 DQ-SDK-1 批,promotions.jsonl 留痕):candidate 防
    # "DeepSeek 能跑了",qualified 防"能力主张 / DSH 更好"。新级别必须
    # 在这里声明自己的划界语,否则 KeyError 当场拦下。
    p = profile(DSH_PROFILE_ID)
    required = {"candidate": "不代表真实模型可用",
                "qualified": "不是能力主张"}[p.lifecycle]
    assert required in p.summary, (
        "划界语丢了 —— 层级承诺会被读成上一级没给的东西"
        f"(lifecycle={p.lifecycle} 要求『{required}』)")


def test_d3_candidate_checks_are_exactly_g1_na_plus_g5() -> None:
    v = evaluate_promotion(DSH_PROFILE_ID, repo=REPO, to="candidate")
    assert {c.id for c in v.checks} == {"G1.topology", "G5.mutation"}
    g1 = next(c for c in v.checks if c.id == "G1.topology")
    assert g1.ok and "不适用" in g1.detail, (
        "DSH 被误套了 sidecar 的 conformance 判据 —— 它没有回执面,"
        f"那组判据对它恒失败 = 墙:{g1.detail}")
