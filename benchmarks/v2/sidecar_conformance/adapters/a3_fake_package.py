"""**假包** → FAIL。

在自己进程里造一个名叫 `canary_upstream` 的模块,版本号照抄 —— T3 批 13
order-68 的原样(它连 `UPSTREAM_COMMIT` 都抄了)。

在 in-process 拓扑下这一手很有效:任何"包在不在场"式的检查都过。
在 sidecar 拓扑下它一点用都没有 —— 假包只污染了 adapter 自己的进程,
上游在**另一个进程**里,台账依然零回执。**名字可以自称,跨进程的执行
事实不能。**
"""
import sys
import types

EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    fake = types.ModuleType("canary_upstream")
    fake.__version__ = "1.0.0"                       # 照抄真版本
    fake.UPSTREAM_ID = "repoproof-canary-upstream"
    tr = types.ModuleType("canary_upstream.transform")
    tr.normalize = lambda t: t.strip() + "\n#canary:deadbeefdeadbeef\n"
    fake.transform = tr
    real = sys.modules.get("canary_upstream")
    sys.modules["canary_upstream"] = fake
    sys.modules["canary_upstream.transform"] = tr
    try:
        return [fake.transform.normalize(j["text"]) for j in jobs]
    finally:
        for k in ("canary_upstream", "canary_upstream.transform"):
            sys.modules.pop(k, None)
        if real is not None:
            sys.modules["canary_upstream"] = real
