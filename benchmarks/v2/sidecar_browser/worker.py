#!/usr/bin/env python3
"""在**封存 runtime 的解释器里**执行的 worker —— 真上游 + 真浏览器。

它不是 sidecar 本体。sidecar 跑在 harness 的进程里(负责鉴权、记账、签回执),
真正的浏览器工作必须换到封存 venv 去做,因为 `browser_use` 与 Chromium 都在
那里、也只在那里。

读 stdin 的 JSON,写 stdout 的 JSON。**不碰台账、不碰密钥** —— 回执由 sidecar
在 harness 侧签发。worker 知道的越少越好:它连自己产出的东西会被拿去比对哪个
摘要都不知道。

它做的事:用封存的 Chromium 起一个 CDP 端点,让钉版 browser-use 接上去,
真渲染 fixture 页面,把排版引擎算出来的答案取回来。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _launch_chromium(exe: str, port: int, user_data: str, offline: bool):
    argv = [exe, "--headless=new", f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data}", "--no-first-run",
            "--no-default-browser-check", "--disable-gpu"]
    if offline:
        # 除本机外一律走死代理:证明这一步**不需要外网**。
        # bypass 留 127.0.0.1/localhost,fixture 才加载得到。
        argv += ["--proxy-server=127.0.0.1:1",
                 "--proxy-bypass-list=127.0.0.1;localhost;<local>"]
    return subprocess.Popen(argv, stdout=subprocess.DEVNULL,          # noqa: S603
                            stderr=subprocess.DEVNULL, start_new_session=True)


def _wait_cdp(port: int, timeout: float = 30.0) -> dict:
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                return json.loads(r.read().decode())
        except Exception as e:                                        # noqa: BLE001
            last = e
            time.sleep(0.3)
    raise RuntimeError(f"CDP 端点没起来:{last}")


async def _render(cdp_ws: str, url: str) -> dict:
    """用**真 browser-use** 打开页面并取回渲染后的答案。

    走 browser_use 的 BrowserSession + CDP 事件,而不是自己拿 websocket 说
    CDP —— 后者虽然也能拿到值,但那就绕过上游了,回执证明的东西会变味。
    """
    from browser_use import BrowserSession
    from browser_use.browser.profile import BrowserProfile

    session = BrowserSession(browser_profile=BrowserProfile(headless=True),
                             cdp_url=cdp_ws)
    await session.start()
    try:
        page = await session.get_or_create_cdp_session()
        await page.cdp_client.send.Page.navigate({"url": url},
                                                 session_id=page.session_id)
        # 等脚本把答案写进 DOM
        answer = ""
        for _ in range(60):
            r = await page.cdp_client.send.Runtime.evaluate(
                {"expression":
                 "document.getElementById('answer').getAttribute('data-answer')",
                 "returnByValue": True}, session_id=page.session_id)
            answer = (r.get("result") or {}).get("value") or ""
            if answer:
                break
            await asyncio.sleep(0.2)
        title = await page.cdp_client.send.Runtime.evaluate(
            {"expression": "document.title", "returnByValue": True},
            session_id=page.session_id)
        return {"answer": answer,
                "title": (title.get("result") or {}).get("value") or ""}
    finally:
        try:
            await session.kill()
        except Exception:                                             # noqa: BLE001
            pass


def main() -> int:
    req = json.loads(sys.stdin.read() or "{}")
    exe = req["chromium"]
    url = req["url"]
    offline = bool(req.get("offline", True))

    user_data = tempfile.mkdtemp(prefix="rp-browser-")
    port = _free_port()
    proc = _launch_chromium(exe, port, user_data, offline)
    try:
        ver = _wait_cdp(port)
        out = asyncio.run(_render(ver["webSocketDebuggerUrl"], url))
        out["browser"] = ver["Browser"]
        import importlib.metadata as md

        out["browser_use_version"] = md.version("browser-use")
        print(json.dumps(out, ensure_ascii=False))
        return 0
    except Exception as e:                                            # noqa: BLE001
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:                                             # noqa: BLE001
            proc.kill()
        shutil.rmtree(user_data, ignore_errors=True)
        os.close(os.open(os.devnull, os.O_RDONLY))


if __name__ == "__main__":
    raise SystemExit(main())
