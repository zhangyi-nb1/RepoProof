"""上游执行回执(Upstream Execution Receipt)的数据模型 —— A0。

**它不是调用日志。** 用户 2026-08-14 的提醒是这套设计的出发点:

    browser_use.do_something(...)          # 调用证据成立
    result = my_own_http_implementation()  # 真正的结果来自别处
    return result

只记"调用发生过",上面这段就能全过。所以回执必须同时证明**四件事**:

    ① 谁执行的        —— 不是 agent 自称,是执行方自己签的
    ② 执行了什么上游能力 —— 钉到发行版 + 版本 + **实际加载的字节** + 符号
    ③ 处理了什么输入   —— input digest,防"拿别的调用充数"
    ④ 结果有没有进入最终输出链 —— output digest + 采纳谓词

前三件由本模块的密码学绑定保证;第④件由 `verify.py` 的**采纳谓词**判定,
且**没有登记采纳谓词的任务一律判不通过**(与"缺清单显式失败"同一条纪律:
第④件是整套设计的要害,不许默认放行)。

绑定关系(用户原话:最关键的是这四样)::

    run_nonce + input_digest + output_digest + upstream identity

少任何一样,分别对应一种绕过:

===========================  =========================================
绕过方式                      挡它的字段
===========================  =========================================
重放上一次 run 的回执          `run_nonce`(每 run 现摇,agent 看不到)
伪造回执                      `receipt_signature`(HMAC,密钥只在 harness
                             与 sidecar 之间;agent 环境里没有)
借用其他调用充数               `input.digest` + `binding.request_nonce`
象征性调用一次                 覆盖率:每个待办单元各需一张 input digest
                             对得上的回执,一张顶不了 N 个
调真包但用另一个结果           `output.digest` + 采纳谓词(第④件)
调错上游方法                   `operation.symbol` 必须在契约要求集里
真包在场但实际跑的是复制实现     `upstream.artifact_hash` —— 取自**运行时
                             实际加载的模块文件**,不是配置里抄来的字符串
===========================  =========================================
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass, field
from typing import Any

RECEIPT_VERSION = 1

# 摘要的规范化标签。写进回执,让采纳谓词知道"这个 digest 到底哈的是什么" ——
# 不写的话,验证方只能猜,而猜错的方向永远是朝松(算不出就放过)。
CANON_JSON = "json/sort_keys+utf8"
CANON_BYTES = "bytes/raw"
CANON_TEXT_SQUASH = "text/whitespace-squashed"


def canonical_json(obj: Any) -> bytes:
    """确定性序列化 —— 同一份对象在任何机器上都得到同一串字节。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def digest_of(value: Any, *, canon: str = CANON_JSON) -> str:
    """`<canon>:<sha256>` —— 摘要自带口径,防止两边哈的不是同一个东西。"""
    if canon == CANON_BYTES:
        raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    elif canon == CANON_TEXT_SQUASH:
        import re
        raw = re.sub(r"\s+", "", value if isinstance(value, str)
                     else value.decode("utf-8", "replace")).encode("utf-8")
    elif canon == CANON_JSON:
        raw = canonical_json(value)
    else:
        raise ValueError(f"未登记的规范化口径:{canon}(不猜)")
    return f"{canon}:{hashlib.sha256(raw).hexdigest()}"


@dataclass(frozen=True)
class UpstreamIdentity:
    """②:执行了什么上游能力。

    `artifact_hash` 必须由执行方在**调用现场**从 `sys.modules[...].__file__`
    的实际字节算出,不得从契约或配置里抄 —— 抄来的字符串证明不了跑的是哪份
    代码,而"真包在场、实际跑复制实现"正是 T3 批 13 的原样。"""

    distribution: str
    version: str
    artifact_hash: str
    import_module: str = ""


@dataclass(frozen=True)
class Operation:
    """②的另一半:调的是哪个符号,哪一次调用。"""

    symbol: str
    invocation_id: str


@dataclass(frozen=True)
class Payload:
    """③/④:输入与输出各自的摘要 + 口径。

    `digest` 是判定用的;`size` 与 `preview` 只为人工取证,**不参与任何
    判定** —— 让它们参与判定就等于让被测方通过控制预览内容影响结论。"""

    digest: str
    size: int = 0
    preview: str = ""


@dataclass(frozen=True)
class Runtime:
    """①:谁执行的。

    `process_identity` 是执行方进程的身份(pid + 启动时刻 + 解释器路径的
    复合),不是 agent 报上来的名字。

    `profile_id` 来自 A0 初版字段表 —— 同一份上游在不同 Runtime Profile 下
    (进程内 / sidecar / 远端)证据强度不同,不记就没法在跨发次比较时区分。"""

    executor: str
    process_identity: str
    timestamp: str
    profile_id: str = ""


@dataclass(frozen=True)
class Binding:
    """把这一张回执**钉到这一次请求**上。

    `request_nonce` 由 harness 随任务单元下发,agent 必须原样转交给执行方;
    执行方把它回写进回执。于是 A 单元的回执拿不到 B 单元去用。
    `parent_invocation` 串出调用 DAG,让"结果进入输出链"可以逐跳追。"""

    run_nonce: str
    request_nonce: str
    parent_invocation: str | None = None


@dataclass(frozen=True)
class Receipt:
    receipt_version: int
    run_id: str
    upstream: UpstreamIdentity
    operation: Operation
    input: Payload
    output: Payload
    runtime: Runtime
    binding: Binding
    # 链式防篡改:与 trace.jsonl 同一套办法。签名挡伪造(需要密钥),
    # 哈希链挡事后改写(不需要密钥,拿到 bundle 的人也能自查)。
    prev_sha256: str | None = None
    receipt_signature: str = ""
    extra: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- 序列化
    def signable(self) -> bytes:
        """参与签名的部分 —— **不含签名自身,也不含链字段**。

        链字段排除在外是有意的:链是写入顺序的性质,签名是内容的性质。
        把链算进签名,同一张回执换个写入位置签名就变了,重放检测反而更难。"""
        d = asdict(self)
        d.pop("receipt_signature", None)
        d.pop("prev_sha256", None)
        return canonical_json(d)

    def sign(self, key: bytes) -> Receipt:
        sig = hmac.new(key, self.signable(), hashlib.sha256).hexdigest()
        return Receipt(**{**asdict_shallow(self), "receipt_signature": sig})

    def signature_ok(self, key: bytes) -> bool:
        if not self.receipt_signature:
            return False
        want = hmac.new(key, self.signable(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(want, self.receipt_signature)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    @staticmethod
    def from_dict(d: dict) -> Receipt:
        return Receipt(
            receipt_version=d["receipt_version"],
            run_id=d["run_id"],
            upstream=UpstreamIdentity(**d["upstream"]),
            operation=Operation(**d["operation"]),
            input=Payload(**d["input"]),
            output=Payload(**d["output"]),
            runtime=Runtime(**d["runtime"]),
            binding=Binding(**d["binding"]),
            prev_sha256=d.get("prev_sha256"),
            receipt_signature=d.get("receipt_signature", ""),
            extra=d.get("extra", {}),
        )


def asdict_shallow(r: Receipt) -> dict:
    """只拆一层 —— 嵌套的 frozen dataclass 保持原对象,避免重建时丢类型。"""
    return {
        "receipt_version": r.receipt_version, "run_id": r.run_id,
        "upstream": r.upstream, "operation": r.operation,
        "input": r.input, "output": r.output, "runtime": r.runtime,
        "binding": r.binding, "prev_sha256": r.prev_sha256,
        "receipt_signature": r.receipt_signature, "extra": dict(r.extra),
    }
