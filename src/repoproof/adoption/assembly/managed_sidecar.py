"""Generate the standard-library-only ToolSpec v3 managed sidecar runtime.

The delivered process supervisor is a Product runtime, not the benchmark
``TaskContract.runtime_profile`` sidecar.  It owns only per-invocation process
lifecycle and the fixed loopback protocol; build-time signed receipts remain a
Harness concern and no signing material is rendered into these files.
"""

from __future__ import annotations

from textwrap import dedent

from repoproof.adoption.assembly.output_contract import render_pytest_validator
from repoproof.domain.models import ToolOutputContract, ToolRuntimeSpec

_SERVER = r'''from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TOKEN_ENV = "REPOPROOF_TOOL_SIDECAR_TOKEN"
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_CHARS = 16 * 1024 * 1024


def _loopback_only(event, args):
    if event != "socket.connect" or len(args) < 2:
        return
    address = args[1]
    if not isinstance(address, tuple) or not address:
        return
    host = str(address[0])
    if host == "localhost":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        pass
    raise PermissionError("managed sidecar outbound network is loopback-only")


def _strict_loads(raw):
    def reject(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")
    return json.loads(raw, parse_constant=reject)


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False


class _Handler(BaseHTTPRequestHandler):
    server_version = "RepoProofManagedSidecar/1"

    def log_message(self, *_args):
        return

    def _authorized(self):
        return self.headers.get("X-RepoProof-Token") == self.server.token

    def _json(self, code, body):
        raw = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != "/healthz":
            return self._json(404, {"ok": False, "error_code": "NOT_FOUND"})
        if not self._authorized():
            return self._json(403, {"ok": False, "error_code": "FORBIDDEN"})
        return self._json(200, {
            "ok": True,
            "protocol": "repoproof-http-sidecar-v1",
        })

    def do_POST(self):
        if self.path != "/v1/invoke":
            return self._json(404, {"ok": False, "error_code": "NOT_FOUND"})
        if not self._authorized():
            return self._json(403, {"ok": False, "error_code": "FORBIDDEN"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = -1
        if size < 0 or size > MAX_REQUEST_BYTES:
            return self._json(413, {
                "ok": False, "error_code": "REQUEST_TOO_LARGE",
            })
        try:
            request = _strict_loads(self.rfile.read(size))
        except (UnicodeDecodeError, ValueError):
            return self._json(400, {
                "ok": False, "error_code": "INVALID_REQUEST",
            })
        if not isinstance(request, dict) or not isinstance(
            request.get("input_path"), str
        ):
            return self._json(400, {
                "ok": False, "error_code": "INVALID_REQUEST",
            })
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return self._json(400, {
                "ok": False, "error_code": "INVALID_REQUEST",
            })
        try:
            result = impl.extract(Path(request["input_path"]))
        except impl.UserInputError as exc:
            return self._json(400, {
                "ok": False,
                "request_id": request_id,
                "error_code": "USER_INPUT_ERROR",
                "error_message": str(exc)[:500],
            })
        except Exception as exc:
            return self._json(500, {
                "ok": False,
                "request_id": request_id,
                "error_code": "SIDECAR_INTERNAL_ERROR",
                "error_message": type(exc).__name__,
            })
        if not isinstance(result, str):
            return self._json(500, {
                "ok": False,
                "request_id": request_id,
                "error_code": "NON_TEXT_RESULT",
            })
        if len(result) > MAX_RESPONSE_CHARS:
            return self._json(500, {
                "ok": False,
                "request_id": request_id,
                "error_code": "RESPONSE_TOO_LARGE",
            })
        return self._json(200, {
            "ok": True,
            "request_id": request_id,
            "stdout": result,
        })


def _write_ready(path, *, port):
    doc = {
        "host": "127.0.0.1",
        "port": port,
        "protocol": "repoproof-http-sidecar-v1",
        "pid": os.getpid(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ready-file", required=True)
    args = parser.parse_args(argv)
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise SystemExit("managed sidecar token missing")
    # Install the best-effort in-process guard before importing agent-owned
    # capability code.  This closes the pre-hook import window, but arbitrary
    # same-process Python still is not an OS sandbox; release remains capped.
    sys.addaudithook(_loopback_only)
    from . import impl as capability_impl

    globals()["impl"] = capability_impl
    server = _Server(("127.0.0.1", 0), _Handler)
    server.token = token
    _write_ready(Path(args.ready_file), port=server.server_address[1])
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
'''


