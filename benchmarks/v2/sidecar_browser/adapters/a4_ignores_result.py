"""**调了 sidecar 但不用结果** → FAIL。**整套设计的考题。**

真上游被真执行、真浏览器真渲染、符号对、每个单元各调一次、输入摘要一一对上
—— U1/U2/U3 全绿。唯一不对的是用的不是那个结果。必须**只红在 U4**。
"""
EXPECT = "FAIL"
EXPECT_RED = {"U4.adoption"}


def run(sidecar, jobs):
    out = []
    for j in jobs:
        sidecar.invoke(j["text"], request_nonce=j["request_nonce"])   # 结果丢掉
        out.append(f"{j['request_nonce']}|my-own-numbers")
    return out
