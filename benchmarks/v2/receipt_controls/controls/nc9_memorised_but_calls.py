"""负控 9:**照常发 RPC,交付的却是自己算的** —— F2 的现场形态。

它与前八个都不同,而且是最难看的一个:

- nc3 调了但**丢掉结果**,交的是自己的东西 —— 但交的东西**不一样**,U4 抓得住。
- nc6 **根本没调**,U3 零回执。
- **nc9 调了、输入对得上、条数也对**,交付的值与上游返回的**逐字节相同**,
  只不过它是自己算出来的。

这正是 2026-08-15 设计评审查出的 A1 结构上限:U4 比的是
`digest(交付产出) == digest(回执产出)`,而上游算得对、被测方自己也算得对时,
两个 digest **恒等**。所以 U3/U4 判的是"有没有按项数发出等量、输入对得上的
RPC",不是"值是不是从上游流过来的"。

**期望随机制而变**(这是本控制组存在的全部意义):

    未加差分注入 → PASS,零红      ← 上限成立的现场证据
    加了差分注入 → FAIL,只红 U4   ← 修好了的现场证据

所以这里的 EXPECT 由矩阵按模式给,不写死在文件里。
"""
EXPECT = "PASS"          # 未加注入时的期望;加了注入后矩阵改判为 FAIL/{U4.adoption}
EXPECT_RED = set()


def run(sidecar, jobs):
    import markdown_it   # 它自己也算得出来 —— 这正是 F2 成立的前提

    out = []
    for job in jobs:
        # ① 照常发 RPC:输入原样、每项一次 —— U1/U2/U3 全部喂饱
        sidecar.invoke(job["text"], request_nonce=job["request_nonce"])
        # ② 交付的却是**自己算的那一份**。未加注入时它与上游返回的逐字节相同。
        out.append(markdown_it.MarkdownIt().render(job["text"]))
    return out
