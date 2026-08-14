"""负控 5:**重放上一次 run 的回执**。

它不调本次的 sidecar,而是把上一轮留下的整本台账原样搬过来 —— 那些回执
签名有效、哈希链完整、上游身份正确、连输出内容都是真上游产的。

唯一不对的是 `run_nonce` 不是本次的。这条负控证明:回执必须**绑定到这一
次运行**,否则"曾经有人真的调用过"就能一直复用下去。

实现方式:本控制组由 runner 特殊处理 —— 它需要一本上一轮的台账,这不是
adapter 代码能表达的东西(adapter 连台账路径都不知道)。runner 会把上一轮
的台账拷进本轮位置,再跑这个 adapter 的输出。
"""
EXPECT = "FAIL"
# runner 会**沿用上一轮的密钥**跑这条 —— 否则签名先挂,nonce 那道走不到,
# 这条负控就变成在考密钥轮换。签名绿、nonce 红,才是把它单独拎出来考。
EXPECT_RED = {"U1.run_nonce", "U3.coverage", "U4.adoption"}
NEEDS_REPLAYED_LEDGER = True


def run(sidecar, jobs):
    # 不调 sidecar —— 全靠那本搬来的旧账。交付用的是旧账里那次真调用的产物,
    # 所以内容甚至是"对的";错的是它不属于这一次运行。
    import os

    from repoproof.receipts.ledger import read_ledger
    old = read_ledger(os.environ["REPOPROOF_REPLAY_SOURCE"])
    return [r.output.preview for r in old][:len(jobs)] or [""] * len(jobs)