_SUPERVISOR = r'''from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .sidecar_contract import OutputContractViolation, assert_output_contract

TOKEN_ENV = "REPOPROOF_TOOL_SIDECAR_TOKEN"
MAX_ENVELOPE_BYTES = 20 * 1024 * 1024
STARTUP_TIMEOUT_SECONDS = __STARTUP_TIMEOUT__
REQUEST_TIMEOUT_SECONDS = __REQUEST_TIMEOUT__
SHUTDOWN_TIMEOUT_SECONDS = __SHUTDOWN_TIMEOUT__
MAX_INVOCATION_SECONDS = (
    STARTUP_TIMEOUT_SECONDS
    + REQUEST_TIMEOUT_SECONDS
    + SHUTDOWN_TIMEOUT_SECONDS
)

# Credentials are forbidden by the delivery contract.  Do not copy the
# ambient environment and try to guess which names are sensitive: capability
# code receives only this small compatibility surface plus an invocation-local
# HOME/TMPDIR and the one-time protocol token.
_CHILD_ENV_ALLOWLIST = (
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
)


class SidecarUserError(ValueError):
    pass


class SidecarRuntimeError(RuntimeError):
    pass


def _child_env(token, runtime_root):
    home = runtime_root / "home"
    scratch = runtime_root / "tmp"
    home.mkdir(mode=0o700)
    scratch.mkdir(mode=0o700)
    env = {
        key: os.environ[key]
        for key in _CHILD_ENV_ALLOWLIST
        if key in os.environ
    }
    env.update({
        "HOME": str(home),
        "PATH": os.pathsep.join((str(Path(sys.executable).parent), os.defpath)),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent),
        "PYTHONSAFEPATH": "1",
        "TEMP": str(scratch),
        "TMP": str(scratch),
        "TMPDIR": str(scratch),
        TOKEN_ENV: token,
    })
    return env


def _remaining(deadline, phase):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError(f"managed sidecar {phase} timed out")
    return remaining


def _read_json_response(request, *, deadline):
    response = None
    try:
        # A local protocol must never be redirected through a user-configured
        # HTTP proxy.  The endpoint itself is also constructed internally from
        # the validated loopback readiness record.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        response = opener.open(
            request,
            timeout=_remaining(deadline, "request"),
        )
    except urllib.error.HTTPError as exc:
        response = exc
    try:
        raw = response.read(MAX_ENVELOPE_BYTES + 1)
    finally:
        response.close()
    if len(raw) > MAX_ENVELOPE_BYTES:
        raise SidecarRuntimeError("sidecar response envelope too large")
    try:
        doc = json.loads(raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise SidecarRuntimeError("sidecar response is not valid JSON") from exc
    if not isinstance(doc, dict):
        raise SidecarRuntimeError("sidecar response must be a JSON object")
    return doc


def _wait_ready(proc, ready_path, *, deadline):
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SidecarRuntimeError(
                f"managed sidecar exited during startup: {proc.returncode}"
            )
        if ready_path.is_file():
            try:
                doc = json.loads(ready_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                time.sleep(0.02)
                continue
            if (
                isinstance(doc, dict)
                and doc.get("host") == "127.0.0.1"
                and type(doc.get("port")) is int
                and 0 < doc["port"] < 65536
                and doc.get("protocol") == "repoproof-http-sidecar-v1"
                and doc.get("pid") == proc.pid
            ):
                return doc
            raise SidecarRuntimeError("invalid managed sidecar readiness record")
        time.sleep(0.02)
    raise SidecarRuntimeError("managed sidecar startup timed out")


def _request(url, token, *, deadline, body=None):
    data = None if body is None else json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="GET" if body is None else "POST",
        headers={
            "Content-Type": "application/json",
            "X-RepoProof-Token": token,
        },
    )
    return _read_json_response(request, deadline=deadline)


def _process_group_exists(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # An existing group that we cannot inspect is not confirmed stopped.
        return True
    return True


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return False
    return True


def _wait_group_gone(proc, pgid, *, deadline):
    while time.monotonic() < deadline:
        # poll() also reaps the leader when it has exited.  Descendants are
        # tracked by process-group existence, not by the leader's return code.
        proc.poll()
        if not _process_group_exists(pgid):
            return True
        time.sleep(0.02)
    proc.poll()
    return not _process_group_exists(pgid)


def _stop(proc):
    pgid = proc.pid
    started = time.monotonic()
    deadline = started + SHUTDOWN_TIMEOUT_SECONDS
    # Reserve part of the one shutdown budget for unconditional SIGKILL
    # escalation.  In particular, do not return just because the HTTP leader
    # has already exited: helpers can still be alive in its process group.
    term_deadline = min(
        deadline,
        started + max(0.05, SHUTDOWN_TIMEOUT_SECONDS * 0.75),
    )
    # The sidecar starts a new session, so reclaim the whole process group.
    # Capability implementations may spawn helpers; killing only the HTTP
    # parent would leave those helpers orphaned after a timeout or crash.
    _signal_group(pgid, signal.SIGTERM)
    if not _wait_group_gone(proc, pgid, deadline=term_deadline):
        _signal_group(pgid, signal.SIGKILL)
    if not _wait_group_gone(proc, pgid, deadline=deadline):
        # One last best-effort kill before failing closed.  This cannot protect
        # against the supervisor itself receiving SIGKILL, nor helpers that
        # deliberately create a different session; those require OS isolation.
        _signal_group(pgid, signal.SIGKILL)
        if not _wait_group_gone(
            proc,
            pgid,
            deadline=time.monotonic() + 0.1,
        ):
            raise SidecarRuntimeError(
                "managed sidecar process-group cleanup could not be confirmed"
            )
    if proc.poll() is None:
        try:
            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise SidecarRuntimeError(
                "managed sidecar leader cleanup could not be confirmed"
            ) from exc


def invoke(input_path):
    token = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="repoproof-sidecar-") as temp:
        runtime_root = Path(temp)
        ready_path = runtime_root / "ready.json"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-P",
                "-m",
                "__PACKAGE__.sidecar_server",
                "--ready-file",
                str(ready_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_child_env(token, runtime_root),
            close_fds=True,
            start_new_session=True,
        )
        try:
            ready = _wait_ready(
                proc,
                ready_path,
                deadline=time.monotonic() + STARTUP_TIMEOUT_SECONDS,
            )
            base = f"http://127.0.0.1:{ready['port']}"
            # Health and invoke share one request budget.  A slow health probe
            # must not buy the invocation a second full timeout.
            request_deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
            health = _request(
                base + "/healthz",
                token,
                deadline=request_deadline,
            )
            if health != {
                "ok": True, "protocol": "repoproof-http-sidecar-v1"
            }:
                raise SidecarRuntimeError("managed sidecar health check failed")
            request_id = str(uuid.uuid4())
            result = _request(
                base + "/v1/invoke",
                token,
                deadline=request_deadline,
                body={"request_id": request_id, "input_path": str(input_path)},
            )
            if result.get("request_id") != request_id:
                raise SidecarRuntimeError("managed sidecar request binding mismatch")
            if result.get("ok") is not True:
                code = result.get("error_code")
                message = result.get("error_message") or code or "sidecar failed"
                if code == "USER_INPUT_ERROR":
                    raise SidecarUserError(str(message))
                raise SidecarRuntimeError(str(message))
            stdout = result.get("stdout")
            if not isinstance(stdout, str):
                raise SidecarRuntimeError("managed sidecar stdout must be text")
            try:
                assert_output_contract(stdout)
            except OutputContractViolation as exc:
                raise SidecarRuntimeError(str(exc)) from exc
            return stdout
        except (TimeoutError, urllib.error.URLError) as exc:
            raise SidecarRuntimeError("managed sidecar request timed out or failed") from exc
        finally:
            _stop(proc)
'''


