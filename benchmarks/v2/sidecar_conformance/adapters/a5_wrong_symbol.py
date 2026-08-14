"""**调错 symbol** → FAIL。

调的是真上游、真进程、输入也对,但用的是 `fingerprint` 而不是契约要求的
`normalize`。

"用了这个上游"和"用了这个上游的这项能力"是两件事。契约要的是后者。
"""
EXPECT = "FAIL"
EXPECT_RED = {"U2.symbol", "U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    out = []
    for j in jobs:
        r = sidecar.invoke(j["text"], request_nonce=j["request_nonce"],
                           symbol="canary_upstream.transform.fingerprint")
        out.append(r["result"] + "\n")
    return out
