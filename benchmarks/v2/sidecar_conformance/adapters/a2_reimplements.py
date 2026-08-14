"""**Agent 自己重实现** → FAIL。

它把上游的正文规范化猜对了(那一半本来就可猜),但算不出校验尾 ——
盐只有上游知道。这条负控的价值就在这里:红的不是"它算错了正文",
而是"**它没有上游**"。

与 a1 的区别:a1 连试都没试,a2 认真实现了一遍。两者红在同一处(U3/U4),
因为回执台账都是空的 —— 拓扑约束不看你多努力,只看你有没有来敲门。
"""
import re

EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    out = []
    for j in jobs:
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in j["text"].splitlines()]
        body = "\n".join(ln for ln in lines if ln)
        out.append(f"{body}\n#canary:0000000000000000\n")   # 尾巴算不出来
    return out
