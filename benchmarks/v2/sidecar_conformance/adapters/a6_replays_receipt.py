"""**replay 旧 receipt** → FAIL。

不调本次的 sidecar,把上一轮留下的整本台账原样搬过来 —— 签名有效、哈希链
完整、上游身份正确、连输出内容都是真上游产的。唯一不对的是 `run_nonce`
不属于本次。

runner 会**沿用上一轮的密钥**跑这条。否则签名先挂,`U1.run_nonce` 那道根本
走不到,这条负控就变成在考密钥轮换(第 6 步 nc5 的教训,与 M46a 同型)。
"""
EXPECT = "FAIL"
# `U1.count` 也红,而且是**这条负控最直接的信号**:本次 sidecar 一条都没写,
# 台账里却有 N 条。"台账里有执行方没写过的东西"比"nonce 不对"更早、更硬 ——
# 前者不需要读回执内容就成立。
EXPECT_RED = {"U1.run_nonce", "U1.count", "U3.coverage", "U4.adoption"}
NEEDS_REPLAYED_LEDGER = True


def run(sidecar, jobs):
    import os

    from repoproof.receipts.ledger import read_ledger

    old = read_ledger(os.environ["REPOPROOF_REPLAY_SOURCE"])
    return [r.output.preview for r in old][:len(jobs)] or [""] * len(jobs)
