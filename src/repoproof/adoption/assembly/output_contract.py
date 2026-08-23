"""Deterministic validation for RFC-011 machine output contracts.

This module is deliberately dependency-light and contains no test/harness
state.  Freeze adequacy, generated runtime checks, release audit and future
MCP projection all consume the same ``ToolOutputContract`` data model.
"""

from __future__ import annotations

import json
import math
import re
import shlex
from typing import Any

from repoproof.domain.models import ToolOutputContract

ERROR_PREFIX = "[tool-output-contract]"


class OutputContractViolation(ValueError):
    """Stable, non-sensitive runtime failure for an invalid tool stdout."""


def normalize_output_format(format_name: str) -> str:
    """Map a human format label to text/json/json_object/json_array/json_lines."""
    normalized = re.sub(r"[^a-z0-9]+", "_", format_name.strip().lower()).strip("_")
    if normalized in {"jsonl", "ndjson"} or (
            "json" in normalized and "line" in normalized):
        return "json_lines"
    if "json" in normalized:
        if "object" in normalized:
            return "json_object"
        if "array" in normalized or "list" in normalized:
            return "json_array"
        return "json"
    return "text"


def is_structured_output_format(format_name: str) -> bool:
    return normalize_output_format(format_name) != "text"


def is_capability_output_invocation(input_arg: str | None) -> bool:
    """Exclude CLI metadata paths whose stdout is not capability output.

    ``argparse --help`` is intentionally human-readable even when successful
    capability invocations return JSON.  It is already guarded by the
    interface regression node and must not be mistaken for a JSON golden.
    """
    if input_arg is None:
        return True
    try:
        args = shlex.split(input_arg)
    except ValueError:
        return True
    return not any(arg in {"-h", "--help", "--version"} for arg in args)


def output_contract_matches_format(
        format_name: str, contract: ToolOutputContract | dict[str, Any]) -> bool:
    """Whether the executable root agrees with the human-readable format label."""
    parsed = (contract if isinstance(contract, ToolOutputContract)
              else ToolOutputContract.model_validate(contract))
    family = normalize_output_format(format_name)
    if family == "text":
        return parsed.root_type == "text"
    if parsed.root_type == "text":
        return False
    if family == "json_lines":
        return parsed.root_type == "json_lines"
    if family == "json_object":
        return parsed.root_type == "object"
    if family == "json_array":
        return parsed.root_type == "array"
    return parsed.root_type in {"json", "object", "array"}


def _type_ok(value: object, expected: str) -> bool:
    if expected == "any":
        return True
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return False


def _reject_json_constant(constant: str) -> None:
    """Reject Python's non-standard JSON number extensions."""
    raise ValueError(f"non-standard JSON constant: {constant}")


def _strict_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _strict_json_loads(text: str) -> Any:
    return json.loads(
        text,
        parse_constant=_reject_json_constant,
        parse_float=_strict_json_float,
    )


def _validate_value(value: object, contract: ToolOutputContract, *, location: str) -> list[str]:
    errors: list[str] = []
    expected = contract.root_type
    if expected == "object" and not isinstance(value, dict):
        return [f"{location}: wrong_root expected=object"]
    if expected == "array" and not isinstance(value, list):
        return [f"{location}: wrong_root expected=array"]
    if contract.required:
        if not isinstance(value, dict):
            return [f"{location}: wrong_root required_fields_need=object"]
        for field, field_type in contract.required.items():
            if field not in value:
                errors.append(f"{location}: missing_required field={field}")
            elif not _type_ok(value[field], field_type):
                errors.append(
                    f"{location}: wrong_type field={field} expected={field_type}")
    return errors


def validate_output_text(
        text: str, contract: ToolOutputContract | dict[str, Any]) -> list[str]:
    """Return deterministic validation errors; never include stdout contents."""
    parsed = (contract if isinstance(contract, ToolOutputContract)
              else ToolOutputContract.model_validate(contract))
    if parsed.root_type == "text":
        return []
    if parsed.root_type == "json_lines":
        lines = [(i, line) for i, line in enumerate(text.splitlines(), start=1)
                 if line.strip()]
        if not lines:
            return ["json_lines: no_nonempty_lines"]
        errors: list[str] = []
        for line_no, line in lines:
            try:
                value = _strict_json_loads(line)
            except (ValueError, UnicodeDecodeError):
                errors.append(f"line={line_no}: invalid_json")
                continue
            errors.extend(_validate_value(value, parsed, location=f"line={line_no}"))
        return errors
    try:
        value = _strict_json_loads(text)
    except (ValueError, UnicodeDecodeError):
        return ["document: invalid_json"]
    return _validate_value(value, parsed, location="document")


