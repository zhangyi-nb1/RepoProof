"""**调错 symbol** → FAIL。

调的是真上游、真浏览器、输入也对,但用的是 `title_only` 而不是契约要求的
`render`。"用了这个上游"和"用了这个上游的这项能力"是两件事。
"""
EXPECT = "FAIL"
EXPECT_RED = {"U2.symbol", "U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    return [sidecar.invoke(j["text"], request_nonce=j["request_nonce"],
                           symbol="browser_use.BrowserSession.title_only")["result"]
            for j in jobs]
