"""adapter 侧的 RPC 客户端 —— 被测实现能拿到的**全部**能力。

注意它拿不到什么:回执台账路径、签名密钥、run_nonce。adapter 只能
"请 sidecar 做一次,拿回一个 result"。用不用这个 result,是它自己的事 ——
而那正是采纳谓词要判的。
"""
from __future__ import annotations

import json
import urllib.request


class Sidecar:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def invoke(self, text: str, *, request_nonce: str,
               symbol: str | None = None) -> dict:
        body = json.dumps({"symbol": symbol, "input": {"text": text},
                           "request_nonce": request_nonce}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/invoke", data=body,
            headers={"Content-Type": "application/json",
                     "X-Sidecar-Token": self.token})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
