"""Anthropic-native gateway channel (explicitly selected, never a fallback).

One self-hosted gateway can front two upstreams: an OpenAI-compatible
surface (``/v1/chat/completions``) and Anthropic's own (``/v1/messages``).
They do not share credentials, and only the Anthropic surface can
*enforce* a JSON schema on Claude models — the OpenAI shim accepts
``response_format={"type": "json_schema", "strict": true}`` and then
returns fenced prose that ignores the schema.  Structured drafting on
this channel therefore speaks the Anthropic protocol directly and forces
one tool call whose ``input_schema`` is the contract; a reply that is not
that tool call is a public protocol failure, never free text quietly
accepted.

Selection is explicit (``REPOPROOF_DRAFTER_BACKEND=anthropic-gateway``).
This module never activates as a silent fallback for another channel:
switching channels changes the billing subject, the model identity and
reproducibility, so it stays an operator decision.

The transport is stdlib ``urllib`` on purpose.  The litellm build pinned
here mistranslates structured output for this API version (it sends the
deprecated ``output_format`` field), and its model-capability table is
fetched over the network, which has already made drafting depend on
reaching a third-party host.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 16000
STRUCTURED_TOOL_NAME = "emit"

# Public, stable classification of one gateway failure.  Never carries the
# provider's raw body, the api key, or the host.
TIMEOUT = "ANTHROPIC_GATEWAY_TIMEOUT"
CONNECTIVITY = "ANTHROPIC_GATEWAY_CONNECTIVITY_ERROR"
AUTH_FAILED = "ANTHROPIC_GATEWAY_AUTH_FAILED"
MODEL_NOT_AVAILABLE = "ANTHROPIC_GATEWAY_MODEL_NOT_AVAILABLE"
RATE_LIMITED = "ANTHROPIC_GATEWAY_RATE_LIMITED"
UNAVAILABLE = "ANTHROPIC_GATEWAY_UNAVAILABLE"
BAD_REQUEST = "ANTHROPIC_GATEWAY_BAD_REQUEST"
PROTOCOL_INVALID = "ANTHROPIC_GATEWAY_PROTOCOL_INVALID"
STRUCTURED_OUTPUT_NOT_ENFORCED = "ANTHROPIC_STRUCTURED_OUTPUT_NOT_ENFORCED"
NOT_CONFIGURED = "ANTHROPIC_GATEWAY_NOT_CONFIGURED"


class AnthropicGatewayError(RuntimeError):
    """A public gateway failure code plus an optional bounded public detail."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class AnthropicGatewayConfig:
    """Everything one Anthropic-protocol request needs, key excluded from evidence."""

    model_name: str
    api_base: str
    api_key: str
    temperature_policy: str = "provider_default"  # "0" | "provider_default"
    max_tokens: int = DEFAULT_MAX_TOKENS

    def __post_init__(self) -> None:
        if self.temperature_policy not in {"0", "provider_default"}:
            raise AnthropicGatewayError(
                NOT_CONFIGURED, "temperature policy must be 0 or provider_default"
            )

    @property
    def messages_url(self) -> str:
        base = self.api_base.rstrip("/")
        # Accept both the bare gateway host and an explicit /v1 base so one
        # value can be shared with the OpenAI-compatible agent channel.
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        return f"{base}/v1/messages"

    @property
    def api_base_summary(self) -> str:
        parsed = urlparse(self.api_base)
        return f"{parsed.scheme}://<redacted-host>{parsed.path}"


@dataclass
class GatewayReply:
    """One completed request: public text plus honest accounting."""

    text: str
    usage: dict[str, int] = field(default_factory=dict)
    temperature_dropped: bool = False
    structured: bool = False


Transport = Callable[[str, bytes, dict[str, str], float], "tuple[int, bytes]"]


