"""M7 强回执 · 验收期注入 managed-sidecar server 进程的取证件。

拓扑(与 import-hook 的「验收注入、交付纯净」同构,由 M7 supervisor 的
child-env 白名单**强制**后者):
  - 交付期:CLI → supervisor → server。supervisor 把子进程 PYTHONPATH 锁死
    为交付包路径,本件根本进不去 —— 交付进程零取证件,纯净由白名单保证。
  - 验收期:harness **绕过交付 supervisor 自己起 server**(同一份交付
    server 代码、会话 venv 解释器),PYTHONPATH 前置本 hook 目录 + 注入
    回执六键。sitecustomize 拦交付包的 `impl` 模块,包住 `extract` 单点:
    每次请求发一张**签名+哈希链**回执(receipts.model 的逐字节兼容格式,
    密钥 harness 现摇,交付代码写不死)。

证明力与诚实边界(v1):
  强回执证明 —— U1 这批账没被伪造/改写/砍尾;U2 处理请求的进程里加载着
  正版 pinned 上游(调用现场 `sys.modules[...].__file__` 实际字节指纹,
  不是自报);U3 每个下发输入各有对得上的回执;U4 交付链(真实
  CLI→supervisor→server)对同一输入的最终 stdout 与取证面 output 逐字节
  同源 —— CLI/supervisor 层换答案即杀。
  不证明 —— extract **内部**逐符号真调上游(wrapper 在 extract 边界外看
  不见内部);该层继续由 import-hook(min_calls 账)并行提供,两层叠加。

nonce 通道:M7 sidecar 协议冻结(request 只有 input_path/request_id),
不为取证改协议 —— harness 把每单元 nonce 编进 staging 文件名
`<nonce>__<原名>`,server 真读了那个路径,绑定即真实。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ENV_LEDGER = "REPOPROOF_RECEIPT_LEDGER"
ENV_KEY = "REPOPROOF_RECEIPT_KEY"
ENV_RUN_ID = "REPOPROOF_RECEIPT_RUN_ID"
ENV_RUN_NONCE = "REPOPROOF_RECEIPT_RUN_NONCE"
ENV_TARGET = "REPOPROOF_RECEIPT_TARGET"            # 交付包 impl 模块全名
ENV_UPSTREAM_MODULE = "REPOPROOF_RECEIPT_UPSTREAM_MODULE"
ENV_UPSTREAM_DIST = "REPOPROOF_RECEIPT_UPSTREAM_DIST"
ENV_COUNT_FILE = "REPOPROOF_RECEIPT_COUNT_FILE"    # 执行方自数条数(反截断)

NONCE_SEP = "__"

_SITECUSTOMIZE = r'''"""repoproof 强回执 hook(harness 验收期注入;交付期不存在)。