def render_managed_sidecar_files(
    *,
    package: str,
    runtime: ToolRuntimeSpec,
    output_contract: ToolOutputContract,
) -> dict[str, str]:
    """Return package-relative framework files for one ToolSpec v3 skeleton."""

    supervisor = (
        _SUPERVISOR.replace("__PACKAGE__", package)
        .replace("__STARTUP_TIMEOUT__", str(runtime.startup_timeout_seconds))
        .replace("__REQUEST_TIMEOUT__", str(runtime.request_timeout_seconds))
        .replace("__SHUTDOWN_TIMEOUT__", str(runtime.shutdown_timeout_seconds))
    )
    validator_lines = render_pytest_validator(output_contract).splitlines()
    assertion_lines = [
        index
        for index, line in enumerate(validator_lines)
        if line.lstrip().startswith("assert not errors,")
    ]
    if len(assertion_lines) != 1:
        raise RuntimeError("standalone output validator shape changed")
    assertion_index = assertion_lines[0]
    validator_lines[assertion_index:assertion_index + 1] = [
        "    if errors:",
        "        raise OutputContractViolation(",
        "            '[tool-output-contract] ' + '; '.join(errors)",
        "        )",
    ]
    validator = (
        "class OutputContractViolation(ValueError):\n"
        "    pass\n\n"
        + "\n".join(validator_lines)
        + "\n"
        + dedent(
            '''

            def assert_output_contract(text):
                _assert_output_contract(text)
            '''
        )
    )
    return {
        "sidecar_server.py": _SERVER,
        "sidecar_supervisor.py": supervisor,
        "sidecar_contract.py": validator,
    }
