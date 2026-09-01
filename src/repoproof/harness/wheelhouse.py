"""Wheelhouse admission (Gate 3A.D).

Before EVERY pass (primary and replay) the wheelhouse is re-verified
against the frozen task-package binding: exact filename set (no extras,
no missing), per-wheel SHA-256, recomputed root. pip never gets to
pick a candidate on its own — installs use explicit verified wheel
paths with --no-index --no-deps.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from repoproof.domain.models import AdmissionError, sha256_file

HARNESS_TEST_REQUIREMENTS = ("pytest>=8.0", "setuptools", "wheel")


def _normalise_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def wheel_distributions(wheelhouse: Path) -> set[str]:
    """Return normalized distribution names represented by regular wheels."""

    return {
        _normalise_distribution(path.name.split("-", 1)[0])
        for path in Path(wheelhouse).iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix == ".whl"
    }


def materialize_harness_test_toolchain(
    wheelhouse: Path,
    *,
    requirements: tuple[str, ...] = HARNESS_TEST_REQUIREMENTS,
    python_executable: str = sys.executable,
    timeout_s: int = 600,
) -> dict:
    """Add only missing Harness-owned test wheels to an execution closure.

    A workspace's runtime lock describes the delivered application, whereas
    RepoProof's public/oracle checks are executed with pytest and editable
    build tooling.  Those are separate ownership domains.  The task runtime
    bytes are never replaced: an admitted runtime wheel wins by distribution,
    and the downloaded supplement contributes only distributions that were
    absent.  Callers keep this supplement beside the immutable runtime
    wheelhouse and record its independent byte identity.
    """

    wheelhouse = Path(wheelhouse)
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise RuntimeError("HARNESS_TEST_WHEELHOUSE_INVALID")
    required_names = {
        _normalise_distribution(re.split(r"[=<>!~\[]", item, maxsplit=1)[0])
        for item in requirements
    }
    present = wheel_distributions(wheelhouse)
    missing_requirements = tuple(
        item
        for item in requirements
        if _normalise_distribution(
            re.split(r"[=<>!~\[]", item, maxsplit=1)[0]
        )
        not in present
    )
    if not missing_requirements:
        return {
            "manifest": compute_manifest(wheelhouse),
            "added_wheels": [],
            "required_distributions": sorted(required_names),
        }

    with tempfile.TemporaryDirectory(
        prefix=".harness-test-wheels-", dir=wheelhouse.parent
    ) as temp:
        stage = Path(temp)
        try:
            downloaded = subprocess.run(  # noqa: S603 - fixed interpreter/argv
                [
                    python_executable,
                    "-m",
                    "pip",
                    "download",
                    "--disable-pip-version-check",
                    "--only-binary=:all:",
                    "--dest",
                    str(stage),
                    *missing_requirements,
                ],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("HARNESS_TEST_TOOLCHAIN_DOWNLOAD_FAILED") from exc
        if downloaded.returncode != 0:
            raise RuntimeError("HARNESS_TEST_TOOLCHAIN_DOWNLOAD_FAILED")

        candidates = sorted(stage.iterdir(), key=lambda item: item.name)
        if not candidates or any(
            item.is_symlink() or not item.is_file() or item.suffix != ".whl"
            for item in candidates
        ):
            raise RuntimeError("HARNESS_TEST_TOOLCHAIN_WHEEL_INVALID")
        added: list[str] = []
        occupied = wheel_distributions(wheelhouse)
        for source in candidates:
            distribution = _normalise_distribution(source.name.split("-", 1)[0])
            if distribution in occupied:
                continue
            target = wheelhouse / source.name
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(target, flags, 0o600)
            except OSError as exc:
                raise RuntimeError("HARNESS_TEST_TOOLCHAIN_DESTINATION_UNSAFE") from exc
            try:
                with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
                    shutil.copyfileobj(reader, writer)
                    writer.flush()
                    os.fsync(writer.fileno())
            except Exception:
                target.unlink(missing_ok=True)
                raise
            occupied.add(distribution)
            added.append(target.name)

    missing_after = required_names - wheel_distributions(wheelhouse)
    if missing_after:
        raise RuntimeError("HARNESS_TEST_TOOLCHAIN_INCOMPLETE")
    return {
        "manifest": compute_manifest(wheelhouse),
        "added_wheels": sorted(added),
        "required_distributions": sorted(required_names),
    }


def compute_manifest(wheelhouse: Path) -> dict:
    wheels = {p.name: sha256_file(p) for p in sorted(Path(wheelhouse).glob("*.whl"))}
    root = hashlib.sha256(json.dumps(wheels, sort_keys=True).encode()).hexdigest()
    return {"wheels": wheels, "root": root}


def verify_wheelhouse(wheelhouse: Path, *, expected_wheels: dict[str, str], expected_root: str) -> dict:
    """Raise AdmissionError on ANY divergence; return the verified
    manifest (for trace evidence) otherwise."""
    actual = compute_manifest(wheelhouse)
    missing = sorted(set(expected_wheels) - set(actual["wheels"]))
    extra = sorted(set(actual["wheels"]) - set(expected_wheels))
    if missing:
        raise AdmissionError(f"wheelhouse missing wheel(s): {missing[:3]}")
    if extra:
        raise AdmissionError(f"wheelhouse has unexpected wheel(s): {extra[:3]}")
    tampered = sorted(n for n, h in expected_wheels.items() if actual["wheels"][n] != h)
    if tampered:
        raise AdmissionError(f"wheelhouse wheel hash mismatch (tampered?): {tampered[:3]}")
    if actual["root"] != expected_root:
        raise AdmissionError(f"wheelhouse root mismatch: {actual['root'][:12]} != {expected_root[:12]}")
    return actual


def select_wheel(expected_wheels: dict[str, str], distribution: str) -> tuple[str, str]:
    """Pick the single wheel for a distribution by exact name prefix;
    ambiguity or absence is an admission failure."""
    dist_norm = distribution.replace("-", "_")
    candidates = [n for n in expected_wheels if n.split("-", 1)[0] == dist_norm]
    if len(candidates) != 1:
        raise AdmissionError(f"expected exactly one {distribution} wheel, found {candidates}")
    return candidates[0], expected_wheels[candidates[0]]