def _urllib_transport(
    url: str, payload: bytes, headers: dict[str, str], timeout_s: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read()
    except TimeoutError as exc:
        raise AnthropicGatewayError(TIMEOUT) from exc
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", "")).lower()
        if "timed out" in reason or "timeout" in reason:
            raise AnthropicGatewayError(TIMEOUT) from exc
        raise AnthropicGatewayError(CONNECTIVITY) from exc
    except OSError as exc:
        raise AnthropicGatewayError(CONNECTIVITY) from exc


def gateway_config_from_env(
    environ: dict[str, str] | None = None,
) -> AnthropicGatewayConfig:
    """Build the channel from explicitly named variables; report missing names only."""

    env = os.environ if environ is None else environ
    base = env.get("REPOPROOF_ANTHROPIC_BASE") or ""
    key = env.get("REPOPROOF_ANTHROPIC_KEY") or ""
    model = (
        env.get("REPOPROOF_ANTHROPIC_MODEL")
        or env.get("REPOPROOF_MODEL")
        or env.get("REPOPROOF_ANTHROPIC_DEFAULT")
        or ""
    )
    missing = [
        name
        for name, value in (
            ("REPOPROOF_ANTHROPIC_BASE", base),
            ("REPOPROOF_ANTHROPIC_KEY", key),
            ("REPOPROOF_ANTHROPIC_MODEL|REPOPROOF_MODEL", model),
        )
        if not value.strip()
    ]
    if missing:
        raise AnthropicGatewayError(NOT_CONFIGURED, "missing: " + ",".join(missing))
    policy = (env.get("REPOPROOF_TEMPERATURE_POLICY") or "provider_default").strip()
    return AnthropicGatewayConfig(
        model_name=model.strip(),
        api_base=base.strip(),
        api_key=key.strip(),
        temperature_policy=policy,
    )


def _classify(status: int, body: bytes) -> AnthropicGatewayError:
    message = ""
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            error = parsed.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "")
    except ValueError:
        message = ""
    detail = " ".join(message.split())[:200]
    if status in {401, 403}:
        return AnthropicGatewayError(AUTH_FAILED)
    if status == 404:
        return AnthropicGatewayError(MODEL_NOT_AVAILABLE, detail)
    if status == 429:
        return AnthropicGatewayError(RATE_LIMITED, detail)
    if status >= 500:
        return AnthropicGatewayError(UNAVAILABLE, detail)
    return AnthropicGatewayError(BAD_REQUEST, detail)


def _rejects_temperature(error: AnthropicGatewayError) -> bool:
    return error.code == BAD_REQUEST and "temperature" in error.detail.lower()


def call_messages(
    config: AnthropicGatewayConfig,
    *,
    system: str,
    user: str,
    schema: dict[str, Any] | None = None,
    timeout_s: float = 300.0,
    transport: Transport | None = None,
) -> GatewayReply:
    """One bounded Anthropic request; a schema is enforced by a forced tool call.

    ``temperature=0`` is attempted only when the configured policy asks for it,
    and a provider that explicitly rejects that one parameter causes exactly one
    retry without it, recorded as ``temperature_dropped``.  No other parameter is
    ever dropped, and no other failure is retried here: network retries and JSON
    repair are Harness decisions made by the caller.
    """

    send = transport or _urllib_transport
    body: dict[str, Any] = {
        "model": config.model_name,
        "max_tokens": config.max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if schema is not None:
        body["tools"] = [
            {
                "name": STRUCTURED_TOOL_NAME,
                "description": "Return the answer as this exact object.",
                "input_schema": schema,
            }
        ]
        body["tool_choice"] = {"type": "tool", "name": STRUCTURED_TOOL_NAME}
    headers = {
        "Content-Type": "application/json",
        "x-api-key": config.api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }

    attempts: list[dict[str, Any]] = []
    if config.temperature_policy == "0":
        attempts.append({**body, "temperature": 0})
    attempts.append(body)

    last_error: AnthropicGatewayError | None = None
    for index, payload in enumerate(attempts):
        status, raw = send(
            config.messages_url,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers,
            timeout_s,
        )
        if status != 200:
            error = _classify(status, raw)
            # Only the temperature parameter may be dropped, only when the
            # provider names it, and only once — the drop is then recorded.
            if index == 0 and len(attempts) > 1 and _rejects_temperature(error):
                last_error = error
                continue
            raise error
        return _reply(raw, schema=schema, temperature_dropped=index > 0)
    raise last_error or AnthropicGatewayError(PROTOCOL_INVALID)


def _reply(
    raw: bytes, *, schema: dict[str, Any] | None, temperature_dropped: bool
) -> GatewayReply:
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise AnthropicGatewayError(PROTOCOL_INVALID, "response is not JSON") from exc
    if not isinstance(document, dict):
        raise AnthropicGatewayError(PROTOCOL_INVALID, "response is not an object")
    content = document.get("content")
    if not isinstance(content, list):
        raise AnthropicGatewayError(PROTOCOL_INVALID, "response has no content list")
    raw_document_usage = document.get("usage")
    raw_usage: dict = raw_document_usage if isinstance(raw_document_usage, dict) else {}
    usage = {
        "prompt_tokens": int(raw_usage.get("input_tokens") or 0),
        "completion_tokens": int(raw_usage.get("output_tokens") or 0),
    }

    if schema is not None:
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                arguments = block.get("input")
                if not isinstance(arguments, dict):
                    raise AnthropicGatewayError(
                        STRUCTURED_OUTPUT_NOT_ENFORCED, "tool input is not an object"
                    )
                return GatewayReply(
                    text=json.dumps(arguments, ensure_ascii=False),
                    usage=usage,
                    temperature_dropped=temperature_dropped,
                    structured=True,
                )
        # A schema was requested and the provider answered with prose.  Accepting
        # it would recreate the reliability bug the schema exists to prevent.
        raise AnthropicGatewayError(
            STRUCTURED_OUTPUT_NOT_ENFORCED,
            "provider returned no tool_use block for a forced tool call",
        )

    texts = [
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return GatewayReply(
        text="\n".join(part for part in texts if part),
        usage=usage,
        temperature_dropped=temperature_dropped,
    )
