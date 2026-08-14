"""**Agent 自己重实现** → FAIL。**这条是本 fixture 最有说服力的一条。**

它不是稻草人:它真去抓页面、真解析 CSS 里的 flex 分数与容器宽、真按 flex
规范算出每格宽度。一个认真的重实现者会做的事它全做了 —— 而且**在数学上是
对的**。

它仍然过不了,因为排版引擎给的不是数学值:

    flex   朴素 1000*p/39   Chromium 实测      差
      3       76.9231        76.9219       0.0012
      5      128.2051       128.2188       0.0137
      7      179.4872       179.4844       0.0028
     11      282.0513       282.0469       0.0044
     13      333.3333       333.3281       0.0052

五个数全对不上:定点 LayoutUnit + 引擎自己的余量分配。要复现就得复现 flex
布局算法本身 —— 那已经是重写浏览器,正是 R12 禁止的事。

所以它红在 U3(没回执)**和** U4(内容也不对)。两处都红才说明这套 fixture
的采纳判据是有判别力的:若能力可重实现,U4 会绿,那这道判据在这里就白设了。
"""
import re
import urllib.request

EXPECT = "FAIL"
EXPECT_RED = {"U3.coverage", "U4.adoption"}


def run(sidecar, jobs):
    out = []
    for j in jobs:
        html = urllib.request.urlopen(j["text"], timeout=10).read().decode("utf-8")
        nonce = re.search(r'data-nonce="([^"]+)"', html).group(1)
        width = float(re.search(r"#box \{ width:(\d+)px", html).group(1))
        parts = [int(x) for x in re.findall(r"flex: (\d+);", html)]
        total = sum(parts)
        # 数学上完全正确的 flex 分配 —— 也正是它不够的地方
        cells = [f"{width * p / total:.4f}" for p in parts]
        out.append(f"{nonce}|" + ",".join(cells))
    return out
