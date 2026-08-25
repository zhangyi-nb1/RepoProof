"""DSH minimal 组合的独立进程 worker(DSH 阶段 3,ADR §4 不可信执行平面)。

**运行位置**:封存 runtime 的 venv(`rt-dsh-minimal-0.1.0rc6-v1/.venv/bin/python`),
那里只有 `deepseek_harness` + 标准库 —— 本文件**不得 import repoproof**,
裁决平面对 worker 拓扑不可见(ADR §4:oracle/verifier/ledger 不挂载)。

**协议**(dsh-worker-v1):
- stdin:单个 JSON job spec(全部路径必须绝对路径;见 `_load_job`);
- stdout:恰好一行 result JSON(`protocol/ok/error_kind/...`),其余一律 stderr;
- events_path:宿主侧原始通知汇(JSONL 逐行 flush)—— 这是**可信记录**,
  DSH 自己的 session JSONL(session_root 下)只作诊断,不作证据;
- 退出码:0 正常;2 job spec 破;3 harness 层错误;4 意外异常;143 被父杀。

**边界**:
- 墙钟与总预算由父进程(RepoProof 侧)经进程组强杀执法,worker 不自设墙钟;
- API key 只经进程环境继承(AI 不经手密钥;不接受 job spec 传 key,
  不落 argv/日志/result);stderr 尾巴回带前做一次值级 redact;
- `final_response` 仅诊断 —— 任何字段都不产生 PASS(裁决属 Completion Gate)。
"""

from __future__ import annotations

import json
import os
import signal
import sys
import uuid
from pathlib import Path

PROTOCOL = "dsh-worker-v1"

_REQUIRED_ABS = ("workspace", "events_path", "session_root", "cordis")


class JobSpecError(ValueError):
    pass


def _load_job(raw: str) -> dict:
    try:
        job = json.loads(raw)
    except json.JSONDecodeError as e:
        raise JobSpecError(f"stdin 不是 JSON:{e}") from e
    if not isinstance(job, dict):
        raise JobSpecError("job spec 必须是 JSON object")
    if not isinstance(job.get("prompt"), str) or not job["prompt"]:
        raise JobSpecError("缺 prompt(非空字符串)")
    for key in _REQUIRED_ABS:
        v = job.get(key)
        if not isinstance(v, str) or not v:
            raise JobSpecError(f"缺 {key}")
        if not Path(v).is_absolute():
            raise JobSpecError(f"{key} 必须是绝对路径:{v}")
    ws = Path(job["workspace"])
    if not ws.is_dir():
        raise JobSpecError(f"workspace 不存在或不是目录:{ws}")
    cordis = Path(job["cordis"])
    if not cordis.is_file():
        raise JobSpecError(f"cordis 配置不存在:{cordis}")
    if "api_key" in job or "DEEPSEEK_API_KEY" in (job.get("env") or {}):
        # 铁律:key 只经进程环境继承,不经 job spec(不落 stdin/argv/日志)
        raise JobSpecError("job spec 不接受 api_key/DEEPSEEK_API_KEY;key 只经进程环境注入")
    env = job.get("env") or {}
    if not (isinstance(env, dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())):
        raise JobSpecError("env 必须是 str→str 映射")
    return job


def _redact(lines: list[str]) -> list[str]:
    """值级 redact:任何行含 key 值本体 → 打码。不打印、不比对前缀。"""
    secret = os.environ.get("DEEPSEEK_API_KEY", "")
    if len(secret) < 8:
        return lines
    return [ln.replace(secret, "«REDACTED»") for ln in lines]


def _emit(result: dict, code: int) -> int:
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return code


def _base_result(job: dict | None, session_id: str | None) -> dict:
    return {
        "protocol": PROTOCOL,
        "ok": False,
        "error_kind": None,
        "error": None,
        "session_id": session_id,
        "final_response": None,   # 仅诊断;不产生 PASS
        "finish_reason": None,
        "counts": None,
        "session_root": (job or {}).get("session_root"),
        "runtime_stderr_tail": [],
    }


def run(job: dict) -> tuple[dict, int]:
    from deepseek_harness import DeepSeekHarness, DeepSeekHarnessConfig

    # 错误族在子模块;顶层只出口 SdkProtocolError(0.1.0rc6 实测)。
    from deepseek_harness.errors import (
        HarnessError,
        JsonRpcError,
        SdkProtocolError,
        TransportClosedError,
    )

    session_id = job.get("session_id") or f"dshw-{uuid.uuid4().hex}"
    result = _base_result(job, session_id)

    env = dict(job.get("env") or {})
    if job.get("model"):
        env.setdefault("DSH_MODEL", str(job["model"]))
    if job.get("system_prompt"):
        env.setdefault("DSH_SYSTEM_PROMPT", str(job["system_prompt"]))

    cfg = DeepSeekHarnessConfig(
        model=str(job.get("model") or "deepseek-v4-flash"),
        max_tokens=job.get("max_tokens"),
        cwd=job["workspace"],
        session_root=job["session_root"],
        cordis=job["cordis"],
        env=env,
        request_timeout_seconds=job.get("request_timeout_seconds"),
    )

    events_path = Path(job["events_path"])
    events_path.parent.mkdir(parents=True, exist_ok=True)
    n_notifications = 0

    harness = DeepSeekHarness(cfg)
    try:
        with events_path.open("a", encoding="utf-8") as sink:
            def _pump(n) -> None:
                nonlocal n_notifications
                n_notifications += 1
                sink.write(json.dumps({"method": n.method, "payload": n.payload},
                                      ensure_ascii=False) + "\n")
                sink.flush()

            rr = harness.run(job["prompt"], session_id=session_id,
                             on_notification=_pump)
        result.update({
            "ok": True,
            "final_response": rr.final_response,
            "finish_reason": rr.finish_reason,
            "counts": {
                "notifications": n_notifications,
                "events": len(rr.events),
                "assistant_messages": sum(
                    1 for e in rr.events if e.get("type") == "assistant/message"),
                "turn_ends": sum(
                    1 for e in rr.events if e.get("type") == "turn/end"),
            },
        })
        return result, 0
    except TransportClosedError as e:
        result.update({"error_kind": "transport_closed", "error": str(e)})
    except JsonRpcError as e:
        result.update({"error_kind": "jsonrpc_error", "error": str(e)})
    except SdkProtocolError as e:
        result.update({"error_kind": "protocol_error", "error": str(e)})
    except HarnessError as e:
        result.update({"error_kind": "harness_error", "error": str(e)})
    finally:
        tail = list(getattr(harness.client, "_stderr_lines", []) or [])[-30:]
        result["runtime_stderr_tail"] = _redact([str(x) for x in tail])
        harness.close()   # 同发不留孤儿:runtime 子进程随 close 收割
    return result, 3


def main() -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    raw = sys.stdin.read()
    try:
        job = _load_job(raw)
    except JobSpecError as e:
        r = _base_result(None, None)
        r.update({"error_kind": "bad_job_spec", "error": str(e)})
        return _emit(r, 2)
    try:
        result, code = run(job)
        return _emit(result, code)
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 —— 意外异常也必须落一行 result
        r = _base_result(job, None)
        r.update({"error_kind": "unexpected", "error": f"{type(e).__name__}: {e}"})
        return _emit(r, 4)


if __name__ == "__main__":
    sys.exit(main())
