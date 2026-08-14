"""Harness 拥有的上游执行 sidecar —— A1 的执行侧本体。

**它住在 `execution/` 而不是 `receipts/`,是有意的。** 回执三件套
(`model`/`ledger`/`verify`)只负责验,归 `verifier` 面;sidecar 改变的是
**agent 能做什么** ——
上游从"装进它的 venv 由它自己调"变成"由 harness 持有、只能经 RPC 请它执行"。
那是执行拓扑的改变,是被测系统本身变了,归 `executor_semantics` 面。
分面按语义不按目录(判据 F3),但把一个执行面的模块塞进验证面的包里,
迟早会有人照目录归错 —— 所以让它住在语义所在的地方。

sidecar 上线 = **新的执行代际**,与既有发次**不可互比**(§2 规则 1)。

这就是它存在的理由:**"是否用了上游"从足迹推断变成执行拓扑约束**。

    足迹推断:看 sys.modules 有没有那个名字、工件里有没有那串字样 ——
              全都是 SUT 能自己供的东西(LESSONS #43 坑五)。
    拓扑约束:上游根本不在 agent 的进程/环境里。它要用,只能来敲这扇门;
              而每一次敲门,harness 都在自己的台账上记一笔它签了名的回执。

顺带绕开一个死结:钉版 wheelhouse 装不进 browser-use 的导入闭包(§4.1),
但 sidecar 是 **harness 自己的进程**,不受 agent 那套离线钉版约束。上游装在
谁那儿,是拓扑问题,不是可得性问题。

设计上刻意**与具体上游无关**:上游能力由 `UpstreamSpec` 声明,符号到可调用
对象的映射由任务侧提供。sidecar 只管三件事 —— 鉴权、执行、记账。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from repoproof.receipts.ledger import ReceiptLedger
from repoproof.receipts.model import (
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

_BOOT = time.time()


@dataclass(frozen=True)
class UpstreamSpec:
    """任务侧声明的上游能力面。

    `dispatch` 是**符号 → 可调用对象**的白名单。不在表里的符号一律拒绝执行
    —— 不是"执行了再说,反正 U2 会判" —— sidecar 是执行方,它不该替被测方
    执行契约之外的东西。U2 判的是**已发生的执行**对不对,拒绝的是**不该发生
    的执行**,两者都要有。
    """

    distribution: str
    import_module: str
    dispatch: dict[str, Callable[[Any], str]]
    # 上游怎么进到 harness 进程里。缺省是普通 import;harness 独占的 fixture
    # 需要显式挂路径,就给一个 loader。
    #
    # 为什么要有它:没有 loader 的话,`identity()` 只能靠"某个 dispatch 已经
    # 先跑过、顺手把路径挂上了"这种副作用才 import 得到 —— 顺序一变就炸,
    # 而且炸的地方是**算上游身份**,那是 U2 的全部依据。身份计算不该依赖
    # 别人的副作用。
    loader: Callable[[], Any] | None = None

    def identity(self) -> UpstreamIdentity:
        """**现场**从实际加载的模块算身份 —— 不读配置,不信自述。

        `artifact_hash` 哈的是包内全部 .py 的字节。自带同名包能骗过
        `__name__` 与 `__version__`(T3 批 13 连 `UPSTREAM_COMMIT` 都照抄
        了),骗不过这个。"""
        mod = self.loader() if self.loader is not None else __import__(self.import_module)
        root = Path(mod.__file__).resolve().parent
        h = hashlib.sha256()
        for f in sorted(root.rglob("*.py")):
            if "__pycache__" in f.parts:
                continue
            h.update(f.relative_to(root).as_posix().encode("utf-8"))
            h.update(f.read_bytes())
        return UpstreamIdentity(self.distribution,
                                getattr(mod, "__version__", "?"),
                                f"sha256:{h.hexdigest()}", self.import_module)


@dataclass
class SidecarHandle:
    server: ThreadingHTTPServer
    base_url: str
    token: str
    ledger_path: Path
    profile_id: str
    _key: bytes = field(repr=False, default=b"")

    def shutdown(self) -> None:
        self.server.shutdown()

    def receipts_written(self) -> int:
        """**执行方自己数的**条数 —— 与台账文件相互独立。

        为什么必须有:哈希链查得出改写、乱序、删中间行,**查不出尾部截断**
        (实测:删最后一行,链校验照样通过)。链只能证明"留下的这些是连续
        的",证明不了"没有被砍掉尾巴"。要证后者,得有一个**在台账之外**的
        计数 —— 那就是这个。
        """
        return int(getattr(self.server, "seq", 0))

    def agent_env(self) -> dict[str, str]:
        """交给 agent 的**全部**东西 —— 端点与令牌,仅此而已。

        刻意不给:台账路径、签名密钥、run_nonce。少了它们,agent 即便够到
        了台账文件也写不出验得过的行(nc8 实测)。这个方法存在的意义就是
        把"该给什么"写死在一处 —— 散落在调用点上迟早会有人顺手多塞一个。"""
        return {"REPOPROOF_SIDECAR_URL": self.base_url,
                "REPOPROOF_SIDECAR_TOKEN": self.token}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):            # 静音:不要 HTTP 噪声混进 run 输出
        pass

    def do_POST(self):                    # noqa: N802 —— BaseHTTPRequestHandler 的约定
        srv = self.server
        if self.headers.get("X-Sidecar-Token") != srv.token:              # type: ignore[attr-defined]
            return self._json(403, {"error": "bad token"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:                                            # noqa: BLE001
            return self._json(400, {"error": str(e)})

        spec: UpstreamSpec = srv.spec                                     # type: ignore[attr-defined]
        symbol = req.get("symbol") or srv.default_symbol                  # type: ignore[attr-defined]
        payload = req.get("input")
        request_nonce = req.get("request_nonce") or ""

        fn = spec.dispatch.get(symbol)
        if fn is None:
            return self._json(400, {"error": f"未支持的符号:{symbol}"})
        try:
            result = fn(payload)
        except Exception as e:                                            # noqa: BLE001
            return self._json(400, {"error": f"{type(e).__name__}: {e}"})

        with srv.lock:                                                    # type: ignore[attr-defined]
            srv.seq += 1                                                  # type: ignore[attr-defined]
            inv = f"inv-{srv.seq:04d}"                                    # type: ignore[attr-defined]
            srv.ledger.append(Receipt(                                    # type: ignore[attr-defined]
                receipt_version=RECEIPT_VERSION,
                run_id=srv.run_id,                                        # type: ignore[attr-defined]
                upstream=spec.identity(),
                operation=Operation(symbol, inv),
                input=Payload(digest_of(payload, canon=CANON_JSON),
                              size=len(json.dumps(payload, ensure_ascii=False)),
                              preview=str(payload)[:60]),
                output=Payload(digest_of(result, canon=CANON_TEXT_SQUASH),
                               size=len(result), preview=result[:60]),
                runtime=Runtime("sidecar", _process_identity(),
                                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                profile_id=srv.profile_id),               # type: ignore[attr-defined]
                binding=Binding(srv.run_nonce, request_nonce)))           # type: ignore[attr-defined]

        # 返回体里**不带**任何回执字段:没有签名、没有 nonce、没有台账位置。
        # adapter 唯一能做的就是用或不用这个 result —— 而用没用由 U4 判。
        return self._json(200, {"invocation_id": inv, "result": result})

    def _json(self, code: int, body: dict):
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _process_identity() -> str:
    return f"pid={os.getpid()}:boot={int(_BOOT)}:py={sys.executable}"


def start_sidecar(*, spec: UpstreamSpec, ledger_path: Path, key: bytes,
                  run_id: str, run_nonce: str, token: str, profile_id: str,
                  default_symbol: str, host: str = "127.0.0.1",
                  port: int = 0) -> SidecarHandle:
    """起一个 harness 拥有的 sidecar。返回的句柄**不交给 agent**。"""
    srv = ThreadingHTTPServer((host, port), _Handler)
    srv.spec = spec                                   # type: ignore[attr-defined]
    srv.ledger = ReceiptLedger(ledger_path, key)      # type: ignore[attr-defined]
    srv.run_id = run_id                               # type: ignore[attr-defined]
    srv.run_nonce = run_nonce                         # type: ignore[attr-defined]
    srv.token = token                                 # type: ignore[attr-defined]
    srv.profile_id = profile_id                       # type: ignore[attr-defined]
    srv.default_symbol = default_symbol               # type: ignore[attr-defined]
    srv.lock = threading.Lock()                       # type: ignore[attr-defined]
    srv.seq = 0                                       # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return SidecarHandle(srv, f"http://{host}:{srv.server_address[1]}",
                         token, Path(ledger_path), profile_id, key)