自包含:server 进程里没有 repoproof 可 import,签名/链/序列化逻辑在此
内联,格式与 repoproof.receipts.model 逐字节兼容(canonical json +
HMAC-SHA256 + prev_sha256 链)。
"""
import datetime as _dt
import hashlib
import hmac
import importlib.abc
import importlib.util
import json
import os
import sys
import uuid

_LEDGER = os.environ.get("REPOPROOF_RECEIPT_LEDGER", "")
_KEY = os.environ.get("REPOPROOF_RECEIPT_KEY", "")
_RUN_ID = os.environ.get("REPOPROOF_RECEIPT_RUN_ID", "")
_RUN_NONCE = os.environ.get("REPOPROOF_RECEIPT_RUN_NONCE", "")
_TARGET = os.environ.get("REPOPROOF_RECEIPT_TARGET", "")
_UP_MOD = os.environ.get("REPOPROOF_RECEIPT_UPSTREAM_MODULE", "")
_UP_DIST = os.environ.get("REPOPROOF_RECEIPT_UPSTREAM_DIST", "")
_COUNT_FILE = os.environ.get("REPOPROOF_RECEIPT_COUNT_FILE", "")

_STATE = {"prev": None, "count": 0}


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _bytes_digest(raw):
    return "bytes/raw:" + hashlib.sha256(raw).hexdigest()


def _upstream_identity():
    """调用现场的上游身份。模块不在场 = 字段留空 = U2 会杀(不造真)。"""
    ident = {"distribution": _UP_DIST, "version": "", "artifact_hash": "",
             "import_module": _UP_MOD}
    mod = sys.modules.get(_UP_MOD)
    f = getattr(mod, "__file__", None) if mod is not None else None
    if f and os.path.isfile(f):
        with open(f, "rb") as fh:
            ident["artifact_hash"] = hashlib.sha256(fh.read()).hexdigest()
    try:
        from importlib import metadata as _md
        ident["version"] = _md.version(_UP_DIST)
    except Exception:
        pass
    return ident


def _emit(input_path, result_text):
    name = os.path.basename(str(input_path))
    nonce = name.split("__", 1)[0] if "__" in name else ""
    try:
        with open(input_path, "rb") as fh:
            in_raw = fh.read()
    except OSError:
        in_raw = b""
    out_norm = (result_text or "").rstrip("\n").encode("utf-8")
    body = {
        "receipt_version": 1,
        "run_id": _RUN_ID,
        "upstream": _upstream_identity(),
        "operation": {"symbol": _TARGET + ".extract",
                      "invocation_id": str(uuid.uuid4())},
        "input": {"digest": _bytes_digest(in_raw), "size": len(in_raw),
                  "preview": ""},
        "output": {"digest": _bytes_digest(out_norm), "size": len(out_norm),
                   "preview": ""},
        "runtime": {"executor": "m7-acceptance-receipt-hook",
                    "process_identity": "pid:%d:%s" % (os.getpid(), sys.executable),
                    "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    "profile_id": "tool-sidecar-v3-acceptance"},
        "binding": {"run_nonce": _RUN_NONCE, "request_nonce": nonce,
                    "parent_invocation": None},
        "prev_sha256": _STATE["prev"],
        "receipt_signature": "",
        "extra": {},
    }
    signable = dict(body)
    signable.pop("receipt_signature", None)
    signable.pop("prev_sha256", None)
    try:
        key = bytes.fromhex(_KEY)       # harness 以 hex 注入原始密钥字节
    except ValueError:
        key = _KEY.encode("utf-8")
    body["receipt_signature"] = hmac.new(
        key, _canonical(signable), hashlib.sha256).hexdigest()
    line = json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    try:
        with open(_LEDGER, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        _STATE["prev"] = hashlib.sha256(line.encode("utf-8")).hexdigest()
        _STATE["count"] += 1
        if _COUNT_FILE:
            with open(_COUNT_FILE, "w", encoding="utf-8") as fh:
                fh.write(str(_STATE["count"]))
    except OSError:
        # 账写不出去 → verify 侧账缺失/计数不符判死(fail-closed),
        # 量具故障不拖垮被测调用本身。
        pass


def _wrap(mod):
    orig = getattr(mod, "extract", None)
    if orig is None or not callable(orig):
        return

    def extract(input_path):
        result = orig(input_path)
        _emit(input_path, result if isinstance(result, str) else "")
        return result

    extract.__name__ = getattr(orig, "__name__", "extract")
    extract.__doc__ = getattr(orig, "__doc__", None)
    mod.extract = extract


def _install():
    if not (_LEDGER and _KEY and _RUN_ID and _RUN_NONCE and _TARGET):
        return

    class _Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != _TARGET:
                return None
            sys.meta_path.remove(self)
            try:
                spec = importlib.util.find_spec(fullname)
            finally:
                sys.meta_path.insert(0, self)
            if spec is None or spec.loader is None:
                return None
            inner = spec.loader

            class _L(importlib.abc.Loader):
                def create_module(self, s):
                    if hasattr(inner, "create_module"):
                        return inner.create_module(s)
                    return None

                def exec_module(self, mod):
                    inner.exec_module(mod)
                    _wrap(mod)

                def get_data(self, path):          # 资源协议完整转发
                    return inner.get_data(path)     # (pyspellchecker 教训)

                def __getattr__(self, item):
                    return getattr(inner, item)

            spec.loader = _L()
            return spec

    sys.meta_path.insert(0, _Finder())


_install()
'''


def write_receipt_hook_dir(dest: Path) -> Path:
    """落 hook 目录(只含 sitecustomize.py);env 六键由调用方注入。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    return dest


def probe_upstream_identity(venv_python: Path, import_module: str,
                            distribution: str, *, timeout_s: int = 60) -> dict:
    """harness 侧的期望上游身份:用**会话 venv 自己的解释器**加载上游并算
    模块文件字节指纹 —— 与 hook 调用现场同一口径。回执里的现场指纹必须与
    这份期望逐位相等(U2),即「进程内加载的」=「盘上 pinned 安装的」。"""
    code = (
        "import hashlib, importlib, json, sys\n"
        f"m = importlib.import_module({import_module!r})\n"
        "f = getattr(m, '__file__', '') or ''\n"
        "h = hashlib.sha256(open(f, 'rb').read()).hexdigest() if f else ''\n"
        "try:\n"
        "    from importlib import metadata\n"
        f"    v = metadata.version({distribution!r})\n"
        "except Exception:\n"
        "    v = ''\n"
        "print(json.dumps({'artifact_hash': h, 'version': v}))\n"
    )
    r = subprocess.run([str(venv_python), "-c", code], capture_output=True,
                       text=True, timeout=timeout_s)
    if r.returncode != 0:
        raise RuntimeError(
            f"上游身份探针失败(exit={r.returncode}):{r.stderr[-300:]}")
    got = json.loads(r.stdout.strip().splitlines()[-1])
    return {"distribution": distribution, "import_module": import_module,
            "version": got["version"], "artifact_hash": got["artifact_hash"]}


def norm_output_digest(text: str) -> str:
    """交付面 stdout 与取证面 output 的统一摘要口径(rstrip 单侧换行)。"""
    raw = (text or "").rstrip("\n").encode("utf-8")
    return "bytes/raw:" + hashlib.sha256(raw).hexdigest()


def input_digest_of(raw: bytes) -> str:
    return "bytes/raw:" + hashlib.sha256(raw).hexdigest()
