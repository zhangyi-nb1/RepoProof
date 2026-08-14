"""**replay 旧 receipt** → FAIL。

搬上一轮的整本台账:签名有效、链完整、上游身份正确、输出也是真渲染产的。
唯一不对的是 `run_nonce` 不属于本次。runner 沿用上一轮密钥跑这条,否则签名
先挂、nonce 那道走不到(第 6 步 nc5 的教训)。
"""
EXPECT = "FAIL"
EXPECT_RED = {"U1.run_nonce", "U1.count", "U3.coverage", "U4.adoption"}
NEEDS_REPLAYED_LEDGER = True


def run(sidecar, jobs):
    import os

    from repoproof.receipts.ledger import read_ledger

    old = read_ledger(os.environ["REPOPROOF_REPLAY_SOURCE"])
    return [r.output.preview for r in old][:len(jobs)] or [""] * len(jobs)
