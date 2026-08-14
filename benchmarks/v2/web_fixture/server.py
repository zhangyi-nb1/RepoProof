"""本地网页 fixture —— **完全离线**的测试站点。

它承担的角色,与 conformance canary 里那撮"盐"是同一个:让**不可重实现**
成立。否则"agent 自己重实现"那条负控会因为输出恰好相同而在 U4 上蒙混过去,
采纳判据在这套 fixture 上就没有判别力,而我们恰恰是拿它来证明采纳判据管用。

**关键值只有真渲染才拿得到。** 页面里的答案 = f(服务端 nonce, 布局测量):

    布局测量取自 flex 分数分配的实际像素宽(读到小数位)。它是**排版引擎
    算出来的**,不在 HTML 文本里 —— 纯 HTTP 抓页面拿到的是 CSS 和一个空
    占位符,拿不到这个数。

诚实的强度边界(写清楚,免得被读成比实际更强):

- 它挡的是"抓 HTML 就想交差";**连朴素重算也挡得住**(实测,非推测):
  容器 1000px、flex 分数 3/5/7/11/13,朴素算法给出的数学值与 Chromium 实测
  逐个不同 ——

      flex     朴素 1000*p/39      Chromium 实测      差
        3        76.9231            76.9219        0.0012
        5       128.2051           128.2188        0.0137
        7       179.4872           179.4844        0.0028
       11       282.0513           282.0469        0.0044
       13       333.3333           333.3281        0.0052

  五个数**全部**对不上:排版引擎用定点 LayoutUnit 并按自己的方式分配余量,
  那不是一句除法能复现的。要复现就得复现 flex 布局算法本身 —— 那已经是
  **重写浏览器**,正是 R12 明令禁止的那件事。判据不必比契约更严。
- 数值的稳定性依赖**浏览器被钉死**。这正好是封存那份 Chromium 的又一个理由:
  换个 build,分数分配的舍入可能就变了。所以 fixture 的期望值不写死在代码里,
  由 harness 在**同一份封存浏览器**上现算一次作为基准。
- 不用 canvas 指纹(GPU 相关)、不用字体测量(字体可得性因机器而异)——
  那两样会把"环境差异"混进"是否真渲染"里。flex 分数分配只依赖排版引擎本身。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 分母刻意取质数且不能整除容器宽,好让分数分配产生长小数 —— 整数结果太容易
# 被"随手猜一个"蒙对,那样这道判据的判别力就靠运气了。
CONTAINER_PX = 1000
FLEX_PARTS = (3, 5, 7, 11, 13)

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>RepoProof web fixture</title>
<style>
  html,body {{ margin:0; padding:0; }}
  #box {{ width:{w}px; display:flex; }}
  #box > div {{ height:10px; }}
  {rules}
</style></head>
<body>
<h1>RepoProof offline fixture</h1>
<p id="nonce" data-nonce="{nonce}">nonce: {nonce}</p>
<div id="box">{cells}</div>
<!-- 答案不在 HTML 里:它由排版引擎算完之后,下面这段脚本写进 #answer -->
<p id="answer" data-answer="">answer: (needs rendering)</p>
<script>
(function () {{
  var parts = [];
  var cells = document.querySelectorAll('#box > div');
  for (var i = 0; i < cells.length; i++) {{
    parts.push(cells[i].getBoundingClientRect().width.toFixed(4));
  }}
  var el = document.getElementById('answer');
  var v = '{nonce}|' + parts.join(',');
  el.setAttribute('data-answer', v);
  el.textContent = 'answer: ' + v;
}})();
</script>
</body></html>
"""


def render_page(nonce: str) -> str:
    rules = "\n  ".join(
        f"#box > div:nth-child({i + 1}) {{ flex: {p}; background:#{i}{i}{i}; }}"
        for i, p in enumerate(FLEX_PARTS))
    cells = "".join("<div></div>" for _ in FLEX_PARTS)
    return PAGE.format(w=CONTAINER_PX, nonce=nonce, rules=rules, cells=cells)


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):                       # noqa: N802
        nonce = getattr(self.server, "nonce", "")          # type: ignore[attr-defined]
        if self.path.startswith("/health"):
            body = json.dumps({"ok": True, "nonce": nonce}).encode()
            ctype = "application/json"
        else:
            body = render_page(nonce).encode("utf-8")
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(nonce: str, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), _H)
    srv.nonce = nonce                                      # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
