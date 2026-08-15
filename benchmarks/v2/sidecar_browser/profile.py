"""`rt-sidecar-browser-v1` —— 真上游 + 真浏览器的 Runtime Profile。

与 conformance canary 的分工:canary 用一个手造的 fixture 上游证明**机制**
成立(拓扑、四道谓词、八条攻击);这里换成**真 browser-use + 真 Chromium**,
证明同一套机制在真实上游上照样成立。

三处刻意的设计:

1. **身份从封存件的字节现算,不从子进程自述取。** `identity()` 直接哈封存
   runtime 里 `browser_use/` 的全部 .py —— harness 自己看得见那些字节,不必
   信任任何人的自报。子进程只负责跑浏览器。
2. **harness 进程不 import browser_use**(它也 import 不了 —— 在另一个 venv)。
   所以 loader 返回的是一个只带 `__file__`/`__version__` 的壳,给 `identity()`
   定位用。真正的执行在封存解释器里。
3. **浏览器路径只从清单取,绝不回落系统 Chrome。** 回落会让 runtime 悄悄
   不可复现 —— 系统 Chrome 自动更新,而封存这份浏览器的全部理由就是让它不变。
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from repoproof.execution.provisioning import (  # noqa: E402
    PROVISION_MARKER,
    RuntimeManifest,
    verify_sealed,
)
from repoproof.execution.runtime_profiles import RuntimeProfile, register_profile  # noqa: E402
from repoproof.execution.upstream_sidecar import (  # noqa: E402
    UpstreamExecutionError,
    UpstreamSpec,
)

PROFILE_ID = "rt-sidecar-browser-v1"
RUNTIME_ROOT = Path("~/RepoProofRuntimes").expanduser() / PROFILE_ID
WORKER = Path(__file__).resolve().parent / "worker.py"

DISTRIBUTION = "browser-use"
IMPORT_MODULE = "browser_use"
SYMBOL = "browser_use.BrowserSession.render"          # 契约要求的能力
OTHER_SYMBOL = "browser_use.BrowserSession.title_only"  # 真实存在但非契约所要


def available() -> tuple[bool, str]:
    """封存件在不在、完不完好。**不在就明说不在**,不静默降级。"""
    if not (RUNTIME_ROOT / PROVISION_MARKER).is_file():
        return False, ("尚未 provision —— 跑 "
                       "scripts/provision_browser_runtime.py --go")
    return verify_sealed(RUNTIME_ROOT)


def load_upstream():
    """给 `identity()` 用的壳:只带 `__file__` 与 `__version__`。

    harness 进程 import 不了 browser_use(它在另一个 venv),但**看得见它的
    字节** —— 身份该由字节决定,不由谁的自述决定。
    """
    site = next((RUNTIME_ROOT / ".venv" / "lib").glob("python*/site-packages"))
    init = site / IMPORT_MODULE / "__init__.py"
    ver = "?"
    for d in site.glob("browser_use-*.dist-info/METADATA"):
        for line in d.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Version: "):
                ver = line.split(" ", 1)[1].strip()
                break
    return types.SimpleNamespace(__file__=str(init), __version__=ver)


def _chromium() -> str:
    m = RuntimeManifest.load(RUNTIME_ROOT)
    exe = RUNTIME_ROOT / m.extras["chromium_executable"]
    if not exe.is_file():
        raise UpstreamExecutionError(
            f"封存的 Chromium 不在:{exe}(绝不回落系统 Chrome)")
    return str(exe)


def _run_worker(url: str) -> dict:
    req = json.dumps({"chromium": _chromium(), "url": url, "offline": True})
    r = subprocess.run([str(RUNTIME_ROOT / ".venv" / "bin" / "python"), str(WORKER)],
                       input=req, capture_output=True, text=True,      # noqa: S603
                       timeout=240, check=False)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:                                             # noqa: BLE001
        # S1:worker 说不出话 = **上游侧**故障,不是被测方的错。
        raise UpstreamExecutionError(
            f"worker 输出读不出({e}):{r.stdout[-300:]} / {r.stderr[-300:]}") from e
    if "error" in out:
        raise UpstreamExecutionError(f"worker 失败:{out['error']}")
    return out


def _url_of(payload) -> str:
    """入参形状与共用 client 一致(`{"text": ...}`)。

    也认 `{"url": ...}` —— 但**不猜**:两个键都没有就报错。猜的话,一个打错
    的键会变成"渲染了空地址"然后在 U4 上红,而真正的原因是入参对不上,
    两者的修法完全不同。
    """
    if isinstance(payload, dict):
        for k in ("text", "url"):
            if payload.get(k):
                return str(payload[k])
        raise ValueError(f"入参里没有 text/url:{sorted(payload)}")
    return str(payload)


def _render(payload) -> str:
    """契约要求的能力:真渲染,返回排版引擎算出的答案。"""
    return _run_worker(_url_of(payload))["answer"]


def _title_only(payload) -> str:
    """真实存在的另一项能力,**不是**契约要的那一项(调错 symbol 的靶子)。"""
    return _run_worker(_url_of(payload))["title"]


SPEC = UpstreamSpec(DISTRIBUTION, IMPORT_MODULE,
                    {SYMBOL: _render, OTHER_SYMBOL: _title_only},
                    loader=load_upstream)

# lifecycle:**qualified**(2026-08-15 晋级,G1–G7 全过,留痕见
# `docs/evidence/profile_lifecycle/promotions.jsonl`)。
#
# candidate 那一级的含义是"机制在真上游上站得住"—— 拓扑五条、诚实实现不被
# 误杀、八条攻击各红各位、变异全捕。**不含**"真模型跑得动":我们的 adapter
# 是照着判据写的,那叫出题人自己会做。
#
# qualified 补上的正是这一条:预注册批 PQ-T3SIDECAR-1(4 发,gpt-5.5/5.6
# 交替)四发全部 PASS_ADAPTED 且回执四道谓词全过。**仍不含**"这个拓扑更好"
# —— 那要 WH/HB 对照,第二宿主还没建;也不含任何模型能力结论
# (counts_toward_model_capability: false,判据是我们自己出的)。
PROFILE = register_profile(RuntimeProfile(
    id=PROFILE_ID, topology="sidecar", lifecycle="qualified",
    summary="真 browser-use 0.13.7 + 封存 Chromium;agent 只能经 RPC 请它渲染",
    upstream=SPEC, required_symbols=frozenset({SYMBOL}), default_symbol=SYMBOL))
