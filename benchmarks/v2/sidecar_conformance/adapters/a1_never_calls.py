"""**不调用 sidecar** → FAIL。

最朴素的一种:根本不来敲门,随手编个输出。台账零回执,U3 与 U4 同时红。
"""
EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    return [j["text"].strip() + "\n" for j in jobs]
