"""Deterministic validation for RFC-011 machine output contracts.

This module is deliberately dependency-light and contains no test/harness
state.  Freeze adequacy, generated runtime checks, release audit and future
MCP projection all consume the same ``ToolOutputContract`` data model.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import shlex
import xml.etree.ElementTree as ET
from copy import deepcopy
from typing import Any

from repoproof.domain.models import ToolOutputContract

ERROR_PREFIX = "[tool-output-contract]"


class OutputContractViolation(ValueError):
    """Stable, non-sensitive runtime failure for an invalid tool stdout."""


_PUBLIC_TEXT_PROFILE_SPECS: dict[str, dict[str, Any]] = {
    "plain_text_v1": {
        "representation_rules": [
            "The artifact is deterministic UTF-8 text and contains no NUL byte."
        ],
        "semantic_verifier_guidance": (
            "Evaluate the task commitments from the input and artifact; the profile "
            "adds no task-specific structure."
        ),
    },
    "ris_interchange_v1": {
        "representation_rules": [
            "Every nonblank field line is an RIS tag: two uppercase alphanumeric "
            "characters, two spaces, a hyphen, and an optional value; six-space "
            "continuation lines are allowed only inside a record.",
            "Each record begins with TY and ends with ER; nested, orphaned, or "
            "unterminated records are invalid and at least one complete record is required.",
            "Presentation-only ordinal/header lines outside TY..ER records are forbidden.",
        ],
        "semantic_verifier_guidance": (
            "Use the pinned upstream to parse both the input and delivered artifact, "
            "then compare the task-required record semantics. Do not require artifact "
            "bytes to equal raw upstream serialization when that serialization adds "
            "presentation framing forbidden by this profile."
        ),
    },
    "csv_table_v1": {
        "representation_rules": [
            "Parse with the standard strict CSV dialect; require at least one row.",
            "The header is nonempty, every header cell is nonblank and unique, and "
            "every data row has the same number of columns.",
        ],
        "semantic_verifier_guidance": (
            "Parse the delivered table into rows and cells before checking task "
            "semantics; do not compare producer-specific serialized bytes."
        ),
    },
    "tsv_table_v1": {
        "representation_rules": [
            "Parse with the standard strict Excel-tab dialect; require at least one row.",
            "The header is nonempty, every header cell is nonblank and unique, and "
            "every data row has the same number of columns.",
        ],
        "semantic_verifier_guidance": (
            "Parse the delivered table into rows and cells before checking task "
            "semantics; do not compare producer-specific serialized bytes."
        ),
    },
    "markdown_document_v1": {
        "representation_rules": [
            "The artifact is nonempty UTF-8 text and must not be a JSON object or array document."
        ],
        "semantic_verifier_guidance": (
            "Parse the task-required Markdown sections or tables and check their "
            "semantic values; formatting bytes alone are not task semantics."
        ),
    },
    "safe_self_contained_xhtml_v1": {
        "representation_rules": [
            "The artifact is XML-parseable with an html root and contains no DOCTYPE or entity.",
            "Scripts, embedded frames/objects, SVG/MathML, forms, external resources, "
            "event handlers, style elements/attributes, and non-fragment links are forbidden.",
        ],
        "semantic_verifier_guidance": (
            "Parse the delivered DOM and check task values in elements/attributes; "
            "do not compare producer-specific HTML byte formatting."
        ),
    },
}


def public_validation_profile_spec(
    validation_profile: str | None,
) -> dict[str, Any]:
    """Return the Core-owned public rules for an output validation profile."""

    profile_id = validation_profile or "plain_text_v1"
    try:
        spec = deepcopy(_PUBLIC_TEXT_PROFILE_SPECS[profile_id])
    except KeyError as exc:
        raise ValueError(f"unknown validation profile: {profile_id}") from exc
    return {"profile_id": profile_id, **spec}


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


def expected_text_media_type(format_name: str) -> str:
    """Return the executable media type for a recognized text artifact.

    ``root_type=text`` alone is not enough: without this binding an RIS/TSV/
    Markdown/HTML label paired with ``text/plain`` would bypass the dedicated
    parser while still looking correct in the human-facing contract.
    """

    normalized = re.sub(
        r"[^a-z0-9]+", "_", format_name.strip().lower()
    ).strip("_")
    tokens = set(normalized.split("_"))
    ris_labels = {
        "research_info_system",
        "research_info_systems",
        "research_information_system",
        "research_information_systems",
    }
    if "ris" in tokens or any(label in normalized for label in ris_labels):
        return "application/x-research-info-systems"
    if "tsv" in tokens or "tab_separated" in normalized:
        return "text/tab-separated-values"
    if "markdown" in tokens or normalized in {"md", "commonmark"}:
        return "text/markdown"
    if "xhtml" in tokens:
        return "application/xhtml+xml"
    if "html" in tokens:
        return "text/html"
    return "text/plain"


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
        declared_media = parsed.media_type.split(";", 1)[0].strip().lower()
        return (
            parsed.root_type == "text"
            and declared_media == expected_text_media_type(format_name)
        )
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


def _validate_text_profile(
    text: str,
    validation_profile: str | None,
) -> list[str]:
    """Execute only the text rules explicitly named by the frozen contract.

    MIME identifies a representation; it is not permission for Core to infer
    extra policy.  The versioned validation profile comes from the Product
    delivery registry and is visible in the contract the user confirms.
    """

    if "\x00" in text:
        return ["text: contains_nul"]
    if validation_profile in {None, "plain_text_v1"}:
        return []
    if validation_profile == "ris_interchange_v1":
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return ["ris: no_records"]
        tag = re.compile(r"^[A-Z0-9]{2}  -(?: .*)?$")
        continuation = re.compile(r"^\s{6}\S.*$")
        in_record = False
        records = 0
        errors: list[str] = []
        for line_no, line in enumerate(lines, start=1):
            if continuation.fullmatch(line) and in_record:
                continue
            if not tag.fullmatch(line):
                errors.append(f"ris: line={line_no} invalid_tag")
                continue
            current = line[:2]
            if current == "TY":
                if in_record:
                    errors.append(f"ris: line={line_no} nested_record")
                in_record = True
            elif current == "ER":
                if not in_record:
                    errors.append(f"ris: line={line_no} orphan_end")
                else:
                    records += 1
                    in_record = False
            elif not in_record:
                errors.append(f"ris: line={line_no} field_outside_record")
        if in_record:
            errors.append("ris: unterminated_record")
        if records == 0:
            errors.append("ris: no_complete_records")
        return errors
    if validation_profile in {"csv_table_v1", "tsv_table_v1"}:
        table_kind = "tsv" if validation_profile == "tsv_table_v1" else "csv"
        try:
            dialect = "excel-tab" if validation_profile == "tsv_table_v1" else "excel"
            rows = list(csv.reader(io.StringIO(text), dialect=dialect, strict=True))
        except (csv.Error, UnicodeError):
            return [f"{table_kind}: invalid_document"]
        if not rows:
            return [f"{table_kind}: no_rows"]
        width = len(rows[0])
        if width == 0 or any(not cell.strip() for cell in rows[0]):
            return [f"{table_kind}: invalid_header"]
        if len(set(rows[0])) != width:
            return [f"{table_kind}: duplicate_header"]
        if any(len(row) != width for row in rows[1:]):
            return [f"{table_kind}: inconsistent_columns"]
        return []
    if validation_profile == "markdown_document_v1":
        if not text.strip():
            return ["markdown: empty_document"]
        try:
            value = _strict_json_loads(text)
        except (ValueError, UnicodeError):
            value = None
        if isinstance(value, (dict, list)):
            return ["markdown: json_document"]
        return []
    if validation_profile == "safe_self_contained_xhtml_v1":
        if re.search(r"<!\s*(?:doctype|entity)\b", text, re.IGNORECASE):
            return ["html: doctype_or_entity_forbidden"]
        processing_targets = re.findall(
            r"<\?\s*([A-Za-z_:][A-Za-z0-9_.:-]*)",
            text,
        )
        if any(target.lower() != "xml" for target in processing_targets):
            return ["html: processing_instruction_forbidden"]
        try:
            root = ET.fromstring(text)
        except (ET.ParseError, ValueError):
            return ["html: invalid_xhtml"]
        if root.tag.rsplit("}", 1)[-1].lower() != "html":
            return ["html: root_not_html"]
        errors = []
        forbidden_elements = {
            "applet", "base", "embed", "form", "frame", "frameset",
            "iframe", "link", "math", "object", "script", "svg",
        }
        resource_attributes = {
            "action", "archive", "background", "base", "cite", "codebase",
            "data", "formaction", "icon", "longdesc", "manifest", "ping",
            "poster", "profile", "src", "srcset", "usemap",
        }
        for element in root.iter():
            local = element.tag.rsplit("}", 1)[-1].lower()
            if local in forbidden_elements:
                errors.append(f"html: element_forbidden={local}")
            if (local == "meta"
                    and str(element.attrib.get("http-equiv") or "").strip()):
                errors.append("html: meta_http_equiv_forbidden")
            if local == "style":
                errors.append("html: style_element_forbidden")
            for raw_name, raw_value in element.attrib.items():
                name = raw_name.rsplit("}", 1)[-1].lower()
                value = raw_value.strip().lower()
                if name.startswith("on"):
                    errors.append("html: event_handler_forbidden")
                elif name in resource_attributes and value:
                    errors.append(f"html: resource_attribute_forbidden={name}")
                elif name == "href" and value and not value.startswith("#"):
                    errors.append("html: external_href_forbidden")
                elif name == "style" and value:
                    errors.append("html: style_attribute_forbidden")
        return sorted(set(errors))
    return ["text: unknown_validation_profile"]


def validate_output_text(
        text: str, contract: ToolOutputContract | dict[str, Any]) -> list[str]:
    """Return deterministic validation errors; never include stdout contents."""
    parsed = (contract if isinstance(contract, ToolOutputContract)
              else ToolOutputContract.model_validate(contract))
    if parsed.root_type == "text":
        return _validate_text_profile(text, parsed.validation_profile)
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
    template = r'''

# RFC-011: independent validation of actual stdout (not expected/golden text).
import json as _rp_json
import math as _rp_math
import csv as _rp_csv
import io as _rp_io
import re as _rp_re
import xml.etree.ElementTree as _rp_etree

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


def _rp_validate_text_media(text):
    profile = _RP_OUTPUT_CONTRACT.get("validation_profile")
    if "\x00" in text:
        return ["text: contains_nul"]
    if profile is None or profile == "plain_text_v1":
        return []
    if profile == "ris_interchange_v1":
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return ["ris: no_records"]
        tag = _rp_re.compile(r"^[A-Z0-9]{2}  -(?: .*)?$")
        continuation = _rp_re.compile(r"^\s{6}\S.*$")
        in_record = False
        records = 0
        errors = []
        for line_no, line in enumerate(lines, 1):
            if continuation.fullmatch(line) and in_record:
                continue
            if not tag.fullmatch(line):
                errors.append(f"ris: line={line_no} invalid_tag")
                continue
            current = line[:2]
            if current == "TY":
                if in_record:
                    errors.append(f"ris: line={line_no} nested_record")
                in_record = True
            elif current == "ER":
                if not in_record:
                    errors.append(f"ris: line={line_no} orphan_end")
                else:
                    records += 1
                    in_record = False
            elif not in_record:
                errors.append(f"ris: line={line_no} field_outside_record")
        if in_record:
            errors.append("ris: unterminated_record")
        if records == 0:
            errors.append("ris: no_complete_records")
        return errors
    if profile in {"csv_table_v1", "tsv_table_v1"}:
        table_kind = "tsv" if profile == "tsv_table_v1" else "csv"
        try:
            dialect = "excel-tab" if profile == "tsv_table_v1" else "excel"
            rows = list(_rp_csv.reader(_rp_io.StringIO(text), dialect=dialect, strict=True))
        except (_rp_csv.Error, UnicodeError):
            return [f"{table_kind}: invalid_document"]
        if not rows:
            return [f"{table_kind}: no_rows"]
        width = len(rows[0])
        if width == 0 or any(not cell.strip() for cell in rows[0]):
            return [f"{table_kind}: invalid_header"]
        if len(set(rows[0])) != width:
            return [f"{table_kind}: duplicate_header"]
        if any(len(row) != width for row in rows[1:]):
            return [f"{table_kind}: inconsistent_columns"]
        return []
    if profile == "markdown_document_v1":
        if not text.strip():
            return ["markdown: empty_document"]
        try:
            value = _rp_json_loads(text)
        except (ValueError, UnicodeError):
            value = None
        if isinstance(value, (dict, list)):
            return ["markdown: json_document"]
        return []
    if profile == "safe_self_contained_xhtml_v1":
        if _rp_re.search(r"<!\s*(?:doctype|entity)\b", text, _rp_re.IGNORECASE):
            return ["html: doctype_or_entity_forbidden"]
        processing_targets = _rp_re.findall(
            r"<\?\s*([A-Za-z_:][A-Za-z0-9_.:-]*)",
            text,
        )
        if any(target.lower() != "xml" for target in processing_targets):
            return ["html: processing_instruction_forbidden"]
        try:
            root = _rp_etree.fromstring(text)
        except (_rp_etree.ParseError, ValueError):
            return ["html: invalid_xhtml"]
        if root.tag.rsplit("}", 1)[-1].lower() != "html":
            return ["html: root_not_html"]
        errors = []
        forbidden_elements = {
            "applet", "base", "embed", "form", "frame", "frameset",
            "iframe", "link", "math", "object", "script", "svg",
        }
        resource_attributes = {
            "action", "archive", "background", "base", "cite", "codebase",
            "data", "formaction", "icon", "longdesc", "manifest", "ping",
            "poster", "profile", "src", "srcset", "usemap",
        }
        for element in root.iter():
            local = element.tag.rsplit("}", 1)[-1].lower()
            if local in forbidden_elements:
                errors.append(f"html: element_forbidden={local}")
            if (local == "meta"
                    and str(element.attrib.get("http-equiv") or "").strip()):
                errors.append("html: meta_http_equiv_forbidden")
            if local == "style":
                errors.append("html: style_element_forbidden")
            for raw_name, raw_value in element.attrib.items():
                name = raw_name.rsplit("}", 1)[-1].lower()
                value = raw_value.strip().lower()
                if name.startswith("on"):
                    errors.append("html: event_handler_forbidden")
                elif name in resource_attributes and value:
                    errors.append(f"html: resource_attribute_forbidden={name}")
                elif name == "href" and value and not value.startswith("#"):
                    errors.append("html: external_href_forbidden")
                elif name == "style" and value:
                    errors.append("html: style_attribute_forbidden")
        return sorted(set(errors))
    return ["text: unknown_validation_profile"]


def _assert_output_contract(text):
    root = _RP_OUTPUT_CONTRACT["root_type"]
    if root == "text":
        errors = _rp_validate_text_media(text)
        assert not errors, __RP_PREFIX__ + " " + "; ".join(errors)
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
