# Third-Party Notices

RepoProof itself is licensed under Apache-2.0 (see LICENSE).

## Runtime-fetched candidate repositories (not vendored)

| Component | Source | Pinned revision | License | Usage |
|---|---|---|---|---|
| Chonkie | https://github.com/feyninc/chonkie | `0a6baea1a42c9afe9b3bc31ecb37739e744bb1ec` (v1.7.0) | MIT | Cloned at runtime into the gitignored `upstream-cache/` as the first adoption candidate. Never vendored into this repository; installed only inside disposable containers (base install, no extras). |

## Planned (Gate 3, not yet integrated)

| Component | Source | License | Usage |
|---|---|---|---|
| mini-swe-agent | https://github.com/SWE-agent/mini-swe-agent | MIT | Planned single AgentBackend. Will be consumed as a pinned dependency via an adapter — attribution recorded here when integrated. |

## Container base image

| Image | Usage |
|---|---|
| `python:3.12-slim-bookworm` | Disposable execution containers (Docker Official Image; Debian + PSF licensing applies inside the image). |

## Design lineage

Concepts (append-only trace, single policy dispatch, verifier
registry, budgets, checkpoint, Docker lifecycle) reference the
author's prior LocalFlow project read-only; all RepoProof code is a
re-implementation. See `docs/lineage.md`.
