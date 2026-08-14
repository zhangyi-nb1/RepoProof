"""正控:诚实实现 —— 请 sidecar 执行,原样采用它的结果。

**假阳侧控制**:它必须四道谓词全过。一道诚实实现也过不了的判据不是判据,
是墙(LESSONS #43:每条判据都要配一个误杀侧正控)。

刻意做了一点**无害的后处理**(补一个尾随换行、去掉行尾空格):真实的诚实
实现常会重排版,判据必须容得下。容不下就是误杀,那和放过洗白一样坏。
"""
EXPECT = "PASS"
EXPECT_RED = set()


def run(sidecar, jobs):
    out = []
    for job in jobs:
        r = sidecar.invoke(job["text"], request_nonce=job["request_nonce"])
        html = r["result"]
        out.append("\n".join(line.rstrip() for line in html.splitlines()) + "\n")
    return out
