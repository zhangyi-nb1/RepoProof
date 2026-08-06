"""Trusted (no-agent) container utilities for Gate 3A:

  * ``container_session`` — a pinned-env container with the offline
    venv installed from the verified wheelhouse (the same env the
    verifier chain uses);
  * ``generate_reference_partitions`` — run the reference partition
    probe against fixture files (calibration; human/pre-freeze step);
  * ``run_oracle_with_adapter`` — execute the capability oracle against
    an EXPLICIT control adapter dir (positive/negative controls),
    returning the parsed JUnit summary.

These are trusted-harness paths: they never run an agent and are never
reachable from agent-profile containers.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from pathlib import Path

from repoproof.execution.docker_backend import DockerExecutionBackend, Mount
from repoproof.verification.junit import parse_junit_xml

IMAGE = "python:3.12-slim-bookworm"


@contextlib.contextmanager
def container_session(
    *,
    project_root: Path,
    upstream: Path,
    wheelhouse: Path,
    extra_mounts: list[Mount] | None = None,
    env: dict[str, str] | None = None,
    user: str,
):
    """Start a pinned container, install the offline venv, yield
    (backend, container_id); always destroy."""
    backend = DockerExecutionBackend(image=IMAGE)
    backend.pull()
    digest = backend.image_digest()
    venv_root = project_root / "runs" / f"_calib-venv-{uuid.uuid4().hex[:8]}"
    venv_root.mkdir(parents=True)
    mounts = [
        Mount(upstream, "/upstream", True),
        Mount(wheelhouse, "/wheels", True),
        Mount(venv_root, "/venv", False),
    ] + (extra_mounts or [])
    cid = backend.start(
        name_prefix="rp-calib",
        network="none",
        mounts=mounts,
        env=env or {},
        user=user,
        image_ref=digest or IMAGE,
    )
    try:
        r = backend.exec(cid, ["python3", "-m", "venv", "/venv/env"], timeout_s=120)
        assert r.exit_code == 0, r.stderr[:300]
        wheels = sorted(p.name for p in wheelhouse.glob("*.whl"))
        argv = [
            "/venv/env/bin/pip",
            "install",
            "--no-index",
            "--no-deps",
            "--no-cache-dir",
            "--disable-pip-version-check",
        ] + [f"/wheels/{w}" for w in wheels]
        r = backend.exec(cid, argv, timeout_s=300)
        assert r.exit_code == 0, r.stderr[-500:]
        yield backend, cid
    finally:
        backend.destroy_all()
        import shutil

        shutil.rmtree(venv_root, ignore_errors=True)


def generate_reference_partitions(
    *, project_root: Path, upstream: Path, wheelhouse: Path, fixture_files: list[Path], chunk_size: int, user: str
) -> dict:
    probes = project_root / "src" / "repoproof" / "probes"
    fixture_mounts = [
        Mount(f.parent, f"/fixtures{i}", True) for i, f in enumerate(fixture_files)
    ]
    with container_session(
        project_root=project_root,
        upstream=upstream,
        wheelhouse=wheelhouse,
        extra_mounts=[Mount(probes, "/probes", True), *fixture_mounts],
        user=user,
    ) as (backend, cid):
        args = [f"/fixtures{i}/{f.name}" for i, f in enumerate(fixture_files)]
        res = backend.exec(
            cid,
            ["/venv/env/bin/python", "/probes/reference_partition_probe.py", *args, "--chunk-size", str(chunk_size)],
            timeout_s=300,
        )
        if res.exit_code != 0:
            raise RuntimeError(f"reference probe failed: {res.stderr.decode(errors='replace')[-500:]}")
        return json.loads(res.stdout.decode("utf-8"))


def run_oracle_with_adapter(
    *,
    project_root: Path,
    upstream: Path,
    wheelhouse: Path,
    oracle_dir: Path,
    adapter_dir: Path,
    consumer_dir: Path,
    user: str,
    test_file: str = "test_capability.py",
) -> dict:
    """Run the capability oracle against a specific control adapter in
    the pinned container. Returns the parsed JUnit summary dict."""
    env = {
        "PYTHONPATH": "/tmp/execution/consumer/src",
        "REPOPROOF_ADAPTATION_DIR": "/control_adapter",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    with container_session(
        project_root=project_root,
        upstream=upstream,
        wheelhouse=wheelhouse,
        extra_mounts=[
            Mount(oracle_dir, "/oracle", True),
            Mount(adapter_dir, "/control_adapter", True),
            Mount(consumer_dir, "/consumer_src", True),
        ],
        env=env,
        user=user,
    ) as (backend, cid):
        r = backend.exec(
            cid,
            ["sh", "-c", "mkdir -p /tmp/execution && cp -r /consumer_src /tmp/execution/consumer"],
            timeout_s=60,
        )
        assert r.exit_code == 0
        res = backend.exec(
            cid,
            [
                "/venv/env/bin/python",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                f"/oracle/{test_file}",
                "--junitxml=/tmp/execution/junit.xml",
            ],
            timeout_s=600,
            workdir="/tmp/execution",
        )
        junit = backend.exec(cid, ["cat", "/tmp/execution/junit.xml"], timeout_s=30)
        parsed = parse_junit_xml(junit.stdout if junit.exit_code == 0 else None)
        parsed["exit_code"] = res.exit_code
        parsed["stdout_tail"] = res.stdout.decode(errors="replace")[-800:]
        return parsed
