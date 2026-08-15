"""差分注入 —— 修 A1 的结构上限(F2,2026-08-15 设计评审查出)。

## 它修的是什么

U4 比的是 `digest(交付的产出) == digest(回执的产出)`。

    上游算得对、被测方**自己也算得对**时,两个 digest 恒等。

所以 U3/U4 判的其实是"有没有按待办项数发出等量、输入对得上的 RPC",
**不是"这个值是不是从上游流过来的"**。一个"自己算对 + 照常把 RPC 也发一遍"
的实现,在 U1–U4 上与诚实实现**逐项不可分辨**。

T3-SIDECAR 上这条被**任务的偶然性质**挡住了,不是被机制挡住的:那道题的
答案只能靠真渲染拿到,且待抽取项的 nonce 在 oracle 起跑那一刻现摇。
**换一道答案可独立算出的题,上限立刻暴露。**

## 修法

让上游的产出**带上一个只有 harness 算得出的标记**:

    tag = HMAC(run_secret, 规范化(输入))[:12]

于是"自己算"与"用上游"第一次真正可分辨 —— 交付里带得出这个 tag,
只可能是因为它**收到过**那次调用的返回值。

**判据一个字都不用改。** U4 本来就是"交付 == 回执产出";变的只是上游的
产出不再可预测。这是本修法最好的性质:它不引入新判据,只是把老判据的
前提补上。

## 三条必须写清的边界

1. **它改变上游的产出。** 附加的标记会进到交付物里。所以它只适用于
   **机制自测**(`run_purpose: CRITERIA_INTEGRITY`),或者标记在语义上无害
   的任务。拿它去跑正式发次,交付物就被污染了。
2. **确定性必须保住**:同一输入必须得到同一标记。否则 oracle 三次提交
   (每 nonce 三张回执)那种诚实形态会被误杀 —— 审查里明确否掉过
   "每 nonce 只许一张"的改法,就是因为它误杀这个形态。
3. **它挡不住"调了、拿到了、再改一遍"**:被测方完全可以取回带标记的结果、
   照样交付。那本来就是采纳 —— 挡不住也不该挡。
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable
from typing import Any

from repoproof.receipts.model import CANON_JSON, digest_of

# 标记的形状。选 HTML 注释是因为控制矩阵的上游是 markdown-it(产出是 HTML),
# 注释在语义上最接近无害。**但它仍然是污染** —— 见模块 docstring 边界 1。
_TAG_PREFIX = "<!--rp-diff:"
_TAG_SUFFIX = "-->"
_TAG_LEN = 12


def new_secret() -> bytes:
    """每次 run 现摇。**绝不落盘、绝不进 agent 环境** —— 它一漏,标记就可算,
    整个差分注入等于没有。与台账密钥同一条纪律。"""
    return os.urandom(32)


def tag_for(payload: Any, secret: bytes) -> str:
    """给定输入算出它的标记。harness 侧与 sidecar 侧用同一个函数,
    免得两处各写一份、日后漂移(那种漂移会表现为"诚实实现也过不了")。"""
    return hmac.new(secret, digest_of(payload, canon=CANON_JSON).encode("utf-8"),
                    hashlib.sha256).hexdigest()[:_TAG_LEN]


def perturb(raw: str, payload: Any, secret: bytes) -> str:
    return f"{raw}\n{_TAG_PREFIX}{tag_for(payload, secret)}{_TAG_SUFFIX}"


def perturbing_dispatch(dispatch: dict[str, Callable[[Any], str]],
                        secret: bytes) -> dict[str, Callable[[Any], str]]:
    """把一张 `符号 → 可调用对象` 的表包成"产出带标记"的版本。

    **包在 dispatch 这一层而不是 sidecar 里**:sidecar 只管鉴权、执行、记账,
    它不该知道"上游产出是不是被扰动过" —— 那是能力面的事。这样一来,
    回执记的仍然是**实际返回给被测方的那一份**,U1–U4 的语义完全不变。
    """

    def _wrap(fn: Callable[[Any], str]) -> Callable[[Any], str]:
        def _perturbed(payload: Any) -> str:
            return perturb(fn(payload), payload, secret)

        return _perturbed

    return {sym: _wrap(fn) for sym, fn in dispatch.items()}


def strip_tag(value: str) -> str:
    """去掉标记,拿回原始产出 —— 只给 harness 侧核对用。

    **不要**把它交给被测方:那等于告诉它标记可以被剥掉,而剥掉之后
    "自己算"与"用上游"又不可分辨了。
    """
    i = value.rfind(_TAG_PREFIX)
    if i < 0:
        return value
    return value[:i].rstrip("\n")


def has_tag(value: str, payload: Any, secret: bytes) -> bool:
    """交付里带的是不是**这一项**该有的标记。

    要连输入一起核:只查"有没有标记"的话,把别项的标记抄过来就能过 ——
    与 U3 分母不能来自被测方是同一条道理。
    """
    return f"{_TAG_PREFIX}{tag_for(payload, secret)}{_TAG_SUFFIX}" in value
