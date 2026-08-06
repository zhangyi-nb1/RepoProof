# Security Policy

## Honest threat model

RepoProof runs candidate open-source code inside Docker containers with
resource limits (`--cpus`, `--memory`, `--pids-limit`,
`--security-opt no-new-privileges`), a `network=none` verification
phase, read-only mounts for the upstream snapshot and the oracle, and
full container disposal after each run.

**This is an isolation, disposal and clean-replay mechanism — it is NOT
a hardened sandbox for adversarial or malicious code.** Containers
share the host kernel (here: a Colima VM); container escape and
kernel-level attacks are out of scope. RepoProof is designed to run
**human-admitted, public, license-identified repositories only**. Do
not point it at untrusted code and expect a security boundary.

## What the harness does defend against

- Accidental writes to the oracle or the pinned upstream snapshot
  (read-only mounts + before/after SHA-256 tree hashing);
- Test-time network access (`network=none` + an in-container probe);
- Unbounded execution (per-command timeout, wall-time and step budgets);
- Silent success claims (independent verifiers + completion gate);
- Environment contamination between runs (fresh containers, fresh
  execution trees, clean-room replay).

## Secrets

No API keys are used in the Gate 2 slice. Future model provider
configuration must live in `.env` (gitignored); manifests record only
a provider/model summary, never credentials.

## Reporting

Please report suspected vulnerabilities via GitHub Security Advisories
on this repository (Security tab → "Report a vulnerability").
