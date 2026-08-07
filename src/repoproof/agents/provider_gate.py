"""ProviderAdmissionGate (Gate 3C prerequisite).

Runs BEFORE DefaultAgent.run() and BEFORE any agent container exists,
using exactly the configuration the real run will use (provider, model,
api base, action protocol, temperature policy). The normalized config
is hashed to ``provider_config_sha256``; preflight result and the real
run must bind the SAME hash.

On failure: no agent, no agent container, agent_model_call_count stays
0, a structured BLOCKED with a typed status and redacted evidence.
Statuses: PROVIDER_READY / AUTH_FAILED / MODEL_NOT_AVAILABLE /
PROVIDER_UNAVAILABLE / RATE_LIMITED / PROVIDER_TIMEOUT /
ACTION_PROTOCOL_UNSUPPORTED.

Hard wall budget: 60 seconds. No automatic model/provider switching.
The same frozen model MAY be probed with native then textbased action
protocols; the first working protocol is FROZEN for the real run.
Preflight calls/tokens/cost/wall metrics are recorded separately from
agent metrics.

The API key lives only in this host process; it is excluded from the
config hash and from all evidence.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from repoproof.domain.models import sha256_bytes

PREFLIGHT_WALL_BUDGET_S = 60.0

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The bash command to execute"}},
            "required": ["command"],
        },
    },
}

_TEXTBASED_RE = re.compile(r"```(?:bash|sh)?\s*\n?(.+?)\n?```", re.DOTALL)


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    model_name: str
    api_base: str
    api_key: str  # excluded from hash + evidence
    temperature_policy: str = "0"  # "0" | "provider_default"
    action_protocol: str = "auto"  # "auto" | "native" | "textbased"

    PROVIDER_TYPE = "openai-compatible"

    def normalized(self) -> dict:
        """Canonical hash input (Gate 4B): provider TYPE (never a
        display label), a redacted api-base fingerprint (sha256 of the
        normalized base — the raw URL never enters evidence), model,
        action protocol and temperature policy. No labels, no config
        source, no notes, no key."""
        return {
            "provider_type": self.PROVIDER_TYPE,
            "api_base_fingerprint": sha256_bytes(self.api_base.rstrip("/").encode())[:16],
            "model_name": self.model_name,
            "action_protocol": self.action_protocol,
            "temperature_policy": self.temperature_policy,
        }

    @property
    def config_sha256(self) -> str:
        return sha256_bytes(json.dumps(self.normalized(), sort_keys=True).encode())

    @property
    def api_base_summary(self) -> str:
        parsed = urlparse(self.api_base)
        return f"{parsed.scheme}://<redacted-host>{parsed.path}"


@dataclass
class PreflightResult:
    status: str
    provider_config_sha256: str
    model_name: str
    api_base_summary: str
    action_protocol: str | None
    temperature: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost: float | str
    wall_time_s: float
    evidence: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.status == "PROVIDER_READY"

    def summary(self) -> dict:
        return {
            "status": self.status,
            "provider_config_sha256": self.provider_config_sha256,
            "model_name": self.model_name,
            "api_base": self.api_base_summary,
            "action_protocol": self.action_protocol,
            "temperature": self.temperature,
            "preflight_calls": self.calls,
            "preflight_input_tokens": self.input_tokens,
            "preflight_output_tokens": self.output_tokens,
            "preflight_cost": self.cost,
            "preflight_wall_time_s": round(self.wall_time_s, 1),
            "evidence": self.evidence,
        }


Transport = Callable[[dict, float], tuple[int, dict]]
"""(payload, timeout_s) -> (http_status, response_json). Injectable for
mock tests; the default posts to <api_base>/chat/completions."""


def default_transport(config: ProviderConfig) -> Transport:
    def _post(payload: dict, timeout_s: float) -> tuple[int, dict]:
        req = urllib.request.Request(
            config.api_base.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read())
            except Exception:  # noqa: BLE001
                body = {"error": {"message": "unparseable error body"}}
            return exc.code, body
        except TimeoutError as exc:
            raise exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError(str(exc)) from exc
            raise ConnectionError(str(exc.reason)[:120]) from exc

    return _post


def _classify_http(status: int, body: dict) -> str | None:
    msg = json.dumps(body)[:300].lower() if isinstance(body, dict) else str(body)[:300].lower()
    if status == 401 or status == 403:
        return "AUTH_FAILED"
    if status == 404 or "model_not_found" in msg or "does not exist" in msg or "unknown model" in msg:
        return "MODEL_NOT_AVAILABLE"
    if status == 429:
        return "RATE_LIMITED"
    if status >= 500:
        return "PROVIDER_UNAVAILABLE"
    return None


def _extract_native_action(body: dict) -> dict | None:
    try:
        msg = body["choices"][0]["message"]
        for tc in msg.get("tool_calls") or []:
            if tc.get("function", {}).get("name") == "bash":
                args = json.loads(tc["function"].get("arguments") or "{}")
                if isinstance(args, dict) and "command" in args:
                    return {"command": args["command"]}
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None
    return None


def _extract_textbased_action(body: dict) -> dict | None:
    try:
        content = body["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, TypeError):
        return None
    matches = _TEXTBASED_RE.findall(content)
    if len(matches) == 1:
        return {"command": matches[0].strip()}
    return None


def _usage(body: dict) -> tuple[int, int]:
    u = body.get("usage") or {}
    return int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)


def run_preflight(
    config: ProviderConfig,
    *,
    transport: Transport | None = None,
    wall_budget_s: float = PREFLIGHT_WALL_BUDGET_S,
) -> PreflightResult:
    post = transport or default_transport(config)
    t0 = time.monotonic()
    calls = 0
    tok_in = tok_out = 0
    evidence: list[str] = []
    temperature = config.temperature_policy

    def result(status: str, protocol: str | None) -> PreflightResult:
        return PreflightResult(
            status=status,
            provider_config_sha256=config.config_sha256,
            model_name=config.model_name,
            api_base_summary=config.api_base_summary,
            action_protocol=protocol,
            temperature=temperature,
            calls=calls,
            input_tokens=tok_in,
            output_tokens=tok_out,
            cost="UNKNOWN" if calls else 0.0,
            wall_time_s=time.monotonic() - t0,
            evidence=evidence,
        )

    def remaining() -> float:
        return wall_budget_s - (time.monotonic() - t0)

    def attempt(payload: dict) -> tuple[str | None, dict | None]:
        """Returns (typed_error | None, body | None)."""
        nonlocal calls, tok_in, tok_out, temperature
        if remaining() <= 1:
            evidence.append("wall budget exhausted before attempt")
            return "PROVIDER_TIMEOUT", None
        try:
            calls += 1
            status, body = post(payload, min(remaining(), 30.0))
        except TimeoutError:
            evidence.append("request timed out")
            return "PROVIDER_TIMEOUT", None
        except ConnectionError as exc:
            evidence.append(f"connection error: {exc}")
            return "PROVIDER_UNAVAILABLE", None
        typed = _classify_http(status, body)
        if typed:
            evidence.append(f"http {status} -> {typed}")
            # temperature rejection is a 400 special-case, not typed above
            return typed, body
        if status == 400 and "temperature" in json.dumps(body)[:400].lower() and temperature == "0":
            evidence.append("provider rejected temperature=0; falling back to provider_default")
            temperature = "provider_default"
            return "RETRY_WITHOUT_TEMPERATURE", body
        if status != 200:
            evidence.append(f"unexpected http {status}")
            return "PROVIDER_UNAVAILABLE", body
        i, o = _usage(body)
        tok_in += i
        tok_out += o
        return None, body

    def base_payload() -> dict:
        p: dict = {
            "model": config.model_name,
            "messages": [
                {"role": "system", "content": "You are a preflight probe. Use the bash tool."},
                {"role": "user", "content": "Run exactly: echo PREFLIGHT_OK"},
            ],
            "max_tokens": 80,
        }
        if temperature == "0":
            p["temperature"] = 0
        return p

    # ---- native tool-call probe (with one temperature fallback) ----
    protocols = ["native", "textbased"] if config.action_protocol == "auto" else [config.action_protocol]
    last_error: str | None = None
    for protocol in protocols:
        payload = base_payload()
        if protocol == "native":
            payload["tools"] = [BASH_TOOL]
        else:
            payload["messages"][0]["content"] = (
                "You are a preflight probe. Reply with exactly one bash command "
                "in a single triple-backtick block."
            )
        typed, body = attempt(payload)
        if typed == "RETRY_WITHOUT_TEMPERATURE":
            payload.pop("temperature", None)
            typed, body = attempt(payload)
        if typed:
            last_error = typed
            hard = ("AUTH_FAILED", "MODEL_NOT_AVAILABLE", "RATE_LIMITED",
                    "PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT")
            if typed in hard:
                return result(typed, None)
            continue
        action = _extract_native_action(body) if protocol == "native" else _extract_textbased_action(body)
        if action and "echo" in action.get("command", ""):
            evidence.append(f"{protocol} action parsed: {action['command'][:60]!r}")
            return result("PROVIDER_READY", protocol)
        evidence.append(f"{protocol} response had no parseable bash action")
        last_error = "ACTION_PROTOCOL_UNSUPPORTED"
    return result(last_error or "ACTION_PROTOCOL_UNSUPPORTED", None)
