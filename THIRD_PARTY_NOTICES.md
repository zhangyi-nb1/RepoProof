# Third-Party Notices

RepoProof itself is licensed under Apache-2.0 (see LICENSE).

## Runtime-fetched candidate repositories (not vendored)

| Component | Source | Pinned revision | License | Usage |
|---|---|---|---|---|
| Chonkie | https://github.com/feyninc/chonkie | `0a6baea1a42c9afe9b3bc31ecb37739e744bb1ec` (v1.7.0) | MIT | Cloned at runtime into the gitignored `upstream-cache/` as the first adoption candidate. Never vendored into this repository; installed only inside disposable containers (base install, no extras). |

| rank_bm25 | https://github.com/dorianbrown/rank_bm25 | source_commit=`47aa3ddf` — source_relation_to_release=after_tag_0.2.2, upstream_declared_version=0.2.2, build_metadata_workaround=PKG_INFO_injection (NOT the official 0.2.2 tag itself) | Apache-2.0 | Second adoption candidate; cloned at runtime, never vendored; wheel built from the pinned commit with sdist-equivalent PKG-INFO metadata. |

## Integrated agent backend (Gate 3B)

| Component | Version | Source | License | Wheel SHA-256 |
|---|---|---|---|---|
| mini-swe-agent | 2.4.6 (exact pin) | https://github.com/SWE-agent/mini-swe-agent | MIT | `a35463c553ac825c7773b03cfa69cd44958e3af20155dcc5711fdf9e4c67cd54` |

Consumed host-side only as the single autonomous agent loop
(DefaultAgent). Transitive pins recorded in
`agent-requirements.lock.txt` (litellm constrained to a wheel build:
1.91.4). Never installed into task containers.

## Container base image

| Image | Usage |
|---|---|
| `python:3.12-slim-bookworm` | Disposable execution containers (Docker Official Image; Debian + PSF licensing applies inside the image). |

## Design lineage

Concepts (append-only trace, single policy dispatch, verifier
registry, budgets, checkpoint, Docker lifecycle) reference the
author's prior LocalFlow project read-only; all RepoProof code is a
re-implementation. See `docs/lineage.md`.
