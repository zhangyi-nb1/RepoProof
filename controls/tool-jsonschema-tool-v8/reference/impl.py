import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, SchemaError


class UserInputError(ValueError):
    pass


_DIALECTS = {
    "https://json-schema.org/draft/2020-12/schema",
    "https://json-schema.org/draft/2020-12/schema#",
}


def _pointer(parts) -> str:
    escaped = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "" if not escaped else "/" + "/".join(escaped)


def _reject_external_refs(value) -> None:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if reference is not None and (
            not isinstance(reference, str) or not reference.startswith("#")
        ):
            raise UserInputError("only in-document fragment $ref values are allowed")
        for child in value.values():
            _reject_external_refs(child)
    elif isinstance(value, list):
        for child in value:
            _reject_external_refs(child)


def _error_records(error, depth: int = 0):
    instance_path = list(error.absolute_path)
    schema_path = list(error.absolute_schema_path)
    yield {
        "depth": depth,
        "instance_path": instance_path,
        "instance_pointer": _pointer(instance_path),
        "message": str(error.message),
        "schema_path": schema_path,
        "schema_pointer": _pointer(schema_path),
        "validator": "" if error.validator is None else str(error.validator),
    }
    for child in error.context:
        yield from _error_records(child, depth + 1)


def extract(input_path: Path) -> str:
    try:
        raw = input_path.read_text(encoding="utf-8")
        if not raw.strip():
            raise UserInputError("input JSON is empty")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise UserInputError("input must be a JSON object")
        if set(document) != {"schema", "instance"}:
            raise UserInputError("input must contain exactly schema and instance")

        schema = document["schema"]
        if not isinstance(schema, (dict, bool)):
            raise UserInputError("schema must be an object or boolean")
        if isinstance(schema, dict):
            dialect = schema.get("$schema")
            if dialect is not None and dialect not in _DIALECTS:
                raise UserInputError("only JSON Schema Draft 2020-12 is supported")
        _reject_external_refs(schema)

        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        records = []
        for error in validator.iter_errors(document["instance"]):
            records.extend(_error_records(error))
        records.sort(
            key=lambda item: (
                item["instance_pointer"],
                item["schema_pointer"],
                item["depth"],
                item["validator"],
                item["message"],
            )
        )
        payload = {
            "valid": not records,
            "error_count": len(records),
            "errors": records,
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except UserInputError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, SchemaError) as exc:
        raise UserInputError(f"invalid JSON Schema input: {exc}") from exc
    except Exception as exc:
        raise UserInputError(f"cannot validate JSON instance: {exc}") from exc
