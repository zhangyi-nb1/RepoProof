"""Sidecar Conformance 用的钉版上游 fixture —— **harness 独占**。

它存在的唯一理由:证明 A1 那条链真的成立 ——

    Agent → (只能) RPC → Harness-owned Sidecar → 真执行钉版上游
          → Receipt → Verifier

**不是 benchmark,不计模型能力。** 它测的是 harness 自己,属 F0 自检。

为什么不用现成的三方包(如控制矩阵里的 markdown-it-py):那些包 agent 的
venv 里装得到,于是"假包""导入真包却用复制实现"这两条负控只能靠约定成立,
而不是靠拓扑成立。本 fixture **不在任何 wheelhouse 里、不在 agent 会话的
任何路径上、住在策略拒绝表覆盖的仓内目录**,agent 想 import 都 import 不着。
那才是 A1 的核心主张:**上游装在谁那儿是拓扑问题**。
"""

__version__ = "1.0.0"
UPSTREAM_ID = "repoproof-canary-upstream"
