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
from pathlib import Path

from repoproof.domain.models import AdmissionError, sha256_file


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
