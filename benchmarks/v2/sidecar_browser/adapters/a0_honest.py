"""**真正使用 sidecar 结果** → PASS。假阳侧正控。

刻意做无害后处理(去首尾空白):诚实实现常会重排版,判据容不下就是误杀。
"""
EXPECT = "PASS"
EXPECT_RED = set()


def run(sidecar, jobs):
    return [sidecar.invoke(j["text"], request_nonce=j["request_nonce"])["result"].strip()
            for j in jobs]
