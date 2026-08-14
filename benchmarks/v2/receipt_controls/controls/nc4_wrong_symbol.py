"""负控 4:**调错上游方法**。

调的是真上游、真进程、输入也对,但用的是 `parse` 而不是契约要求的
`render` —— 拿到 token 流之后自己拼 HTML。

"用了这个库"和"用了这个库的这项能力"是两件事。契约要的是后者。
"""
import json

EXPECT = "FAIL"
# 三处一起红是**设计的级联**,不是判据糊在一起:符号不在要求集里的回执
# 进不了可信集,于是它既凑不了覆盖率(U3)也背不了书(U4)。"不可信的回执
# 不得参与任何后续判定"这条正是 M49e 那次逃逸补上的性质。
EXPECT_RED = {"U2.symbol", "U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    out = []
    for job in jobs:
        r = sidecar.invoke(job["text"], request_nonce=job["request_nonce"],
                           symbol="markdown_it.MarkdownIt.parse")
        types_ = json.loads(r["result"])
        out.append("".join(f"<!--{t}-->\n" for t in types_))
    return out
