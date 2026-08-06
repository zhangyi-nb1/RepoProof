"""Minimal write-path and argv policy for the Gate 2 slice.

Single-dispatch idea referenced (read-only) from LocalFlow's policy
guard; rules re-written for RepoProof's trust zones. Scope is honest:
this is an isolation/discipline layer for human-admitted public repos,
NOT a security boundary against malicious code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PolicyDecision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class TrustZones:
    """Host-side zone roots for one run."""

    upstream: Path  # read-only, pinned commit
    oracle: Path  # read-only, hash-checked
    adaptation: Path  # ONLY persistent writable product zone
    # execution/scratch zones are container-local and ephemeral by
    # construction (never mounted from the host), so no host rule here.


def _contains(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def evaluate_write_path(zones: TrustZones, target: Path) -> PolicyDecision:
    t = Path(target)
    if _contains(zones.oracle, t):
        return PolicyDecision(False, ["oracle_write_forbidden"])
    if _contains(zones.upstream, t):
        return PolicyDecision(False, ["upstream_write_forbidden (patches go to adaptation/patches)"])
    if _contains(zones.adaptation, t):
        return PolicyDecision(True, ["adaptation_zone"])
    return PolicyDecision(False, [f"outside_editable_zones: {t}"])


# argv-level denylist: commands the Gate 2 runner must never issue.
_ARGV_DENY_SUBSTRINGS = (
    "--privileged",
    "docker.sock",
    "sudo ",
)

# Forbidden install extras / heavyweight deps per the Chonkie contract.
_FORBIDDEN_INSTALL_TOKENS = (
    "[all]",
    "[semantic]",
    "[neural]",
    "[late]",
    "[slumber]",
    "[st]",
    "sentence-transformers",
    "torch",
    "openai",
    "google-genai",
    "gemini",
    "qdrant",
    "chromadb",
    "pgvector",
    "weaviate",
)


def evaluate_argv(argv: list[str], *, forbidden_install_tokens: tuple[str, ...] | None = None) -> PolicyDecision:
    joined = " ".join(argv)
    reasons: list[str] = []
    for bad in _ARGV_DENY_SUBSTRINGS:
        if bad in joined:
            reasons.append(f"denied_substring:{bad.strip()}")
    is_pip_install = "pip" in joined and "install" in joined
    if is_pip_install:
        tokens = forbidden_install_tokens or _FORBIDDEN_INSTALL_TOKENS
        for tok in tokens:
            if tok in joined:
                reasons.append(f"forbidden_install_extra:{tok}")
    if reasons:
        return PolicyDecision(False, reasons)
    return PolicyDecision(True, ["ok"])
