"""DSH 预算 watchdog 与进程组强杀的钉死(DSH 阶段 4,ADR §6 预算长牙处)。

**冻结判据**(先写判据与反例,再写实现;措辞此后不改):

- G1 **超限即杀,杀整组**:请求数越限 → SIGKILL 进程组,worker 与它的
  孩子一起死,归因 `budget_overrun:<轴>`;**超限后 events 汇不再增长**
  ("无后台继续调用模型"是拓扑保证)。反例:只杀 worker 不杀组 ——
  runtime 成孤儿继续打模型,预算只约束了记账进程。
- G2 **墙钟同律**:wall 越限 → 同一把刀,归因 `wall_overrun`。反例:
  依赖 worker 自觉退出 —— 卡死的 runtime 恰恰不会自觉。
- G3 **不越权**:预算内正常结束 → 不杀,归因走 worker 自报(ok /
  worker_error:*),trace 对账平。反例:watchdog 顺手把干净发次也杀了,
  或把 worker 的错误归因覆盖成自己的。
- G4 **协议破点名**:stdout 不是恰好一行带 protocol 标识的 result →
  `worker_protocol_breach`。反例:拿日志第一行当 result 解析。

**假 worker 纪律**:全部自终结(≤4s)—— 执法变异(检查被打死)只能让
断言红,不许让闸门挂在 communicate 上等一个不会退出的进程。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from repoproof.agents.dsh_backend import DshBudget, run_dsh_worker

_EV = ('{"method":"session.event","payload":{"sessionId":"s","event":'
       '{"seq":%d,"time":0,"type":"%s","data":%s}}}')


def _fake(tmp: Path, body: str) -> Path:
    p = tmp / "fake_worker.py"
    p.write_text("import json,os,subprocess,sys,time\n"
                 "ev=os.environ['FAKE_EVENTS']\n" + body, encoding="utf-8")
    return p


def _job(tmp: Path) -> dict:
    (tmp / "ws").mkdir(exist_ok=True)
    return {"prompt": "x", "workspace": str(tmp / "ws"),
            "events_path": str(tmp / "evdir" / "events.jsonl"),
            "session_root": str(tmp / "sess"), "cordis": str(tmp / "ws")}


# 请求洪流:先起一个 argv 带记号的孩子(强杀必须连它一起),然后每 0.12s
# 一条 request/header,~4s 后自终结并给出合法单行 result。
_FLOOD = r"""
child=subprocess.Popen(["/bin/sh","-c","exec sleep 300 # "+ev],
    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)  # 不攥父管道:
    # 否则执法变异世界里 worker 退了孩子还举着写端,communicate 等满 300s
os.makedirs(os.path.dirname(ev),exist_ok=True)
f=open(ev,"a")
f.write('{"method":"session.event","payload":{"sessionId":"s","event":{"seq":0,"time":0,"type":"turn/start","data":{"turn":1}}}}\n');f.flush()
for i in range(1,30):
    f.write('{"method":"session.event","payload":{"sessionId":"s","event":{"seq":%d,"time":0,"type":"request/header","data":{}}}}\n'%i);f.flush()
    time.sleep(0.12)
print('{"protocol":"dsh-worker-v1","ok":true,"error_kind":null}')
"""


def test_g1_request_overrun_kills_group_and_stops_growth(tmp_path: Path) -> None:
    job = _job(tmp_path)
    fake = _fake(tmp_path, _FLOOD)
    r = run_dsh_worker(job, worker_python=sys.executable,
                       budget=DshBudget(max_logical_requests=3),
                       extra_env={"FAKE_EVENTS": job["events_path"]},
                       worker_argv=[sys.executable, str(fake)])
    assert r.attribution == "budget_overrun:logical_requests"
    assert r.killed and r.orphan_count == 0
    # 超限后无后台继续:events 汇一秒内不得再长一字节
    size = Path(job["events_path"]).stat().st_size
    time.sleep(1.0)
    assert Path(job["events_path"]).stat().st_size == size, \
        "杀完 events 还在长 —— 有进程活着继续跑"
    # 孩子也必须死:记号进程一个不剩
    got = subprocess.run(["pgrep", "-f", job["events_path"]],
                         capture_output=True, text=True)
    assert got.returncode != 0, f"进程组没杀干净:{got.stdout}"


def test_g2_wall_overrun_same_knife(tmp_path: Path) -> None:
    job = _job(tmp_path)
    fake = _fake(tmp_path, "time.sleep(4)\n"
                 "print('{\"protocol\":\"dsh-worker-v1\",\"ok\":true}')\n")
    t0 = time.monotonic()
    r = run_dsh_worker(job, worker_python=sys.executable,
                       budget=DshBudget(max_wall_seconds=1.2),
                       extra_env={"FAKE_EVENTS": job["events_path"]},
                       worker_argv=[sys.executable, str(fake)])
    assert r.attribution == "wall_overrun" and r.killed
    assert time.monotonic() - t0 < 3.5, "墙钟刀没在限内落下"


def test_g3_clean_run_not_touched(tmp_path: Path) -> None:
    job = _job(tmp_path)
    body = (
        "os.makedirs(os.path.dirname(ev),exist_ok=True)\n"
        "f=open(ev,'a')\n"
        f"f.write('{_EV % (0, 'turn/start', '{\"turn\":1}')}\\n')\n"
        f"f.write('{_EV % (1, 'turn/end', '{\"turn\":1}')}\\n')\n"
        "f.write('{\"method\":\"session.status\",\"payload\":"
        "{\"sessionId\":\"s\",\"status\":\"idle\"}}\\n');f.flush()\n"
        "print('{\"protocol\":\"dsh-worker-v1\",\"ok\":true,\"error_kind\":null}')\n")
    r = run_dsh_worker(_job(tmp_path) | job, worker_python=sys.executable,
                       budget=DshBudget(max_logical_requests=100,
                                        max_wall_seconds=30),
                       extra_env={"FAKE_EVENTS": job["events_path"]},
                       worker_argv=[sys.executable, str(_fake(tmp_path, body))])
    assert (r.attribution, r.killed) == ("ok", False)
    assert r.trace.ok, r.trace.problems
    assert r.selfcheck_problems == []
    assert r.result and r.result["ok"] is True


def test_g4_protocol_breach_named(tmp_path: Path) -> None:
    job = _job(tmp_path)
    fake = _fake(tmp_path, "print('日志混进来了')\n"
                 "print('{\"protocol\":\"dsh-worker-v1\",\"ok\":true}')\n")
    r = run_dsh_worker(job, worker_python=sys.executable,
                       extra_env={"FAKE_EVENTS": job["events_path"]},
                       worker_argv=[sys.executable, str(fake)])
    assert r.attribution == "worker_protocol_breach"
    assert r.result is None