def assert_output_text(
        text: str, contract: ToolOutputContract | dict[str, Any]) -> None:
    """Raise a stable-prefixed violation when ``text`` breaks ``contract``."""
    errors = validate_output_text(text, contract)
    if errors:
        raise OutputContractViolation(f"{ERROR_PREFIX} {'; '.join(errors)}")


def mcp_output_projection(
    contract: ToolOutputContract | dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Project the contract into MCP's object-root ``outputSchema``.

    The stable MCP revisions that introduced structured tool output require an
    object at the schema root.  Object-shaped tool output therefore projects
    directly; text, arbitrary JSON, arrays and JSON Lines use a deterministic
    wrapper.  ``mode`` tells the standalone generated server how to construct
    matching ``structuredContent`` from the already-validated stdout.
    """

    parsed = (
        contract
        if isinstance(contract, ToolOutputContract)
        else ToolOutputContract.model_validate(contract)
    )

    def field_schema(field_type: str) -> dict[str, str]:
        if field_type == "any":
            return {}
        return {"type": field_type}

    object_properties = {
        name: field_schema(field_type)
        for name, field_type in sorted(parsed.required.items())
    }
    object_schema: dict[str, Any] = {
        "type": "object",
        "properties": object_properties,
    }
    if parsed.required:
        object_schema["required"] = sorted(parsed.required)

    if parsed.root_type == "json_lines":
        return {
            "type": "object",
            "properties": {
                "lines": {
                    "type": "array",
                    "items": object_schema if parsed.required else {},
                },
            },
            "required": ["lines"],
        }, "json_lines"
    if parsed.root_type == "object" or parsed.required:
        return object_schema, "object"
    if parsed.root_type == "array":
        return {
            "type": "object",
            "properties": {"value": {"type": "array"}},
            "required": ["value"],
        }, "array"
    if parsed.root_type == "json":
        return {
            "type": "object",
            "properties": {"value": {}},
            "required": ["value"],
        }, "json"
    return {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": f"Tool stdout ({parsed.media_type})",
            },
        },
        "required": ["text"],
    }, "text"


def render_pytest_validator(contract: ToolOutputContract | dict[str, Any]) -> str:
    """Render a standalone validator for generated/public tool pytest files.

    Tool packages must remain independently runnable without importing
    RepoProof, so the generated test carries this small standard-library-only
    projection.  The normalized contract data remains its sole fact source.
    """
    parsed = (contract if isinstance(contract, ToolOutputContract)
              else ToolOutputContract.model_validate(contract))
    literal = repr(parsed.model_dump())
    template = '''

# RFC-011: independent validation of actual stdout (not expected/golden text).
import json as _rp_json
import math as _rp_math

_RP_OUTPUT_CONTRACT = __RP_CONTRACT__


def _rp_reject_json_constant(constant):
    raise ValueError(f"non-standard JSON constant: {constant}")


def _rp_strict_json_float(value):
    parsed = float(value)
    if not _rp_math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number: {value}")
    return parsed


def _rp_json_loads(text):
    return _rp_json.loads(
        text,
        parse_constant=_rp_reject_json_constant,
        parse_float=_rp_strict_json_float,
    )


def _rp_type_ok(value, expected):
    if expected == "any":
        return True
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    return False


def _rp_validate_value(value, location):
    root = _RP_OUTPUT_CONTRACT["root_type"]
    required = _RP_OUTPUT_CONTRACT["required"]
    if root == "object" and not isinstance(value, dict):
        return [f"{location}: wrong_root expected=object"]
    if root == "array" and not isinstance(value, list):
        return [f"{location}: wrong_root expected=array"]
    if required and not isinstance(value, dict):
        return [f"{location}: wrong_root required_fields_need=object"]
    errors = []
    for field, field_type in required.items():
        if field not in value:
            errors.append(f"{location}: missing_required field={field}")
        elif not _rp_type_ok(value[field], field_type):
            errors.append(
                f"{location}: wrong_type field={field} expected={field_type}")
    return errors


def _assert_output_contract(text):
    root = _RP_OUTPUT_CONTRACT["root_type"]
    if root == "text":
        return
    errors = []
    if root == "json_lines":
        lines = [
            (i, line) for i, line in enumerate(text.splitlines(), 1) if line.strip()
        ]
        if not lines:
            errors.append("json_lines: no_nonempty_lines")
        for line_no, line in lines:
            try:
                value = _rp_json_loads(line)
            except ValueError:
                errors.append(f"line={line_no}: invalid_json")
                continue
            errors.extend(_rp_validate_value(value, f"line={line_no}"))
    else:
        try:
            value = _rp_json_loads(text)
        except ValueError:
            errors.append("document: invalid_json")
        else:
            errors.extend(_rp_validate_value(value, "document"))
    assert not errors, __RP_PREFIX__ + " " + "; ".join(errors)
'''
    return (template.replace("__RP_CONTRACT__", literal)
            .replace("__RP_PREFIX__", repr(ERROR_PREFIX)))
