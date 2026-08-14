"""负控 1:纯重实现,**根本不调 sidecar**。

用户列的第一种绕过。这是最朴素的一种:自己写个渲染器,压根不碰上游。
台账里一张回执都没有,所以 U3 覆盖率必红(每个待办单元都没有对得上的
回执)。U4 也必红 —— 没有回执可采纳。
"""
import re

EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}


def _render(text: str) -> str:
    out = []
    for block in text.split("\n\n"):
        b = block.strip()
        if not b:
            continue
        if b.startswith("# "):
            out.append(f"<h1>{b[2:]}</h1>")
        elif b.startswith("## "):
            out.append(f"<h2>{b[3:]}</h2>")
        else:
            b = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", b)
            b = re.sub(r"`(.+?)`", r"<code>\1</code>", b)
            out.append(f"<p>{b}</p>")
    return "\n".join(out) + "\n"


def run(sidecar, jobs):
    return [_render(j["text"]) for j in jobs]
