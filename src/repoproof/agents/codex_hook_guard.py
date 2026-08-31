"""Fail-closed command hook for the Product Mode Codex CLI connector.

Codex's ``workspace-write`` sandbox constrains writes, but it intentionally
permits broad reads.  RepoProof's held-out material therefore needs an
additional command gate.  This hook is invoked by Codex ``PreToolUse`` and
reuses RepoProof's existing command policy, then rejects explicit path escapes
from the disposable session root.

This remains a best-effort shell-command detector, not a substitute for OS
isolation.  Consequently the Codex connector is Product Mode only and never a
Benchmark Lab measurement backend.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from repoproof.harness.policy import evaluate_agent_command

HOOK_POLICY_VERSION = "repoproof-codex-pretool-v1"

_SYSTEM_READ_PREFIXES = (
    "/bin/",
    "/dev/",
    "/Library/",
    "/opt/",
    "/private/tmp/",
    "/System/",
    "/tmp/",
    "/usr/",
)
_SHELL_META = ";&|<>()"


def _record(payload: dict[str, Any]) -> None:
    raw = os.environ.get("REPOPROOF_CODEX_POLICY_LOG", "")
    if not raw:
        return
    path = Path(raw)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        # A missing audit sink must not turn a denied command into an allowed one.
        return


def _clean_token(token: str) -> str:
    return token.strip("\"'" + _SHELL_META + ",")


def _path_escape_reasons(command: str, *, cwd: Path, allowed_root: Path) -> list[str]:
    reasons: list[str] = []
    folded = command.lower()
    if "$home" in folded or "${home" in folded or "~/.codex" in folded:
        reasons.append("codex_private_home_reference")
    if "`" in command or "$(" in command:
        reasons.append("codex_dynamic_command_substitution")

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return [*reasons, "codex_unparseable_shell_command"]

    for token in tokens:
        candidate = _clean_token(token)
        if not candidate or candidate.startswith("-"):
            continue
        # Values such as ``PYTHONPATH=a:b`` are inspected component by
        # component.  Plain words and URLs are not filesystem paths.
        values = candidate.split("=", 1)[-1].split(":")
        for value in values:
            value = _clean_token(value)
            if not value or value.startswith(("http://", "https://")):
                continue
            if not (value.startswith(("/", "../", "./", "~/")) or "/../" in value):
                continue
            if value.startswith(_SYSTEM_READ_PREFIXES):
                continue
            try:
                resolved = (cwd / value).resolve() if not value.startswith("/") else Path(value).resolve()
                resolved.relative_to(allowed_root)
            except (OSError, RuntimeError, ValueError):
                reasons.append(f"out_of_workspace_access:{value[:160]}")
    return reasons


def evaluate_hook(event: dict[str, Any]) -> dict[str, Any]:
    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input")
    command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
    cwd = Path(str(event.get("cwd") or ".")).resolve()
    allowed_raw = os.environ.get("REPOPROOF_CODEX_ALLOWED_ROOT", "")
    reasons: list[str] = []
    if os.environ.get("REPOPROOF_CODEX_NO_TOOLS") == "1":
        reasons.append("codex_text_mode_tools_disabled")
    if not allowed_raw:
        reasons.append("codex_allowed_root_missing")
        allowed_root = cwd
    else:
        allowed_root = Path(allowed_raw).resolve()
        try:
            cwd.relative_to(allowed_root)
        except ValueError:
            reasons.append("codex_hook_cwd_outside_allowed_root")

    if tool_name not in {"Bash", "apply_patch"}:
        reasons.append(f"codex_tool_not_allowed:{tool_name or 'UNKNOWN'}")
    if not command:
        reasons.append("codex_empty_tool_command")
    else:
        decision = evaluate_agent_command(command)
        if not decision.allowed:
            reasons.extend(decision.reasons)
        reasons.extend(_path_escape_reasons(command, cwd=cwd, allowed_root=allowed_root))

    deduped = list(dict.fromkeys(reasons))
    audit = {
        "policy_version": HOOK_POLICY_VERSION,
        "tool_name": tool_name,
        "command": command[:2000],
        "allowed": not deduped,
        "reasons": deduped or ["ok"],
    }
    _record(audit)
    if not deduped:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "; ".join(deduped)[:1000],
        }
    }


def main() -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("hook input is not an object")
        output = evaluate_hook(event)
    except Exception as exc:  # noqa: BLE001 - malformed hook input must fail closed
        _record({
            "policy_version": HOOK_POLICY_VERSION,
            "tool_name": "UNKNOWN",
            "command": "",
            "allowed": False,
            "reasons": [f"codex_hook_failure:{type(exc).__name__}"],
        })
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"RepoProof hook failure:{type(exc).__name__}",
            }
        }
    if output:
        print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
