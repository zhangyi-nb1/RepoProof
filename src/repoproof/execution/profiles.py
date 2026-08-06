"""Container mount/security profiles: Agent vs Verifier trust separation.

Gate 2.5 builds and TESTS both profiles even though no real agent runs
yet — the separation must exist before the agent does.

Agent profile MUST NOT see: oracle, Gate-2 evidence, completion-gate /
harness source, LocalFlow, credentials, docker socket. It gets exactly:
the read-only upstream snapshot, a writable workspace (its own copy of
the consumer fixture + public sample inputs), and the writable
adaptation zone. network=none.

Verifier profile: upstream ro, CLEAN consumer copy ro (from the repo,
never the agent's touched workspace), adaptation ro (frozen), oracle
ro. network=none.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from repoproof.execution.docker_backend import Mount


@dataclass
class ContainerProfile:
    name: str
    network: str
    mounts: list[Mount]
    env: dict[str, str] = field(default_factory=dict)
    user: str | None = "1000:1000"
    cap_drop_all: bool = True

    def start_kwargs(self) -> dict:
        return {
            "network": self.network,
            "mounts": self.mounts,
            "env": self.env,
            "user": self.user,
            "cap_drop_all": self.cap_drop_all,
        }


def agent_profile(
    *,
    upstream: Path,
    agent_workspace: Path,
    adaptation: Path,
    venv: Path,
) -> ContainerProfile:
    """What a future agent is allowed to touch. No oracle. No harness
    source. No probes. No evidence. No network. Non-root, cap-drop ALL."""
    return ContainerProfile(
        name="agent",
        network="none",
        mounts=[
            Mount(upstream, "/upstream", True),
            Mount(agent_workspace, "/workspace", False),
            Mount(adaptation, "/adaptation", False),
            Mount(venv, "/venv", False),
        ],
        env={
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        },
    )


def verifier_profile(
    *,
    upstream: Path,
    consumer_clean: Path,
    adaptation: Path,
    oracle_snapshot: Path,
    venv: Path,
    probes: Path,
) -> ContainerProfile:
    """Verification consumes the FROZEN adaptation zone read-only and a
    clean consumer copy from the repo — never the agent workspace."""
    return ContainerProfile(
        name="verifier",
        network="none",
        mounts=[
            Mount(upstream, "/upstream", True),
            Mount(consumer_clean, "/consumer_src", True),
            Mount(adaptation, "/adaptation", True),
            Mount(oracle_snapshot, "/oracle", True),
            Mount(venv, "/venv", False),
            Mount(probes, "/probes", True),
        ],
        env={
            "PYTHONPATH": "/tmp/execution/consumer/src",
            "REPOPROOF_ADAPTATION_DIR": "/adaptation",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
