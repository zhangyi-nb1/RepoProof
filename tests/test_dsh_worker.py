"""dsh_worker 最小闭环的钉死(DSH 阶段 3,ADR §4 不可信执行平面)。

**冻结判据**(先写判据与反例,再写实现;措辞此后不改):

- W1 **stdout 纯净**:无论成败,stdout 恰好一行、必须是带 protocol 标识的
  JSON;其余输出一律 stderr。反例:runtime 日志混进 stdout —— 父进程按行
  解析 result,读到的是日志第一行,归因全错。
- W2 **job spec 收紧方向**:相对路径、缺 prompt、env 非 str→str,一律
  bad_job_spec + 退出码 2,且**不起 runtime**。反例:相对 workspace 被
  容忍 —— worker 的 cwd 解释权落到调用方启动目录,隔离负控从此测不准。
- W3 **key 只经进程环境**:job spec 里出现 api_key / env.DEEPSEEK_API_KEY
  → 直接拒(铁律:AI 不经手密钥,key 不落 stdin/argv/日志)。反例:接受
  spec 传 key —— key 进了 events/journal 的字面量,一次落盘永久泄漏。
- W4 **生命周期与归因**(集成,吃封存 runtime):正常启动/关闭;runtime
  起不来(坏 cordis)归 harness 层错误族 + 退出码 3,不是 unexpected;
  同发结束后**无孤儿进程**;两发 session id 互异(fresh)。反例:崩溃归
  "unexpected" —— C8 金丝雀(阶段 6)将无从区分"环境破"与"代码 bug"。

**smoke 的模型面**:不可达 base_url + 假 key(字面假值,非任何真实凭据),
模型调用失败在 DSH 内部表达 —— 本阶段只证进程闭环,工具循环行为归阶段 6
C 系;"shell 状态不串"的完整证明也在那里(此处只钉 session id fresh)。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKER = REPO / "src" / "repoproof" / "agents" / "dsh_worker.py"

RT_ROOT = Path.home() / "RepoProofRuntimes" / "rt-dsh-minimal-0.1.0rc6-v1"
SEALED_PY = RT_ROOT / ".venv" / "bin" / "python"
SEALED_CORDIS = RT_ROOT / "config" / "minimal.upstream.0.1.0rc6.cordis.yml"

# 字面假值:不是任何真实凭据,只为让 runtime 的 provider 初始化不缺参。
_FAKE_KEY = "sk-smoke-invalid-0000"
# 丢弃端口:本机瞬时拒连,不出网(执行期断网纪律)。
_DEAD_BASE_URL = "http://127.0.0.1:9"


def _spawn(job: dict, python: str | Path = sys.executable,
           extra_env: dict | None = None, timeout: float = 180.0):
    """父侧最小闭环:进程组 + stdin 喂 spec + 超时强杀整组。"""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "HOME": os.environ.get("HOME", "/tmp"),
           "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
           **(extra_env or {})}
    proc = subprocess.Popen(
        [str(python), str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True, env=env)
    try:
        out, err = proc.communicate(json.dumps(job), timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
        pytest.fail(f"worker 超时未归:stdout={out!r} stderr 尾={err[-800:]!r}")
    return proc.returncode, out, err


def _result(out: str) -> dict:
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, f"W1:stdout 必须恰好一行 result,实得 {len(lines)} 行:{out!r}"
    r = json.loads(lines[0])
    assert r.get("protocol") == "dsh-worker-v1"
    return r


def _job(tmp: Path, **over) -> dict:
    ws = tmp / "ws"
    ws.mkdir(exist_ok=True)
    base = {
        "prompt": "说一句话即可。",
        "workspace": str(ws),
        "events_path": str(tmp / "events.jsonl"),
        "session_root": str(tmp / "dsh-sessions"),
        "cordis": str(SEALED_CORDIS),
    }
    base.update(over)
    return base


# ------------------------------------------------------------------ W1/W2/W3
# 纯协议面:走主 venv(拒绝路径在 import deepseek_harness 之前),不吃 runtime。

def test_w2_relative_paths_rejected(tmp_path: Path) -> None:
    code, out, _ = _spawn(_job(tmp_path, workspace="ws-relative"))
    r = _result(out)
    assert (code, r["ok"], r["error_kind"]) == (2, False, "bad_job_spec")
    assert "workspace" in r["error"] and "绝对路径" in r["error"]


def test_w2_missing_prompt_rejected(tmp_path: Path) -> None:
    j = _job(tmp_path)
    del j["prompt"]
    code, out, _ = _spawn(j)
    r = _result(out)
    assert (code, r["error_kind"]) == (2, "bad_job_spec")


def test_w2_garbage_stdin_rejected(tmp_path: Path) -> None:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)}
    proc = subprocess.Popen([sys.executable, str(WORKER)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True, env=env)
    out, _ = proc.communicate("这不是 JSON", timeout=60)
    assert proc.returncode == 2
    assert _result(out)["error_kind"] == "bad_job_spec"


def test_w3_key_via_spec_rejected(tmp_path: Path) -> None:
    for over in ({"api_key": "sk-x"}, {"env": {"DEEPSEEK_API_KEY": "sk-x"}}):
        code, out, _ = _spawn(_job(tmp_path, **over))
        r = _result(out)
        assert (code, r["error_kind"]) == (2, "bad_job_spec")
        assert "环境注入" in r["error"]


# ------------------------------------------------------------------ W4(集成)

needs_runtime = pytest.mark.skipif(
    not SEALED_PY.exists(),
    reason="封存 runtime 不在本机(rt-dsh-minimal-0.1.0rc6-v1);"
           "scripts/provision_dsh_runtime.py --go 后可跑")


def _no_orphans(marker: str) -> None:
    """同发无孤儿:以本发独有路径为记号,结束后不得再有活进程引用它。"""
    time.sleep(0.5)
    got = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
    assert got.returncode != 0, f"发现孤儿进程(pgrep -f {marker}):{got.stdout}"


@needs_runtime
def test_w4_lifecycle_and_fresh_sessions(tmp_path: Path) -> None:
    ids = []
    for i in ("a", "b"):
        sub = tmp_path / i
        sub.mkdir()
        job = _job(sub, request_timeout_seconds=60.0,
                   env={"DEEPSEEK_BASE_URL": _DEAD_BASE_URL})
        code, out, err = _spawn(job, python=SEALED_PY,
                                extra_env={"DEEPSEEK_API_KEY": _FAKE_KEY})
        r = _result(out)
        # 模型不可达:失败在 DSH 内部表达(ok=True + 错误 finish)或 harness
        # 层错误(exit 3)都算闭环;唯独不许 unexpected(exit 4)与超时。
        assert code in (0, 3), f"退出码 {code};stderr 尾={err[-800:]!r}"
        assert r["error_kind"] != "unexpected"
        assert r["session_id"], "必须有 session id"
        ids.append(r["session_id"])
        assert Path(job["events_path"]).exists() or code == 3, \
            "runtime 起来过就必须有宿主侧事件汇"
        _no_orphans(str(sub))
    assert ids[0] != ids[1], "W4:两发 session id 必须互异(fresh)"


@needs_runtime
def test_w4_runtime_crash_attributed_not_unexpected(tmp_path: Path) -> None:
    bad = tmp_path / "broken.cordis.yml"
    bad.write_text("]]] 这不是合法的 cordis [[[", encoding="utf-8")
    job = _job(tmp_path, cordis=str(bad), request_timeout_seconds=60.0)
    code, out, err = _spawn(job, python=SEALED_PY,
                            extra_env={"DEEPSEEK_API_KEY": _FAKE_KEY})
    r = _result(out)
    assert code == 3, f"崩溃必须归 harness 层(3),实得 {code};stderr 尾={err[-800:]!r}"
    assert r["error_kind"] in ("transport_closed", "jsonrpc_error",
                               "protocol_error", "harness_error")
    assert r["error_kind"] != "unexpected"
    _no_orphans(str(tmp_path))
