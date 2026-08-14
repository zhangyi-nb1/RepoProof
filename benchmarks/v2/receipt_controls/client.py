"""adapter 侧的 RPC 客户端 —— 被测实现能拿到的**全部**能力。

注意它拿不到什么:回执台账路径、签名密钥、run_nonce。adapter 只能
"请 sidecar 做一次,拿回一个 result"。用不用这个 result,是它自己的事 ——
而那正是采纳谓词要判的。
"""
from __future__ import annotations

import json
import urllib.request


class Sidecar:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        # 超时可配:markdown 渲染是毫秒级,真浏览器**首次**冷启动实测 16.3s
        # (macOS 首次运行新下载的 app bundle 要过一遍扫描),之后约 1.8s。
        # 固定 30s 会在冷启动那次偶发打满 —— 而那不是缺陷,是一次性开销。
        self.timeout = timeout

    def invoke(self, text: str, *, request_nonce: str,
               symbol: str | None = None) -> dict:
        body = json.dumps({"symbol": symbol, "input": {"text": text},
                           "request_nonce": request_nonce}).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + "/invoke", data=body,
            headers={"Content-Type": "application/json",
                     "X-Sidecar-Token": self.token})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))
