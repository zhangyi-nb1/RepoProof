#!/usr/bin/env python3
"""Harness 拥有的上游执行 sidecar —— 第 6 步的被测装置。

它是**唯一**持有真上游的进程。被测实现(下称 adapter)只能通过 RPC 请它
执行,拿不到上游本体。每执行一次,sidecar 就往回执台账追加一张签好名的
回执 —— 台账路径与密钥都从环境变量来,**adapter 的环境里没有这两样**。

这不是玩具:三处是真的,少一处整个实验就退化成"我自己证明我自己"。

1. **真加载上游**。`artifact_hash` 由 `sys.modules[...]`.__file__` 的**实际
   字节**现算,不是从配置里抄。于是"自带一个同名包"改不了这个值。
2. **真跨进程**。sidecar 是独立进程,adapter 通过 HTTP 调它。adapter 伪造
   RPC 响应可以,但伪造不出台账里的那一行。
3. **回执走独立通道**。sidecar 直接写台账,不经 adapter 转交。adapter 连
   台账路径都不知道。

上游能力选 `markdown_it.MarkdownIt.render`:渲染 Markdown 是**真的可以被
朴素重实现**的(负控 nc1 就这么干),输出又足够长,使"摘要相等"这条采纳
判据有实质内容 —— 换一份实现,输出就对不上。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from repoproof.receipts.ledger import ReceiptLedger  # noqa: E402
from repoproof.receipts.model import (  # noqa: E402
    CANON_JSON,
    CANON_TEXT_SQUASH,
    RECEIPT_VERSION,
    Binding,
    Operation,
    Payload,
    Receipt,
    Runtime,
    UpstreamIdentity,
    digest_of,
)

DISTRIBUTION = "markdown-it-py"
IMPORT_MODULE = "markdown_it"
SYMBOL = "markdown_it.MarkdownIt.render"
PROFILE_ID = "rt-sidecar-v1"


def _upstream_identity() -> UpstreamIdentity:
    """**现场**从实际加载的模块算身份 —— 不读配置,不信自述。

    `artifact_hash` 哈的是包内全部 .py 的字节。自带同名包能骗过 `__name__`
    和 `__version__`(T3 批 13 连 `UPSTREAM_COMMIT` 都照抄了),骗不过这个。
    """
    import markdown_it

    root = Path(markdown_it.__file__).resolve().parent
    h = hashlib.sha256()
    for f in sorted(root.rglob("*.py")):
        if "__pycache__" in f.parts:
            continue
        h.update(f.relative_to(root).as_posix().encode("utf-8"))
        h.update(f.read_bytes())
    return UpstreamIdentity(DISTRIBUTION, markdown_it.__version__,
                            f"sha256:{h.hexdigest()}", IMPORT_MODULE)


def _process_identity() -> str:
    return f"pid={os.getpid()}:boot={int(_BOOT)}:py={sys.executable}"


_BOOT = time.time()
_LOCK = threading.Lock()
_SEQ = 0


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):            # 静音:测试输出里不要 HTTP 噪声
        pass

    def do_POST(self):                    # noqa: N802 —— BaseHTTPRequestHandler 的约定
        global _SEQ
        if self.headers.get("X-Sidecar-Token") != self.server.token:      # type: ignore[attr-defined]
            return self._json(403, {"error": "bad token"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:                                            # noqa: BLE001
            return self._json(400, {"error": str(e)})

        symbol = req.get("symbol") or SYMBOL
        payload = req.get("input")
        request_nonce = req.get("request_nonce") or ""

        try:
            result = _execute(symbol, payload)
        except Exception as e:                                            # noqa: BLE001
            return self._json(400, {"error": f"{type(e).__name__}: {e}"})

        with _LOCK:
            _SEQ += 1
            inv = f"inv-{_SEQ:04d}"
            r = Receipt(
                receipt_version=RECEIPT_VERSION,
                run_id=self.server.run_id,                                # type: ignore[attr-defined]
                upstream=_upstream_identity(),
                operation=Operation(symbol, inv),
                input=Payload(digest_of(payload, canon=CANON_JSON),
                              size=len(json.dumps(payload, ensure_ascii=False)),
                              preview=str(payload)[:60]),
                output=Payload(digest_of(result, canon=CANON_TEXT_SQUASH),
                               size=len(result), preview=result[:60]),
                runtime=Runtime("sidecar", _process_identity(),
                                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                profile_id=PROFILE_ID),
                binding=Binding(self.server.run_nonce, request_nonce),    # type: ignore[attr-defined]
            )
            self.server.ledger.append(r)                                  # type: ignore[attr-defined]

        # 返回体里**不带**任何回执字段。adapter 拿不到签名、拿不到 nonce,
        # 它唯一能做的就是用或不用这个 result —— 而"用没用"由采纳谓词判。
        return self._json(200, {"invocation_id": inv, "result": result})

    def _json(self, code: int, body: dict):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _execute(symbol: str, payload) -> str:
    """真调上游。符号不在支持表里就报错 —— 不猜。"""
    import markdown_it

    md = markdown_it.MarkdownIt()
    text = payload.get("text", "") if isinstance(payload, dict) else str(payload)
    if symbol == SYMBOL:
        return md.render(text)
    if symbol == "markdown_it.MarkdownIt.parse":
        # 真实存在的另一个上游方法 —— 负控 nc4 用它:调的是真上游,
        # 但不是契约要求的那个能力。
        return json.dumps([t.type for t in md.parse(text)], ensure_ascii=False)
    raise ValueError(f"未支持的符号:{symbol}")


def serve(ledger_path: Path, key: bytes, run_id: str, run_nonce: str,
          token: str, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), _Handler)
    srv.ledger = ReceiptLedger(ledger_path, key)      # type: ignore[attr-defined]
    srv.run_id = run_id                               # type: ignore[attr-defined]
    srv.run_nonce = run_nonce                         # type: ignore[attr-defined]
    srv.token = token                                 # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
