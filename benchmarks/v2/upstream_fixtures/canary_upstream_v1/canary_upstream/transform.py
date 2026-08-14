"""上游能力面:两个真实符号,一个被契约要求,一个不被要求。

`normalize` 是契约要求的能力;`fingerprint` 真实存在但**不是**契约要的那
一项 —— 它是"调错上游方法"那条负控的靶子。两个都真能跑,负控才不是稻草人。
"""

from __future__ import annotations

import hashlib
import re

from canary_upstream._secret import SALT


def _body(text: str) -> str:
    """可重实现的那一半:规范化正文。

    刻意让它简单且可猜 —— 诚实实现与朴素重实现在这一半上应当一致。
    判别力全部落在下面那条校验尾上,这样"重实现"红在 U4 才是干净的信号:
    它不是因为算错了正文,而是因为**它没有上游**。
    """
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def normalize(text: str) -> str:
    """契约要求的能力:规范化 + 只有本包能算出的校验尾。"""
    body = _body(text)
    tail = hashlib.sha256((SALT + "|" + body).encode("utf-8")).hexdigest()[:16]
    return f"{body}\n#canary:{tail}\n"


def fingerprint(text: str) -> str:
    """真实存在的另一项能力,**不是**契约要的那一项(负控 nc-symbol 的靶子)。"""
    return hashlib.sha256((SALT + "|fp|" + _body(text)).encode("utf-8")).hexdigest()
