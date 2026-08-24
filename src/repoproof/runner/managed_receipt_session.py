"""M7 强回执 · 验收期取证会话(harness 侧编排;交付零改动)。

两面取证(receipt_hook 模块 docstring 的架构):
  取证面 —— harness 绕过交付 supervisor,自起同一份交付 server
  (会话 venv 解释器 + PYTHONPATH 前置 hook 目录 + 回执六键),对每个
  oracle fixture 发一次 /v1/invoke;server 进程内 hook 对每次
  `impl.extract` 发签名回执(现场上游指纹 / 输入输出摘要 / nonce 绑定)。
  交付面 —— 逐同一批 fixture 经**真实交付 bin 壳**(CLI→supervisor→
  server,无任何注入)收最终 stdout,作为 U4 的 delivery。
  U4(等于式):每个交付 stdout 的摘要必须等于某张回执的 output 摘要
  —— CLI/supervisor 层换答案、改写、后处理即杀。

返回形状与 sidecar_session.verify 对齐({ok, reason, attribution,
findings, ...}),直接进 host_guided 既有的 `_receipt_failure_side` /
`_adoption_failure_type` 归因管道。一切故障 fail-closed:起不来、账缺失、
探针失败都判不过,谁的锅写清 attribution。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from repoproof.execution.receipt_hook import (
    ENV_COUNT_FILE,
    ENV_KEY,
    ENV_LEDGER,
    ENV_RUN_ID,
    ENV_RUN_NONCE,
    ENV_TARGET,
    ENV_UPSTREAM_DIST,
    ENV_UPSTREAM_MODULE,
    NONCE_SEP,
    input_digest_of,
    norm_output_digest,
    probe_upstream_identity,
    write_receipt_hook_dir,
)
from repoproof.receipts.ledger import new_key, new_nonce
from repoproof.receipts.verify import (
    digest_equality_predicate,
    register_adoption,
    verify_receipts,
)

_TOKEN_ENV = "REPOPROOF_TOOL_SIDECAR_TOKEN"
_STARTUP_S = 30
_REQUEST_S = 120


class _AuditFailure(RuntimeError):
    def __init__(self, reason: str, attribution: str, detail: str):
        self.reason, self.attribution, self.detail = reason, attribution, detail
        super().__init__(detail)


def _harness_child_env(token: str, hook_dir: Path, src_dir: Path,
                       scratch: Path, receipt_env: dict[str, str]) -> dict[str, str]:
    """取证面 server 的 env:复刻交付 supervisor 的白名单语义(受控
    HOME/TMP、无环境泄漏),外加 hook 注入 —— 差异仅取证件本身。"""
    home = scratch / "home"
    tmp = scratch / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env = {k: os.environ[k] for k in ("LANG", "LC_ALL", "LC_CTYPE", "TZ")
           if k in os.environ}
    env.update({
        "HOME": str(home),
        "PATH": os.defpath,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        # hook 目录前置:sitecustomize 先行;交付包路径殿后
        "PYTHONPATH": os.pathsep.join((str(hook_dir), str(src_dir))),
        "TEMP": str(tmp), "TMP": str(tmp), "TMPDIR": str(tmp),
        _TOKEN_ENV: token,
    })
    env.update(receipt_env)
    return env


def _wait_ready(proc: subprocess.Popen, ready: Path, *, timeout_s: float) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise _AuditFailure(
                "RECEIPT_SERVER_DIED", "harness",
                f"取证面 server 启动即退(exit={proc.returncode})")
        if ready.is_file():
            try:
                doc = json.loads(ready.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = None
            if doc and isinstance(doc.get("port"), int):
                return doc
        time.sleep(0.05)
    raise _AuditFailure("RECEIPT_SERVER_TIMEOUT", "harness",
                        f"取证面 server {timeout_s}s 内未就绪")


def _invoke(base: str, token: str, input_path: Path, *, timeout_s: float) -> dict:
    body = json.dumps({"request_id": input_path.name,
                       "input_path": str(input_path)}).encode("utf-8")
    req = urllib.request.Request(
        base + "/v1/invoke", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-RepoProof-Token": token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))


def run_managed_receipt_audit(
    *,
    src_dir: Path,
    package: str,
    venv_python: Path,
    import_module: str,
    distribution: str,
    task_id: str,
    run_id: str,
    run_dir: Path,
    fixtures: list[Path],
    tool_bin: Path,
    tool_env: dict[str, str] | None = None,
) -> dict:
    """→ {ok, reason, attribution, findings, receipts, detail}。"""
    try:
        return _run(src_dir=Path(src_dir), package=package,
                    venv_python=Path(venv_python), import_module=import_module,
                    distribution=distribution, task_id=task_id, run_id=run_id,
                    run_dir=Path(run_dir), fixtures=[Path(f) for f in fixtures],
                    tool_bin=Path(tool_bin), tool_env=dict(tool_env or {}))
    except _AuditFailure as exc:
        return {"ok": False, "reason": exc.reason,
                "attribution": exc.attribution, "detail": exc.detail,
                "findings": [], "receipts": 0}


def _run(*, src_dir: Path, package: str, venv_python: Path, import_module: str,
         distribution: str, task_id: str, run_id: str, run_dir: Path,
         fixtures: list[Path], tool_bin: Path, tool_env: dict[str, str]) -> dict:
    if not fixtures:
        raise _AuditFailure("NO_FIXTURES", "harness",
                            "取证会话没有输入单元 —— 空账验不出任何东西")

    # 1) 期望上游身份(会话 venv 盘上事实;与 hook 现场口径一致)
    try:
        required_upstream = probe_upstream_identity(
            venv_python, import_module, distribution)
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise _AuditFailure("UPSTREAM_PROBE_FAILED", "harness",
                            f"期望上游身份探针失败:{exc}") from exc

    # 2) 取证材料现摇
    audit_root = run_dir / "managed_receipt_audit"
    audit_root.mkdir(parents=True, exist_ok=True)
    hook_dir = write_receipt_hook_dir(audit_root / "hook")
    ledger = audit_root / "receipts.jsonl"
    count_file = audit_root / "receipts.count"
    key = new_key()
    run_nonce = new_nonce()
    token = new_nonce()
    # 密钥落 run_dir(harness 侧,agent/交付摸不到):供 bundle 期独立复核
    # 重放同一本账 —— 没有它,事后审计只能验链不能验签。
    (audit_root / "receipts.key").write_text(key.hex(), encoding="utf-8")

    staging = audit_root / "staging"
    staging.mkdir(exist_ok=True)
    expected_units: list[dict] = []
    staged: list[Path] = []
    for f in fixtures:
        nonce = new_nonce()
        dst = staging / f"{nonce}{NONCE_SEP}{f.name}"
        shutil.copyfile(f, dst)
        expected_units.append({"request_nonce": nonce,
                               "input_digest": input_digest_of(f.read_bytes())})
        staged.append(dst)

    receipt_env = {
        ENV_LEDGER: str(ledger), ENV_KEY: key.hex(), ENV_RUN_ID: run_id,
        ENV_RUN_NONCE: run_nonce, ENV_TARGET: f"{package}.impl",
        ENV_UPSTREAM_MODULE: import_module, ENV_UPSTREAM_DIST: distribution,
        ENV_COUNT_FILE: str(count_file),
    }

    # 3) 取证面:起同一份交付 server(hook 注入),逐单元 invoke
    scratch = audit_root / "scratch"
    ready = audit_root / "ready.json"
    proc = subprocess.Popen(
        [str(venv_python), "-P", "-m", f"{package}.sidecar_server",
         "--ready-file", str(ready)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env=_harness_child_env(token, hook_dir, src_dir, scratch, receipt_env),
        start_new_session=True)
    try:
        doc = _wait_ready(proc, ready, timeout_s=_STARTUP_S)
        base = f"http://127.0.0.1:{doc['port']}"
        for dst in staged:
            r = _invoke(base, token, dst, timeout_s=_REQUEST_S)
            if r.get("ok") is not True:
                # 取证面调用失败:上游/实现异常在此如实截停,不猜
                raise _AuditFailure(
                    "RECEIPT_PROBE_INVOKE_FAILED", "agent",
                    f"取证面对 {dst.name} 调用失败:"
                    f"{r.get('error_code')}:{str(r.get('error_message'))[:200]}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    # 4) 交付面:真实 CLI→supervisor→server 链收最终 stdout(U4 delivery)
    delivery: list[str] = []
    for f in fixtures:
        r = subprocess.run([str(tool_bin), str(f)], capture_output=True,
                           text=True, timeout=_REQUEST_S * 2,
                           env={**os.environ, **tool_env})
        if r.returncode != 0:
            raise _AuditFailure(
                "DELIVERY_INVOKE_FAILED", "agent",
                f"交付链对 {f.name} exit={r.returncode}:{r.stderr[-200:]}")
        delivery.append(r.stdout)

    # 5) U1–U4(U4 = 等于式:交付 stdout 摘要 == 某张回执 output 摘要)
    register_adoption(task_id, digest_equality_predicate(
        lambda d: [norm_output_digest(t) for t in d]))
    try:
        written = int(count_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        written = 0            # 计数副本缺失 → 与账行数不符即 U1.count 杀
    v = verify_receipts(
        ledger, key=key, run_id=run_id, run_nonce=run_nonce, task_id=task_id,
        required_symbols={f"{package}.impl.extract"},
        required_upstream=required_upstream,
        expected_units=expected_units,
        delivery=delivery,
        expected_receipt_count=written)
    return {
        "ok": v.ok,
        "reason": "" if v.ok else "RECEIPT_VERIFICATION_FAILED",
        "attribution": "agent",
        "receipts": v.receipts,
        "findings": [{"check": f.check, "ok": f.ok, "detail": f.detail}
                     for f in v.findings],
        "detail": "" if v.ok else "; ".join(
            f"{f.check}:{f.detail[:80]}" for f in v.findings if not f.ok),
    }
