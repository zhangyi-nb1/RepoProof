"""负控 2:**本地伪造同名包**,连版本号都照抄。

用户列的第二种绕过,也正是 T3 批 13 order-68 的原样 —— 交付自带一个名叫
`browser_use` 的包,`__version__` 与 `UPSTREAM_COMMIT` 都写死成真值。

这里把假包装进 `sys.modules`,于是任何"包在不在场"式的检查都过。它挡不住
的是:sidecar 是**独立进程**,假包只污染了 adapter 自己的进程;台账里依然
零回执。名字可以自称,跨进程的执行事实不能。
"""
import sys
import types

EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}


def _install_fake():
    fake = types.ModuleType("markdown_it")
    fake.__version__ = "4.2.0"          # 照抄真版本
    fake.__file__ = "<forged>/markdown_it/__init__.py"

    class MarkdownIt:
        def render(self, text):
            return "".join(f"<p>{ln}</p>\n" for ln in text.splitlines() if ln.strip())

    fake.MarkdownIt = MarkdownIt
    sys.modules["markdown_it"] = fake
    return fake


def run(sidecar, jobs):
    real = sys.modules.get("markdown_it")
    fake = _install_fake()
    try:
        return [fake.MarkdownIt().render(j["text"]) for j in jobs]
    finally:
        if real is not None:
            sys.modules["markdown_it"] = real
        else:
            sys.modules.pop("markdown_it", None)
