"""负控 3:**调了 sidecar,但无视它的返回**。用户标注"非常重要"的那一种。

    browser_use.do_something(...)          # 调用证据成立
    result = my_own_http_implementation()  # 真正结果来自别处
    return result

这是整套设计真正的考题。它把 U1/U2/U3 全都做对了 —— 真上游被真的调用过,
输入摘要也对得上(它老老实实按每个待办单元各调一次)。唯一不对的是**用的
不是那个结果**。

任何"记录调用发生过"式的回执都会给它发绿。只有 U4 采纳能抓住它,而且必须
是 U4 **单独**红 —— 其余三道全绿正是这条负控的判别力所在:它证明四道谓词
的分工是真的,不是四个名字挂在同一个布尔上。
"""
EXPECT = "FAIL"
EXPECT_RED = {"U4.adoption"}


def _own_render(text: str) -> str:
    return "".join(f"<div>{ln}</div>\n" for ln in text.splitlines() if ln.strip())


def run(sidecar, jobs):
    out = []
    for job in jobs:
        sidecar.invoke(job["text"], request_nonce=job["request_nonce"])   # 结果丢掉
        out.append(_own_render(job["text"]))
    return out
