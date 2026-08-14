"""负控 6:**导入了真包,实际用的是复制实现**。

`import markdown_it` 真的执行了,模块真的在 `sys.modules` 里,版本号一查
就对 —— 任何"进程内模块可见"式的判据全过(T3 h7 的 v2 判据栽的就是这里)。

但渲染走的是一份**从上游拷出来再改过**的本地实现。跨进程的 sidecar 一次
没被调用,台账零回执。

它与 nc2 的区别值得留意:nc2 伪造了包,nc6 **没有伪造任何东西** —— 真包
确实在场、确实被导入。它只是没用。这说明"在场"从来就不是"被使用"。
"""
EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    import markdown_it  # 真包,真导入,真在 sys.modules
    assert markdown_it.__version__                  # 版本查得到

    def vendored_render(text: str) -> str:
        # 从上游拷出来的简化版:同样的思路,不同的字节
        html = []
        for para in text.split("\n\n"):
            p = para.strip()
            if not p:
                continue
            level = len(p) - len(p.lstrip("#"))
            if level:
                html.append(f"<h{level}>{p[level:].strip()}</h{level}>")
            else:
                html.append(f"<p>{p}</p>")
        return "\n".join(html) + "\n"

    return [vendored_render(j["text"]) for j in jobs]
