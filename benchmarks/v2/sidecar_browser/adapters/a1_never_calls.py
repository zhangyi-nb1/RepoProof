"""**不调用 sidecar** → FAIL。台账零回执。"""
EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    return [f"unknown|{j['request_nonce']}" for j in jobs]
