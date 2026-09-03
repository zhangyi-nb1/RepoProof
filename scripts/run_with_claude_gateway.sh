#!/bin/sh
# Run one RepoProof command on the Claude gateway channel.
#
#   scripts/run_with_claude_gateway.sh .venv/bin/python -m repoproof.cli tool add ...
#
# The credential is read from the Claude Code settings file that already holds
# it and exported to the child process only: this repository never gets a second
# copy of the token on disk, and nothing is printed.
#
# The channel is explicit end to end.  The drafter speaks Anthropic's protocol
# (forced tool call = provider-enforced JSON schema); the Agent keeps the
# OpenAI-compatible surface of the same gateway, which is why the base carries
# /v1 and the temperature policy is provider_default — current Claude models
# reject the temperature parameter outright, and a silently dropped parameter is
# exactly the kind of degradation this project refuses to hide.
set -eu

SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
[ -r "$SETTINGS" ] || { echo "claude settings not readable: $SETTINGS" >&2; exit 2; }

eval "$(
  python3 - "$SETTINGS" <<'PY'
import json, os, shlex, sys
env = (json.load(open(sys.argv[1])).get("env") or {})
base = str(env.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
token = str(env.get("ANTHROPIC_AUTH_TOKEN") or "")
if not base or not token:
    sys.exit("ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN missing from claude settings")
# The model is an explicit, recorded choice; override per run with
# REPOPROOF_CLAUDE_MODEL so a model comparison never needs a source edit.
#
# Default: the same-family tier BELOW the flagship, to match how this batch was
# originally run against the other provider (a mid tier, not its top model).
# Documented fallback: claude-opus-4-6 — selected by hand, never automatically,
# because switching models changes the billing subject, the model identity and
# reproducibility.  Note 4-6 accepts temperature=0 while 4-8 rejects it; if you
# run the fallback and want the deterministic setting, say so explicitly with
# REPOPROOF_TEMPERATURE_POLICY=0 rather than letting a channel decide per model.
model = os.environ.get("REPOPROOF_CLAUDE_MODEL") or "claude-opus-4-8"
pairs = {
    "REPOPROOF_DRAFTER_BACKEND": "anthropic-gateway",
    "REPOPROOF_ANTHROPIC_BASE": base,
    "REPOPROOF_ANTHROPIC_KEY": token,
    "REPOPROOF_ANTHROPIC_MODEL": model,
    # Agent side: same gateway, OpenAI-compatible surface, same credential.
    "REPOPROOF_API_BASE": base + "/v1",
    "REPOPROOF_API_KEY": token,
    "REPOPROOF_MODEL": model,
    "REPOPROOF_TEMPERATURE_POLICY": "provider_default",
}
print("\n".join(f"export {k}={shlex.quote(v)}" for k, v in pairs.items()))
PY
)"

[ "$#" -gt 0 ] || { echo "usage: $0 <command> [args...]" >&2; exit 2; }
exec "$@"
