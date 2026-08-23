"""In-process import 取证(M2-c · RFC-010 [D4] 弱档→运行时升级)。

静态 provenance 的结构上限:`import pdfplumber` 写在文件顶部、实现却
全自写 —— 零 import 检测对"装样子 import"束手无策(nc3 同型)。
本件把证据升到运行时:验收期(oracle/replay/regression)harness 在
**工具子进程**注入一个 sitecustomize hook:

    - sys.meta_path finder 侦测目标模块真被 import(事件行);
    - import 完成后对模块顶层公开函数包 wrapper，并对公开非异常类的
      实例化包 __new__，每次调用写一行回执(symbol / args 摘要 / seq /
      HMAC(secret, 载荷));
    - ledger 与 secret 都由 harness 现摇现注(run 期 env),hook 目录在
      run_dir(会话外)—— agent 的冻结交付摸不到。

威胁模型(如实):
  防得住 —— 装样子 import(零调用)、无协议知识的伪造(HMAC secret
  运行期才存在,冻结代码写不死)、砍账(计数核对);
  探测即自曝 —— 交付代码里出现 REPOPROOF_HOOK 字样由 run() 静态扫描
  判 INSTRUMENT_TAMPERED(闸门先教后杀:提示从不提 hook,正常实现
  不可能碰巧写出这个前缀);
  防不住(v1 边界,如实记) —— 同进程运行时反射窃取 secret 并按协议
  伪造:需要 agent 在不知道协议的前提下先探测(会自曝)。sidecar 拓扑
  仍是强档;本件把 in-process 从"静态足迹"抬到"运行时回执"。

交付期零注入:hook 只随验收 env 存在,导出的工具包纯净([D4] 双拓扑)。
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
from pathlib import Path

ENV_MODULE = "REPOPROOF_HOOK_MODULE"
ENV_LEDGER = "REPOPROOF_HOOK_LEDGER"
ENV_SECRET = "REPOPROOF_HOOK_SECRET"

# 交付代码静态扫描的自曝指纹(先教后杀的"杀"面;"教"面 = 提示从不提它,
# 正常实现不可能需要这个前缀)
PROBE_MARKER = "REPOPROOF_HOOK"

_SITECUSTOMIZE = r'''"""repoproof import-hook(harness 注入;验收期专用,交付期不存在)。"""
import hashlib
import hmac
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import sys


def _emit(ledger, secret, payload):
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    with open(ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"p": payload, "sig": sig}, ensure_ascii=False) + "\n")


def _install():
    module = os.environ.get("REPOPROOF_HOOK_MODULE", "")
    ledger = os.environ.get("REPOPROOF_HOOK_LEDGER", "")
    secret = os.environ.get("REPOPROOF_HOOK_SECRET", "")
    if not (module and ledger and secret):
        return
    state = {"seq": 0}
    wrapped_class_ids = set()

    def _record(kind, symbol, extra=None):
        state["seq"] += 1
        payload = {"kind": kind, "module": module, "symbol": symbol,
                   "seq": state["seq"], "pid": os.getpid()}
        if extra:
            payload.update(extra)
        try:
            _emit(ledger, secret, payload)
        except OSError:
            pass

    def _wrap_callables(mod, modname):
        for name in list(vars(mod)):
            if name.startswith("_"):
                continue
            obj = getattr(mod, name, None)
            # 只量目标模块自身定义的 API。typing.List 等从别处导入的
            # callable 若被换成函数代理，会破坏 List[T] 等正常语义。
            if getattr(obj, "__module__", None) != modname:
                continue
            if not callable(obj) or isinstance(obj, type(sys)):
                continue

            # 公开类 API(OpenCC 型)的真实实例化也属于上游调用。不能把
            # 类替换成函数代理，否则 isinstance/except 会被量具破坏；
            # 原类上只包 __new__，并继续排除异常类以保持 except 语义。
            if isinstance(obj, type):
                try:
                    if issubclass(obj, BaseException):
                        continue
                except TypeError:
                    continue
                if id(obj) in wrapped_class_ids:
                    continue
                original_new = getattr(obj, "__new__", object.__new__)

                def _make_new(sym, fn):
                    def _new(cls, *a, **kw):
                        digest = hashlib.sha256(
                            repr((a, sorted(kw.items())))[:2000].encode()
                        ).hexdigest()[:16]
                        _record("call", sym, {"args_sha": digest})
                        if fn is object.__new__:
                            return fn(cls)
                        return fn(cls, *a, **kw)

                    return staticmethod(_new)

                try:
                    setattr(obj, "__new__", _make_new(
                        f"{modname}.{name}", original_new))
                except (AttributeError, TypeError):
                    continue
                wrapped_class_ids.add(id(obj))
                continue

            def _make(sym, fn):
                def _proxy(*a, **kw):
                    digest = hashlib.sha256(
                        repr((a, sorted(kw.items())))[:2000].encode()
                    ).hexdigest()[:16]
                    _record("call", sym, {"args_sha": digest})
                    return fn(*a, **kw)

                try:
                    _proxy.__name__ = getattr(fn, "__name__", sym)
                    _proxy.__doc__ = getattr(fn, "__doc__", None)
                except (AttributeError, TypeError):
                    pass
                return _proxy

            try:
                setattr(mod, name, _make(f"{modname}.{name}", obj))
            except (AttributeError, TypeError):
                continue

    class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            # 前缀匹配覆盖子模块:dateutil 型"空壳顶层包"(顶层零公共
            # 函数,功能全在 dateutil.parser)只拦精确名会记零调用,
            # 把真用判成装样子(M4 实测)。payload 的 module 字段仍写
            # 声明模块 —— verify 侧过滤键不变。
            if fullname != module and not fullname.startswith(module + "."):
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
                def __getattr__(self, name):
                    # pkgutil.get_data / importlib.resources 等依赖原 loader
                    # 的扩展协议；代理必须完整转发，不能只保留 exec。
                    return getattr(inner, name)

                def create_module(self, s):
                    return inner.create_module(s) if hasattr(inner, "create_module") else None

                def exec_module(self, mod):
                    inner.exec_module(mod)
                    _record("import", getattr(mod, "__name__", fullname))
                    _wrap_callables(mod, getattr(mod, "__name__", fullname))

            spec.loader = _L()
            return spec

    sys.meta_path.insert(0, _Finder())


_install()
'''


def write_hook_dir(dest: Path) -> Path:
    """落 hook 目录(只含 sitecustomize.py);env 三键由调用方注入。"""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "sitecustomize.py").write_text(_SITECUSTOMIZE, encoding="utf-8")
    return dest


def verify_import_receipts(
    ledger: Path,
    secret: str,
    *,
    module: str,
    min_calls: int = 1,
) -> dict:
    """→ {ok, imports, calls, reason}。

    判据(v1,如实弱于 sidecar U3 的逐项对应):
      - 每行 HMAC 必须对(secret 现摇,伪造需预知协议+密钥);
      - import 事件 ≥1(模块真被载入);
      - call 事件 ≥ min_calls(装样子 import 在这里死)。
    ledger 缺失/为空 = 判不过 —— 沉默不是通过。"""
    ledger = Path(ledger)
    if not ledger.is_file():
        return {"ok": False, "imports": 0, "calls": 0,
                "reason": f"import-hook ledger 缺失:{ledger}(没量到 = 判死)"}
    imports = calls = 0
    for i, line in enumerate(ledger.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            body = json.dumps(row["p"], sort_keys=True, ensure_ascii=False)
            want = _hmac.new(secret.encode(), body.encode(),
                             hashlib.sha256).hexdigest()
        except (ValueError, KeyError, TypeError) as e:
            return {"ok": False, "imports": imports, "calls": calls,
                    "reason": f"回执第 {i} 行不可解析:{e}"}
        if not _hmac.compare_digest(want, row.get("sig", "")):
            return {"ok": False, "imports": imports, "calls": calls,
                    "reason": f"回执第 {i} 行 HMAC 不符 —— 伪造/篡改嫌疑"}
        p = row["p"]
        if p.get("module") != module:
            continue
        if p.get("kind") == "import":
            imports += 1
        elif p.get("kind") == "call":
            calls += 1
    if imports < 1:
        return {"ok": False, "imports": imports, "calls": calls,
                "reason": f"目标模块 {module} 从未被 import(运行时证据缺席)"}
    if calls < min_calls:
        return {"ok": False, "imports": imports, "calls": calls,
                "reason": (f"上游调用 {calls} 次 < 最低 {min_calls} —— "
                           "import 了但没真用(装样子 import)")}
    return {"ok": True, "imports": imports, "calls": calls, "reason": ""}


def scan_probe_marker(root: Path, changed_files: list[str]) -> list[str]:
    """交付文本里出现 REPOPROOF_HOOK 字样的文件清单(探测即自曝)。"""
    hits: list[str] = []
    rootp = Path(root)
    for rel in changed_files:
        p = rootp / rel
        if p.suffix not in (".py", ".txt", ".sh", ".toml", ".cfg", ".md"):
            continue
        try:
            if p.is_file() and PROBE_MARKER in p.read_text(
                    encoding="utf-8", errors="replace"):
                hits.append(rel)
        except OSError:
            continue
    return hits
