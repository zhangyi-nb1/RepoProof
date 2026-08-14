"""上游执行回执(A0)。

`model` 数据模型与密码学绑定 · `ledger` harness 私有的独立事件通道 ·
`verify` 四道谓词(U1 执行方可信 / U2 上游身份 / U3 输入覆盖 / U4 采纳)。

读之前先读 `model.py` 的模块文档 —— 那里写了这套设计要挡的七种绕过,
以及为什么"只记调用发生过"必然被绕。
"""

from repoproof.receipts.model import (
    RECEIPT_VERSION,
    Binding,
    Operation,
    Payload,
    Receipt,
    Runtime,
    UpstreamIdentity,
    digest_of,
)

__all__ = ["RECEIPT_VERSION", "Binding", "Operation", "Payload", "Receipt",
           "Runtime", "UpstreamIdentity", "digest_of"]
