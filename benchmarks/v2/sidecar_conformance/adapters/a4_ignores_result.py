"""**调一次 sidecar 但不用结果** → FAIL。**这是整套设计的考题。**

    upstream.normalize(x)        # 调用证据成立
    return my_own_impl(x)        # 真正的结果来自别处

它把 U1/U2/U3 全做对了:真上游被真执行、符号对、每个待办单元各调一次、
输入摘要一一对上。唯一不对的是**用的不是那个结果**。

任何"记录调用发生过"式的回执都会给它发绿。必须**只红在 U4** —— 其余三道
全绿正是它的判别力所在:它证明四道谓词的分工是真的,不是四个名字挂在同一
个布尔上。
"""
EXPECT = "FAIL"
EXPECT_RED = {"U4.adoption"}


def run(sidecar, jobs):
    out = []
    for j in jobs:
        sidecar.invoke(j["text"], request_nonce=j["request_nonce"])   # 结果丢掉
        out.append(j["text"].strip() + "\n#canary:1111111111111111\n")
    return out
