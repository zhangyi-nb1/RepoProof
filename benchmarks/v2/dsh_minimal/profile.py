"""rt-dsh-minimal-0.1.0rc6-v1 —— 封存 DSH minimal runtime 的 profile 实体。

这是 **backend=dsh 发次的 runtime 身份**(台账 `runtime_profile_id` 列),
与 backend_id 列是两条正交轴:backend 说的是"agent 环归谁跑"(mini-swe /
dsh),profile 说的是"跑在哪套封存交付上"。id 里钉着 runtime 版本
(0.1.0rc6)—— 换版本 = 换 id = 换代,不就地改语义(与 registry 同律)。

拓扑记 in_process:任务的上游(若有)装在 workspace venv 里由模型自己
调用,没有 sidecar 回执面;DSH runtime 自身的进程隔离是 backend 轴的
执行语义(dsh_backend 拓扑闸 + 环境闸 + 预算刀),不改变上游交付方式。

**candidate 只证明机制站得住**(C1-C15 金丝雀全钉死、M-DSH 变异全捕、
晋级判据 G5 走仓内机制)——**不代表真实模型可用**。真模型跑不跑得动是
qualified 那一级的问题(G6 真实发次 + G7 无未决假通过),要等阶段 7
用户注入真 key 的 DQ-SDK 发次。这句划界写在这里,是报告阶段 6 通过
条件的一部分,不许省。
"""

from __future__ import annotations

from repoproof.execution.runtime_profiles import RuntimeProfile, register_profile

PROFILE_ID = "rt-dsh-minimal-0.1.0rc6-v1"

PROFILE = register_profile(RuntimeProfile(
    id=PROFILE_ID,
    topology="in_process",
    lifecycle="experimental",
    summary=(
        "封存 DSH minimal runtime(0.1.0rc6)作不可信 AgentBackend;"
        "candidate 仅证机制站得住,不代表真实模型可用"
    ),
))
