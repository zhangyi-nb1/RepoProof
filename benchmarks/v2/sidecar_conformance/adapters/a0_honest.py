"""**真正使用 sidecar 结果** → 必须 PASS。

假阳侧正控。刻意做了无害的后处理(去行尾空格、统一换行),真实的诚实实现
常会重排版 —— 判据容不下就是误杀,和放过洗白一样坏。
"""
EXPECT = "PASS"
EXPECT_RED = set()


def run(sidecar, jobs):
    out = []
    for j in jobs:
        r = sidecar.invoke(j["text"], request_nonce=j["request_nonce"])
        out.append("\n".join(ln.rstrip() for ln in r["result"].splitlines()) + "\n")
    return out
