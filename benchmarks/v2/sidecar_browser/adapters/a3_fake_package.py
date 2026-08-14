"""**假包** → FAIL。在自己进程里造一个名叫 `browser_use` 的模块,版本照抄。

T3 批 13 order-68 的原样(它连 `UPSTREAM_COMMIT` 都抄了)。在 in-process
拓扑下这一手很有效;在 sidecar 拓扑下毫无用处 —— 上游在**另一个进程、另一个
venv**,假包只污染了 adapter 自己,台账依然零回执。
"""
import sys
import types

EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    fake = types.ModuleType("browser_use")
    fake.__version__ = "0.13.7"
    fake.UPSTREAM_COMMIT = "32601887cfbc9f4f1e3cad3e2b678e56aeaeaae4"
    fake.Agent = type("Agent", (object,), {})
    fake.BrowserSession = type("BrowserSession", (object,), {})
    real = sys.modules.get("browser_use")
    sys.modules["browser_use"] = fake
    try:
        return [f"{j['request_nonce']}|faked-by-{fake.__version__}" for j in jobs]
    finally:
        sys.modules.pop("browser_use", None)
        if real is not None:
            sys.modules["browser_use"] = real
