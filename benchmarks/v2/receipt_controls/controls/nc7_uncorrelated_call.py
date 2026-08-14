"""负控 7:**上游调用完成了,但最终输出与调用结果没有因果关系**。

它老老实实调了 sidecar —— 真上游、真 render、真回执。但喂进去的是一段
**无关的**文本(一句占位),而交付的是它自己渲染的真作业。

与 nc3 的区别:nc3 输入是对的、结果被丢掉;nc7 连输入都是假的。所以两者
红在不同的地方 —— nc7 红在 U3(待办单元的 input digest 对不上),nc3 红在
U4。**两条负控各红一处,这正是"红一片的负控不算数"要的那种判别力**:
如果它们红在同一处,就说明我们其实只有一道判据,却给它起了四个名字。
"""
EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}

FILLER = "# placeholder\n\nnothing to do with the real job\n"


def _own_render(text: str) -> str:
    return "".join(f"<span>{ln}</span>\n" for ln in text.splitlines() if ln.strip())


def run(sidecar, jobs):
    out = []
    for job in jobs:
        sidecar.invoke(FILLER, request_nonce=job["request_nonce"])   # 输入无关
        out.append(_own_render(job["text"]))
    return out
