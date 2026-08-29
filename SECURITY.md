# Security Policy

## Honest threat model

RepoProof runs candidate open-source code inside Docker containers with
resource limits (`--cpus`, `--memory`, `--pids-limit`,
`--security-opt no-new-privileges`), a `network=none` verification
phase, read-only mounts for the upstream snapshot and the oracle, and
full container disposal after each run.

Studio's pre-freeze and Fresh-audit reference probes are a narrower local
path. On the currently supported macOS Product host they run in a disposable
directory under an OS-enforced profile that denies all network access and all
writes outside that directory; provider/API environment variables are removed.
If that reviewed isolation backend is unavailable, Studio stops before the LLM
is called. This probe profile is not claimed to prevent an admitted upstream
from reading every host path, so reference output is kept local and is never
sent back to the model. Existing sample bodies and raw reference exception text
also never enter model prompts: duplicate filtering is local, while bounded
candidate repair receives only coarse reason codes and a classification
fingerprint derived from the allow-listed reason alone (never from the message,
input contents or a caller-provided opaque digest).

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
