"""Agent/Verifier container profile separation — real docker checks.

Skipped when no docker daemon is reachable; on the dev machine (and
any CI with docker) they run for real:
  * the AGENT profile container has NO /oracle, NO /probes, NO
    harness source, network=none, non-root user, cap-drop ALL;
  * network=none is proven by docker inspect AND a socket probe.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repoproof.execution.docker_backend import DockerExecutionBackend
from repoproof.execution.profiles import agent_profile

IMAGE = "python:3.12-slim-bookworm"

ok, _msg = DockerExecutionBackend.available()
pytestmark = pytest.mark.skipif(not ok, reason="docker daemon not reachable")


REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def agent_container():
    # Zones must live under $HOME: colima only mounts the home dir into
    # the VM, so /var/folders (pytest tmp) arrives as empty root-owned
    # dirs inside containers — a real environmental finding.
    import shutil
    import uuid

    tmp = REPO / "runs" / f"_profile_test_zones-{uuid.uuid4().hex[:8]}"
    tmp.mkdir(parents=True)
    for name in ("upstream", "workspace", "adaptation", "venv"):
        (tmp / name).mkdir()
    (tmp / "upstream" / "README.md").write_text("pinned upstream\n")
    backend = DockerExecutionBackend(image=IMAGE)
    profile = agent_profile(
        upstream=tmp / "upstream",
        agent_workspace=tmp / "workspace",
        adaptation=tmp / "adaptation",
        venv=tmp / "venv",
    )
    kwargs = profile.start_kwargs()
    kwargs["user"] = f"{os.getuid()}:{os.getgid()}"
    cid = backend.start(name_prefix="rp-test-agent", **kwargs)
    yield backend, cid
    backend.destroy(cid)
    shutil.rmtree(tmp, ignore_errors=True)


def test_agent_cannot_see_oracle_or_harness(agent_container) -> None:
    backend, cid = agent_container
    for forbidden in ("/oracle", "/probes", "/consumer_src", "/repoproof", "/var/run/docker.sock"):
        res = backend.exec(cid, ["test", "-e", forbidden], timeout_s=10)
        assert res.exit_code != 0, f"agent profile must not expose {forbidden}"
    res = backend.exec(cid, ["test", "-r", "/upstream/README.md"], timeout_s=10)
    assert res.exit_code == 0


def test_agent_container_security_flags(agent_container) -> None:
    backend, cid = agent_container
    sec = backend.inspect_security(cid)
    assert str(sec.get("network_mode")) == "none"
    assert sec.get("user") not in ("", "0", "root", None)
    assert "ALL" in str(sec.get("cap_drop"))
    assert sec.get("pids_limit") == 256


def test_agent_network_none_socket_probe(agent_container) -> None:
    backend, cid = agent_container
    res = backend.exec(
        cid,
        [
            "python3",
            "-c",
            (
                "import socket\n"
                "try:\n"
                "    socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
                "    print('UNEXPECTED-NETWORK'); raise SystemExit(1)\n"
                "except OSError as exc:\n"
                "    print('blocked:', type(exc).__name__)"
            ),
        ],
        timeout_s=20,
    )
    assert res.exit_code == 0
    assert b"blocked:" in res.stdout


def test_agent_writable_zones_work(agent_container) -> None:
    backend, cid = agent_container
    res = backend.exec(cid, ["sh", "-c", "echo hi > /adaptation/note.txt && cat /adaptation/note.txt"], timeout_s=10)
    assert res.exit_code == 0 and b"hi" in res.stdout
    res2 = backend.exec(cid, ["sh", "-c", "echo x > /upstream/hack.txt"], timeout_s=10)
    assert res2.exit_code != 0, "upstream must be read-only for the agent"
